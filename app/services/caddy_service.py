"""
Caddy Service
Handles communication with Caddy API for dynamic domain configuration.
"""

import os
import logging
import json
from datetime import datetime
from typing import Optional, Dict, Any, List
import httpx

logger = logging.getLogger(__name__)

# Caddy API configuration
CADDY_ADMIN_URL = os.getenv("CADDY_ADMIN_URL", "http://localhost:2019")
CADDY_API_TIMEOUT = 30  # seconds


class CaddyService:
    """Service for managing Caddy reverse proxy configuration"""
    
    def __init__(self):
        self.admin_url = CADDY_ADMIN_URL
        self.timeout = CADDY_API_TIMEOUT
        logger.info(f"CaddyService initialized with admin URL: {self.admin_url}")
    
    async def health_check(self) -> bool:
        """Check if Caddy API is reachable"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.admin_url}/config/")
                return response.status_code == 200
        except Exception as e:
            logger.warning(f"Caddy health check failed: {str(e)}")
            return False
    
    async def get_config(self) -> Optional[Dict[str, Any]]:
        """Get current Caddy configuration"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.admin_url}/config/")
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.error(f"Failed to get Caddy config: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error getting Caddy config: {str(e)}")
            return None
    
    async def add_domain(
        self, 
        domain: str, 
        backend_host: str = "localhost",
        backend_port: int = 8000
    ) -> tuple[bool, str]:
        """
        Add a domain to Caddy configuration.
        
        This creates a route that:
        1. Matches the custom domain
        2. Reverse proxies to the FastAPI backend
        3. Adds necessary headers
        
        Note: With on-demand TLS configured in Caddyfile, Caddy will 
        automatically request SSL certificates when the domain is accessed.
        """
        try:
            # Generate a unique route ID
            route_id = f"domain_{domain.replace('.', '_')}"
            
            # Build the route configuration
            route_config = {
                "@id": route_id,
                "match": [{
                    "host": [domain]
                }],
                "handle": [{
                    "handler": "reverse_proxy",
                    "upstreams": [{
                        "dial": f"{backend_host}:{backend_port}"
                    }],
                    "headers": {
                        "request": {
                            "set": {
                                "Host": ["{http.request.host}"],
                                "X-Real-IP": ["{http.request.remote.host}"],
                                "X-Forwarded-For": ["{http.request.remote.host}"],
                                "X-Forwarded-Proto": ["{http.request.scheme}"],
                                "X-Custom-Domain": [domain]
                            }
                        }
                    }
                }],
                "terminal": True
            }
            
            # First, check if route already exists
            existing_config = await self.get_config()
            if existing_config:
                # Navigate to routes
                routes = self._get_routes_from_config(existing_config)
                for route in routes:
                    if route.get("@id") == route_id:
                        logger.info(f"Domain {domain} already configured in Caddy")
                        return True, "Domain already configured"
            
            # Add the route to Caddy
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Try to add to existing server routes
                # Caddy API endpoint for adding routes
                response = await client.post(
                    f"{self.admin_url}/config/apps/http/servers/srv0/routes",
                    json=route_config,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    logger.info(f"Successfully added domain {domain} to Caddy")
                    return True, "Domain added successfully"
                else:
                    error_msg = f"Failed to add domain to Caddy: {response.status_code} - {response.text}"
                    logger.error(error_msg)
                    return False, error_msg
                    
        except httpx.ConnectError:
            error_msg = "Could not connect to Caddy API. Is Caddy running?"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Error adding domain to Caddy: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    async def remove_domain(self, domain: str) -> tuple[bool, str]:
        """Remove a domain from Caddy configuration"""
        try:
            route_id = f"domain_{domain.replace('.', '_')}"
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Delete the route by ID
                response = await client.delete(
                    f"{self.admin_url}/id/{route_id}",
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 204]:
                    logger.info(f"Successfully removed domain {domain} from Caddy")
                    return True, "Domain removed successfully"
                elif response.status_code == 404:
                    # Route doesn't exist, consider it success
                    logger.info(f"Domain {domain} not found in Caddy (already removed)")
                    return True, "Domain not found (already removed)"
                else:
                    error_msg = f"Failed to remove domain from Caddy: {response.status_code}"
                    logger.error(error_msg)
                    return False, error_msg
                    
        except httpx.ConnectError:
            error_msg = "Could not connect to Caddy API. Is Caddy running?"
            logger.error(error_msg)
            return False, error_msg
        except Exception as e:
            error_msg = f"Error removing domain from Caddy: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return False, error_msg
    
    async def check_ssl_status(self, domain: str) -> Optional[Dict[str, Any]]:
        """
        Check SSL certificate status for a domain.
        
        Note: With on-demand TLS, certificates are generated when first accessed.
        This method checks if a certificate has been issued.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Query certificate info from Caddy
                response = await client.get(
                    f"{self.admin_url}/pki/ca/local/certificates",
                    headers={"Accept": "application/json"}
                )
                
                if response.status_code == 200:
                    certs = response.json()
                    # Look for certificate matching domain
                    for cert in certs if isinstance(certs, list) else []:
                        subjects = cert.get("subjects", [])
                        if domain in subjects or f"*.{domain}" in subjects:
                            return {
                                "issued": True,
                                "domain": domain,
                                "expires": cert.get("not_after"),
                                "issuer": cert.get("issuer")
                            }
                    
                    return {"issued": False, "domain": domain}
                else:
                    logger.warning(f"Could not check SSL status: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"Error checking SSL status for {domain}: {str(e)}")
            return None
    
    async def reload_config(self) -> bool:
        """
        Reload Caddy configuration.
        
        Note: Usually not needed as Caddy applies changes dynamically,
        but useful for forcing a refresh.
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # Caddy doesn't have a specific reload endpoint
                # Config changes are applied immediately
                # We can trigger a config reload by posting the current config
                current_config = await self.get_config()
                if current_config:
                    response = await client.post(
                        f"{self.admin_url}/load",
                        json=current_config,
                        headers={"Content-Type": "application/json"}
                    )
                    return response.status_code == 200
                return False
                
        except Exception as e:
            logger.error(f"Error reloading Caddy config: {str(e)}")
            return False
    
    async def get_domain_routes(self) -> List[Dict[str, Any]]:
        """Get all custom domain routes from Caddy"""
        try:
            config = await self.get_config()
            if not config:
                return []
            
            routes = self._get_routes_from_config(config)
            
            # Filter for our custom domain routes
            custom_routes = []
            for route in routes:
                route_id = route.get("@id", "")
                if route_id.startswith("domain_"):
                    # Extract domain from route
                    match = route.get("match", [{}])[0]
                    hosts = match.get("host", [])
                    if hosts:
                        custom_routes.append({
                            "route_id": route_id,
                            "domain": hosts[0],
                            "config": route
                        })
            
            return custom_routes
            
        except Exception as e:
            logger.error(f"Error getting domain routes: {str(e)}")
            return []
    
    def _get_routes_from_config(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract routes from Caddy config"""
        try:
            return config.get("apps", {}).get("http", {}).get("servers", {}).get("srv0", {}).get("routes", [])
        except (KeyError, TypeError):
            return []
    
    async def add_domain_with_retry(
        self, 
        domain: str, 
        backend_host: str = "localhost",
        backend_port: int = 8000,
        max_retries: int = 3
    ) -> tuple[bool, str]:
        """Add domain with retry logic"""
        for attempt in range(max_retries):
            success, message = await self.add_domain(domain, backend_host, backend_port)
            if success:
                return True, message
            
            if attempt < max_retries - 1:
                logger.warning(f"Retry {attempt + 1}/{max_retries} for adding domain {domain}")
                import asyncio
                await asyncio.sleep(2 ** attempt)  # Exponential backoff
        
        return False, f"Failed after {max_retries} attempts: {message}"


# Global instance
caddy_service = CaddyService()




