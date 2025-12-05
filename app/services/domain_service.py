"""
Domain Service
Handles custom domain management including registration, validation, and activation.
"""

import uuid
import secrets
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import HTTPException

from ..models import (
    CustomDomain, DomainStatus, VerificationMethod, SSLCertificateStatus,
    CreateDomainRequest, CreateDomainResponse, VerifyDomainResponse,
    DomainStatusResponse, ListDomainsResponse, DeleteDomainResponse,
    DomainMapping
)
from .mongodb import mongodb

logger = logging.getLogger(__name__)


# Domain limits per subscription tier
MAX_DOMAINS_PER_TIER = {
    "free": 0,
    "starter": 1,
    "professional": 3,
    "enterprise": 999  # Effectively unlimited
}

# Reserved/blacklisted domains
BLACKLISTED_DOMAINS = {
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "bucketapi.com",
    "www.bucketapi.com",
    "api.bucketapi.com",
    "app.bucketapi.com",
}

# Reserved TLDs
RESERVED_TLDS = {
    "local",
    "localhost",
    "internal",
    "invalid",
    "test",
}


class DomainService:
    """Service for managing custom domains"""
    
    def __init__(self):
        logger.info("DomainService initialized")
    
    def _validate_domain_format(self, domain: str) -> bool:
        """Validate domain format (FQDN)"""
        # Domain regex pattern
        pattern = r'^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$'
        return bool(re.match(pattern, domain))
    
    def _is_blacklisted(self, domain: str) -> bool:
        """Check if domain is blacklisted"""
        domain_lower = domain.lower()
        
        # Check exact match
        if domain_lower in BLACKLISTED_DOMAINS:
            return True
        
        # Check TLD
        tld = domain_lower.split('.')[-1]
        if tld in RESERVED_TLDS:
            return True
        
        # Check if it's an IP address pattern
        ip_pattern = r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$'
        if re.match(ip_pattern, domain_lower):
            return True
        
        return False
    
    def _generate_verification_token(self) -> str:
        """Generate a secure verification token"""
        return secrets.token_urlsafe(32)
    
    async def get_user_domain_count(self, user_id: str) -> int:
        """Get count of domains for a user"""
        try:
            count = mongodb.custom_domains.count_documents({
                "user_id": user_id,
                "status": {"$ne": DomainStatus.FAILED.value}
            })
            return count
        except Exception as e:
            logger.error(f"Failed to get domain count for user {user_id}: {str(e)}")
            return 0
    
    async def get_user_subscription_tier(self, user_id: str) -> str:
        """Get user's subscription tier"""
        try:
            user = mongodb.users.find_one({"_id": user_id})
            if user:
                return user.get("subscription_tier", "free")
            return "free"
        except Exception as e:
            logger.error(f"Failed to get subscription tier for user {user_id}: {str(e)}")
            return "free"
    
    async def check_domain_limit(self, user_id: str) -> tuple[bool, str]:
        """Check if user can create more domains"""
        tier = await self.get_user_subscription_tier(user_id)
        max_domains = MAX_DOMAINS_PER_TIER.get(tier, 0)
        current_count = await self.get_user_domain_count(user_id)
        
        if current_count >= max_domains:
            if max_domains == 0:
                return False, f"Custom domains are not available on the {tier} tier. Please upgrade to use custom domains."
            return False, f"You have reached the maximum number of domains ({max_domains}) for your {tier} tier."
        
        return True, ""
    
    async def create_domain(
        self, 
        user_id: str, 
        request: CreateDomainRequest
    ) -> CreateDomainResponse:
        """Create/register a new custom domain for a user (can serve multiple APIs)"""
        try:
            domain = request.domain.lower().strip()
            api_slug = request.api_slug  # Optional: default API for root path
            
            # Validate domain format
            if not self._validate_domain_format(domain):
                return CreateDomainResponse(
                    success=False,
                    message=f"Invalid domain format: {domain}. Please use a valid domain like api.example.com"
                )
            
            # Check if domain is blacklisted
            if self._is_blacklisted(domain):
                return CreateDomainResponse(
                    success=False,
                    message=f"Domain {domain} is not allowed."
                )
            
            # Check domain limit
            can_create, limit_message = await self.check_domain_limit(user_id)
            if not can_create:
                return CreateDomainResponse(
                    success=False,
                    message=limit_message
                )
            
            # If api_slug is provided, verify it exists and belongs to user
            if api_slug:
                # API slug in database uses format: user_id_api_name (but we store clean slug)
                saved_api = mongodb.saved_apis.find_one({
                    "user_id": user_id,
                    "api_slug": api_slug
                })
                
                if not saved_api:
                    # Try with full slug (user_id_api_slug)
                    full_slug = f"{user_id}_{api_slug}"
                    saved_api = mongodb.saved_apis.find_one({
                        "user_id": user_id,
                        "api_slug": full_slug
                    })
                    if saved_api:
                        api_slug = full_slug
                
                if not saved_api:
                    return CreateDomainResponse(
                        success=False,
                        message=f"API '{api_slug}' not found or you don't have access to it. If you want to register the domain without a default API, omit the api_slug field."
                    )
            
            # Check if domain already exists
            existing_domain = mongodb.custom_domains.find_one({"domain": domain})
            if existing_domain:
                if existing_domain["user_id"] != user_id:
                    return CreateDomainResponse(
                        success=False,
                        message=f"Domain {domain} is already registered by another user."
                    )
                
                # Domain exists and belongs to this user
                existing_status = DomainStatus(existing_domain["status"])
                
                # If domain is already active or verified, allow updating default API
                if existing_status in [DomainStatus.ACTIVE, DomainStatus.VERIFIED, DomainStatus.ACTIVATING]:
                    # Update default API if provided
                    if api_slug:
                        mongodb.custom_domains.update_one(
                            {"_id": existing_domain["_id"]},
                            {"$set": {"api_slug": api_slug}}
                        )
                        existing_domain["api_slug"] = api_slug
                        existing_domain_model = self._doc_to_model(existing_domain)
                        return CreateDomainResponse(
                            success=True,
                            message=f"Domain {domain} default API updated to {api_slug}.",
                            domain=existing_domain_model
                        )
                    else:
                        # Return existing domain
                        existing_domain_model = self._doc_to_model(existing_domain)
                        return CreateDomainResponse(
                            success=True,
                            message=f"Domain {domain} is already {existing_status.value}. You can manage it from the domains list.",
                            domain=existing_domain_model
                        )
                
                # If domain is pending/failed/verifying, return the existing domain so user can continue
                # This allows them to continue verification without creating a duplicate
                existing_domain_model = self._doc_to_model(existing_domain)
                return CreateDomainResponse(
                    success=True,
                    message=f"Domain {domain} was previously registered but not verified. You can continue with verification below.",
                    domain=existing_domain_model
                )
            
            # Generate verification token
            verification_token = self._generate_verification_token()
            
            # Create domain record
            domain_id = str(uuid.uuid4())
            now = datetime.utcnow()
            
            domain_doc = {
                "_id": domain_id,
                "user_id": user_id,
                "api_slug": api_slug,  # Optional: default API for root path
                "domain": domain,
                "status": DomainStatus.PENDING.value,
                "verification_token": verification_token,
                "verification_method": request.verification_method.value,
                "ssl_certificate_status": None,
                "caddy_route_id": None,
                "created_at": now,
                "verified_at": None,
                "last_verified_at": None,
                "activated_at": None,
                "expires_at": now + timedelta(hours=48),  # 48 hour verification window
                "error_message": None,
                "verification_attempts": 0,
                "last_verification_attempt": None
            }
            
            mongodb.custom_domains.insert_one(domain_doc)
            
            # Build verification instructions
            dns_record = f"_bucketapi-verify.{domain}"
            
            if request.verification_method == VerificationMethod.DNS_TXT:
                instructions = f"""To verify ownership of {domain}, please add a DNS TXT record:

1. Go to your DNS provider's settings
2. Add a new TXT record:
   - Name/Host: _bucketapi-verify.{domain.split('.')[0] if '.' in domain else domain}
   - Value: {verification_token}
   - TTL: 300 (or lowest available)

3. Wait for DNS propagation (can take up to 24-48 hours)
4. Click 'Verify Domain' to complete the verification

Note: DNS changes may take time to propagate. You can try verification multiple times."""
            else:
                instructions = f"""To verify ownership of {domain} using HTTP file verification:

1. Create a file at: http://{domain}/.well-known/bucketapi-verify.txt
2. Add this content to the file: {verification_token}
3. Make sure the file is publicly accessible
4. Click 'Verify Domain' to complete the verification"""
            
            # Create response model
            custom_domain = CustomDomain(
                id=domain_id,
                user_id=user_id,
                api_slug=api_slug,  # Optional: default API
                domain=domain,
                status=DomainStatus.PENDING,
                verification_token=verification_token,
                verification_method=request.verification_method,
                ssl_certificate_status=None,
                caddy_route_id=None,
                created_at=now,
                verified_at=None,
                last_verified_at=None,
                activated_at=None,
                expires_at=now + timedelta(hours=48),
                error_message=None,
                verification_attempts=0,
                last_verification_attempt=None
            )
            
            if api_slug:
                logger.info(f"Created domain {domain} for user {user_id} with default API {api_slug}")
            else:
                logger.info(f"Created domain {domain} for user {user_id} (no default API - use /api/{{api_slug}} paths)")
            
            return CreateDomainResponse(
                success=True,
                message=f"Domain {domain} registered successfully. Please complete verification.",
                domain=custom_domain,
                verification_instructions=instructions,
                dns_record=dns_record
            )
            
        except Exception as e:
            logger.error(f"Failed to create domain: {str(e)}", exc_info=True)
            return CreateDomainResponse(
                success=False,
                message=f"Failed to create domain: {str(e)}"
            )
    
    async def get_domain(self, domain_id: str, user_id: str) -> Optional[CustomDomain]:
        """Get a domain by ID"""
        try:
            domain_doc = mongodb.custom_domains.find_one({
                "_id": domain_id,
                "user_id": user_id
            })
            
            if not domain_doc:
                return None
            
            return self._doc_to_model(domain_doc)
            
        except Exception as e:
            logger.error(f"Failed to get domain {domain_id}: {str(e)}")
            return None
    
    async def get_domain_by_name(self, domain: str) -> Optional[CustomDomain]:
        """Get a domain by domain name"""
        try:
            domain_doc = mongodb.custom_domains.find_one({"domain": domain.lower()})
            
            if not domain_doc:
                return None
            
            return self._doc_to_model(domain_doc)
            
        except Exception as e:
            logger.error(f"Failed to get domain {domain}: {str(e)}")
            return None
    
    async def get_domain_mapping(self, domain: str) -> Optional[DomainMapping]:
        """Get domain mapping for routing (user_id, optional default api_slug)"""
        try:
            domain_doc = mongodb.custom_domains.find_one({
                "domain": domain.lower(),
                "status": DomainStatus.ACTIVE.value
            })
            
            if not domain_doc:
                return None
            
            return DomainMapping(
                domain=domain_doc["domain"],
                user_id=domain_doc["user_id"],
                api_slug=domain_doc.get("api_slug"),  # Optional default API
                status=DomainStatus(domain_doc["status"])
            )
            
        except Exception as e:
            logger.error(f"Failed to get domain mapping for {domain}: {str(e)}")
            return None
    
    async def list_domains(
        self, 
        user_id: str, 
        api_slug: Optional[str] = None
    ) -> ListDomainsResponse:
        """List all domains for a user, optionally filtered by API"""
        try:
            query = {"user_id": user_id}
            if api_slug:
                # Handle both slug formats: clean slug and user_id_slug format
                # Try to find domains with either format
                full_slug = f"{user_id}_{api_slug}"
                # Use $or within the query, but keep user_id filter
                query = {
                    "user_id": user_id,
                    "$or": [
                        {"api_slug": api_slug},
                        {"api_slug": full_slug}
                    ]
                }
            
            domain_docs = list(mongodb.custom_domains.find(query).sort("created_at", -1))
            
            domains = [self._doc_to_model(doc) for doc in domain_docs]
            
            logger.info(f"Found {len(domains)} domain(s) for user {user_id}, api_slug={api_slug}")
            
            return ListDomainsResponse(
                success=True,
                domains=domains,
                total=len(domains)
            )
            
        except Exception as e:
            logger.error(f"Failed to list domains for user {user_id}: {str(e)}", exc_info=True)
            return ListDomainsResponse(
                success=False,
                domains=[],
                total=0
            )
    
    async def update_domain_status(
        self, 
        domain_id: str, 
        status: DomainStatus,
        error_message: Optional[str] = None
    ) -> bool:
        """Update domain status"""
        try:
            update_data = {
                "status": status.value,
                "error_message": error_message
            }
            
            if status == DomainStatus.VERIFIED:
                update_data["verified_at"] = datetime.utcnow()
            elif status == DomainStatus.ACTIVE:
                update_data["activated_at"] = datetime.utcnow()
            
            result = mongodb.custom_domains.update_one(
                {"_id": domain_id},
                {"$set": update_data}
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            logger.error(f"Failed to update domain status: {str(e)}")
            return False
    
    async def delete_domain(self, domain_id: str, user_id: str) -> DeleteDomainResponse:
        """Delete a domain"""
        try:
            # Get domain first
            domain_doc = mongodb.custom_domains.find_one({
                "_id": domain_id,
                "user_id": user_id
            })
            
            if not domain_doc:
                return DeleteDomainResponse(
                    success=False,
                    message="Domain not found or you don't have access to it."
                )
            
            domain = domain_doc["domain"]
            
            # If domain is active, we need to remove it from Caddy first
            if domain_doc["status"] == DomainStatus.ACTIVE.value:
                # Import caddy_service to remove domain
                try:
                    from .caddy_service import caddy_service
                    await caddy_service.remove_domain(domain)
                except Exception as caddy_error:
                    logger.warning(f"Failed to remove domain from Caddy: {caddy_error}")
                    # Continue with deletion even if Caddy removal fails
            
            # Delete from database
            result = mongodb.custom_domains.delete_one({
                "_id": domain_id,
                "user_id": user_id
            })
            
            if result.deleted_count > 0:
                logger.info(f"Deleted domain {domain} for user {user_id}")
                return DeleteDomainResponse(
                    success=True,
                    message=f"Domain {domain} deleted successfully."
                )
            
            return DeleteDomainResponse(
                success=False,
                message="Failed to delete domain."
            )
            
        except Exception as e:
            logger.error(f"Failed to delete domain {domain_id}: {str(e)}")
            return DeleteDomainResponse(
                success=False,
                message=f"Failed to delete domain: {str(e)}"
            )
    
    async def increment_verification_attempt(self, domain_id: str) -> bool:
        """Increment verification attempt counter"""
        try:
            result = mongodb.custom_domains.update_one(
                {"_id": domain_id},
                {
                    "$inc": {"verification_attempts": 1},
                    "$set": {"last_verification_attempt": datetime.utcnow()}
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to increment verification attempt: {str(e)}")
            return False
    
    async def check_domain_for_caddy(self, domain: str) -> bool:
        """
        Check if a domain is allowed for SSL certificate generation.
        Called by Caddy's on-demand TLS before issuing certificate.
        """
        try:
            domain_doc = mongodb.custom_domains.find_one({
                "domain": domain.lower(),
                "status": {"$in": [DomainStatus.VERIFIED.value, DomainStatus.ACTIVE.value]}
            })
            
            if domain_doc:
                # Update status to activating if it was verified
                if domain_doc["status"] == DomainStatus.VERIFIED.value:
                    mongodb.custom_domains.update_one(
                        {"_id": domain_doc["_id"]},
                        {"$set": {"status": DomainStatus.ACTIVATING.value}}
                    )
                    logger.info(f"Domain {domain} status updated to activating")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking domain for Caddy: {str(e)}")
            return False
    
    async def activate_domain(self, domain_id: str) -> bool:
        """Activate a domain after SSL certificate is issued"""
        try:
            result = mongodb.custom_domains.update_one(
                {"_id": domain_id},
                {
                    "$set": {
                        "status": DomainStatus.ACTIVE.value,
                        "ssl_certificate_status": SSLCertificateStatus.ISSUED.value,
                        "activated_at": datetime.utcnow()
                    }
                }
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"Failed to activate domain: {str(e)}")
            return False
    
    def _doc_to_model(self, doc: Dict[str, Any]) -> CustomDomain:
        """Convert MongoDB document to CustomDomain model"""
        return CustomDomain(
            id=doc["_id"],
            user_id=doc["user_id"],
            api_slug=doc["api_slug"],
            domain=doc["domain"],
            status=DomainStatus(doc["status"]),
            verification_token=doc["verification_token"],
            verification_method=VerificationMethod(doc["verification_method"]),
            ssl_certificate_status=SSLCertificateStatus(doc["ssl_certificate_status"]) if doc.get("ssl_certificate_status") else None,
            caddy_route_id=doc.get("caddy_route_id"),
            created_at=doc["created_at"],
            verified_at=doc.get("verified_at"),
            last_verified_at=doc.get("last_verified_at"),
            activated_at=doc.get("activated_at"),
            expires_at=doc.get("expires_at"),
            error_message=doc.get("error_message"),
            verification_attempts=doc.get("verification_attempts", 0),
            last_verification_attempt=doc.get("last_verification_attempt")
        )


# Global instance
domain_service = DomainService()

