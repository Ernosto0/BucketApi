"""
Domain Verification Service
Handles DNS TXT and HTTP file verification for custom domains.
"""

import os
import logging
import httpx
from datetime import datetime, timedelta
from typing import Optional, Tuple
import dns.resolver
import dns.exception

from ..models import (
    CustomDomain, DomainStatus, VerificationMethod,
    VerifyDomainResponse
)
from .mongodb import mongodb
from .domain_service import domain_service

logger = logging.getLogger(__name__)

# Verification settings
VERIFICATION_TIMEOUT_HOURS = 48
MAX_VERIFICATION_ATTEMPTS_PER_DAY = 10
DNS_QUERY_TIMEOUT = 10  # seconds
HTTP_VERIFICATION_TIMEOUT = 10  # seconds


class DomainVerificationService:
    """Service for verifying domain ownership"""
    
    def __init__(self):
        # Configure DNS resolver with common public DNS servers
        self.resolver = dns.resolver.Resolver()
        self.resolver.nameservers = [
            '8.8.8.8',      # Google
            '8.8.4.4',      # Google
            '1.1.1.1',      # Cloudflare
            '1.0.0.1',      # Cloudflare
            '9.9.9.9',      # Quad9
        ]
        self.resolver.timeout = DNS_QUERY_TIMEOUT
        self.resolver.lifetime = DNS_QUERY_TIMEOUT
        
        logger.info("DomainVerificationService initialized")
    
    async def verify_domain(
        self, 
        domain_id: str, 
        user_id: str
    ) -> VerifyDomainResponse:
        """
        Verify domain ownership using the configured verification method.
        """
        try:
            # Get domain record
            domain_doc = mongodb.custom_domains.find_one({
                "_id": domain_id,
                "user_id": user_id
            })
            
            if not domain_doc:
                return VerifyDomainResponse(
                    success=False,
                    status=DomainStatus.FAILED,
                    message="Domain not found or you don't have access to it."
                )
            
            domain = domain_doc["domain"]
            verification_token = domain_doc["verification_token"]
            verification_method = VerificationMethod(domain_doc["verification_method"])
            current_status = DomainStatus(domain_doc["status"])
            
            # Check if already verified/active
            if current_status in [DomainStatus.VERIFIED, DomainStatus.ACTIVE, DomainStatus.ACTIVATING]:
                return VerifyDomainResponse(
                    success=True,
                    status=current_status,
                    message=f"Domain {domain} is already {current_status.value}."
                )
            
            # Check if verification has expired
            expires_at = domain_doc.get("expires_at")
            if expires_at and datetime.utcnow() > expires_at:
                await domain_service.update_domain_status(
                    domain_id, 
                    DomainStatus.FAILED,
                    "Verification period expired. Please re-register the domain."
                )
                return VerifyDomainResponse(
                    success=False,
                    status=DomainStatus.FAILED,
                    message="Verification period has expired. Please delete and re-register the domain."
                )
            
            # Check rate limiting
            verification_attempts = domain_doc.get("verification_attempts", 0)
            last_attempt = domain_doc.get("last_verification_attempt")
            
            # Reset counter if last attempt was more than 24 hours ago
            if last_attempt and (datetime.utcnow() - last_attempt) > timedelta(hours=24):
                mongodb.custom_domains.update_one(
                    {"_id": domain_id},
                    {"$set": {"verification_attempts": 0}}
                )
                verification_attempts = 0
            
            if verification_attempts >= MAX_VERIFICATION_ATTEMPTS_PER_DAY:
                next_retry = last_attempt + timedelta(hours=24) if last_attempt else datetime.utcnow()
                return VerifyDomainResponse(
                    success=False,
                    status=current_status,
                    message=f"Too many verification attempts. Please try again in 24 hours.",
                    next_retry_at=next_retry
                )
            
            # Update status to verifying
            mongodb.custom_domains.update_one(
                {"_id": domain_id},
                {"$set": {"status": DomainStatus.VERIFYING.value}}
            )
            
            # Increment verification attempt counter
            await domain_service.increment_verification_attempt(domain_id)
            
            # Perform verification based on method
            if verification_method == VerificationMethod.DNS_TXT:
                verified, message = await self._verify_dns_txt(domain, verification_token)
            else:
                verified, message = await self._verify_http_file(domain, verification_token)
            
            if verified:
                # Update status to verified
                await domain_service.update_domain_status(domain_id, DomainStatus.VERIFIED)
                
                logger.info(f"Domain {domain} verified successfully for user {user_id}")
                
                return VerifyDomainResponse(
                    success=True,
                    status=DomainStatus.VERIFIED,
                    message=f"Domain {domain} verified successfully! Your domain will be activated automatically when you first access it.",
                    verification_token=verification_token
                )
            else:
                # Update status back to pending
                mongodb.custom_domains.update_one(
                    {"_id": domain_id},
                    {"$set": {"status": DomainStatus.PENDING.value}}
                )
                
                # Build DNS record info for response
                dns_record = f"_bucketapi-verify.{domain}"
                
                return VerifyDomainResponse(
                    success=False,
                    status=DomainStatus.PENDING,
                    message=message,
                    verification_token=verification_token,
                    dns_record=dns_record
                )
                
        except Exception as e:
            logger.error(f"Failed to verify domain {domain_id}: {str(e)}", exc_info=True)
            return VerifyDomainResponse(
                success=False,
                status=DomainStatus.FAILED,
                message=f"Verification failed: {str(e)}"
            )
    
    async def _verify_dns_txt(
        self, 
        domain: str, 
        verification_token: str
    ) -> Tuple[bool, str]:
        """
        Verify domain ownership via DNS TXT record.
        
        Expected record: _bucketapi-verify.{domain} TXT {verification_token}
        """
        try:
            # LOCAL TESTING: Skip DNS check for .local domains or if SKIP_DNS_VERIFICATION is set
            skip_dns = os.getenv('SKIP_DNS_VERIFICATION', '').lower() == 'true'
            is_local_domain = domain.endswith('.local') or domain.endswith('.localhost') or '127.0.0.1' in domain
            
            if skip_dns or is_local_domain:
                logger.info(f"LOCAL TESTING: Skipping DNS verification for {domain} (skip_dns={skip_dns}, is_local={is_local_domain})")
                return True, "DNS verification successful (local testing mode)"
            
            # Build the verification record name
            # For subdomain like api.example.com, check _bucketapi-verify.api.example.com
            verification_record = f"_bucketapi-verify.{domain}"
            
            logger.info(f"Checking DNS TXT record: {verification_record}")
            
            try:
                # Query TXT records
                answers = self.resolver.resolve(verification_record, 'TXT')
                
                # Check each TXT record
                for rdata in answers:
                    # TXT records come wrapped in quotes
                    txt_value = str(rdata).strip('"')
                    logger.debug(f"Found TXT record: {txt_value}")
                    
                    if txt_value == verification_token:
                        logger.info(f"DNS TXT verification successful for {domain}")
                        return True, "DNS verification successful"
                
                # Token not found in any TXT record
                return False, f"DNS TXT record found but token doesn't match. Expected value: {verification_token}"
                
            except dns.resolver.NXDOMAIN:
                return False, f"DNS record not found. Please add a TXT record for {verification_record}"
            except dns.resolver.NoAnswer:
                return False, f"No TXT records found for {verification_record}. Please add the verification record."
            except dns.resolver.NoNameservers:
                return False, "Unable to reach DNS servers. Please try again later."
            except dns.exception.Timeout:
                return False, "DNS query timed out. Please try again later."
            except Exception as dns_error:
                logger.warning(f"DNS query error: {dns_error}")
                return False, f"DNS query failed: {str(dns_error)}"
                
        except Exception as e:
            logger.error(f"DNS TXT verification error for {domain}: {str(e)}")
            return False, f"Verification error: {str(e)}"
    
    async def _verify_http_file(
        self, 
        domain: str, 
        verification_token: str
    ) -> Tuple[bool, str]:
        """
        Verify domain ownership via HTTP file.
        
        Expected file: http://{domain}/.well-known/bucketapi-verify.txt
        Content: {verification_token}
        """
        try:
            verification_url = f"http://{domain}/.well-known/bucketapi-verify.txt"
            
            logger.info(f"Checking HTTP verification file: {verification_url}")
            
            async with httpx.AsyncClient(timeout=HTTP_VERIFICATION_TIMEOUT) as client:
                try:
                    response = await client.get(
                        verification_url,
                        follow_redirects=True,
                        headers={"User-Agent": "BucketAPI-Verification/1.0"}
                    )
                    
                    if response.status_code == 200:
                        content = response.text.strip()
                        
                        if content == verification_token:
                            logger.info(f"HTTP file verification successful for {domain}")
                            return True, "HTTP file verification successful"
                        else:
                            return False, f"Verification file content doesn't match. Expected: {verification_token}"
                    
                    elif response.status_code == 404:
                        return False, f"Verification file not found at {verification_url}. Please create the file."
                    else:
                        return False, f"HTTP request failed with status {response.status_code}"
                        
                except httpx.TimeoutException:
                    return False, f"HTTP request to {domain} timed out. Please ensure the server is accessible."
                except httpx.ConnectError:
                    return False, f"Could not connect to {domain}. Please ensure your server is running and accessible."
                except Exception as http_error:
                    return False, f"HTTP request failed: {str(http_error)}"
                    
        except Exception as e:
            logger.error(f"HTTP file verification error for {domain}: {str(e)}")
            return False, f"Verification error: {str(e)}"
    
    async def check_verification_status(self, domain_id: str) -> Optional[DomainStatus]:
        """Check current verification status of a domain"""
        try:
            domain_doc = mongodb.custom_domains.find_one({"_id": domain_id})
            if domain_doc:
                return DomainStatus(domain_doc["status"])
            return None
        except Exception as e:
            logger.error(f"Failed to check verification status: {str(e)}")
            return None
    
    async def revalidate_active_domain(self, domain: str) -> bool:
        """
        Re-verify an active domain to ensure DNS is still configured.
        Used for periodic health checks on active domains.
        """
        try:
            domain_doc = mongodb.custom_domains.find_one({
                "domain": domain.lower(),
                "status": DomainStatus.ACTIVE.value
            })
            
            if not domain_doc:
                return False
            
            verification_token = domain_doc["verification_token"]
            verification_method = VerificationMethod(domain_doc["verification_method"])
            
            if verification_method == VerificationMethod.DNS_TXT:
                verified, _ = await self._verify_dns_txt(domain, verification_token)
            else:
                verified, _ = await self._verify_http_file(domain, verification_token)
            
            if verified:
                # Update last_verified_at
                mongodb.custom_domains.update_one(
                    {"_id": domain_doc["_id"]},
                    {"$set": {"last_verified_at": datetime.utcnow()}}
                )
                return True
            else:
                # Mark domain as failed if re-verification fails
                logger.warning(f"Domain {domain} failed re-verification")
                await domain_service.update_domain_status(
                    domain_doc["_id"],
                    DomainStatus.FAILED,
                    "Domain re-verification failed. DNS record may have been removed."
                )
                return False
                
        except Exception as e:
            logger.error(f"Failed to revalidate domain {domain}: {str(e)}")
            return False


# Global instance
domain_verification_service = DomainVerificationService()

