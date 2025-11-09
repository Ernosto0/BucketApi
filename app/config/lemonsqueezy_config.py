"""
LemonSqueezy Configuration
Set up your LemonSqueezy API credentials and product mappings here.
"""

import os
from typing import Dict

class LemonSqueezyConfig:
    def __init__(self):
        # LemonSqueezy API credentials (set these in your environment variables)
        self.api_key = os.getenv("LEMONSQUEEZY_API_KEY", "")
        self.store_id = os.getenv("LEMONSQUEEZY_STORE_ID", "")
        self.webhook_secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET", "")
        
        # Base API URL
        self.api_base_url = "https://api.lemonsqueezy.com/v1"
        
        # Product and variant mappings
        # You'll need to update these with your actual LemonSqueezy product/variant IDs
        self.products = {
            "starter": {
                "product_id": os.getenv("LEMONSQUEEZY_STARTER_PRODUCT_ID", ""),
                "variant_id": os.getenv("LEMONSQUEEZY_STARTER_VARIANT_ID", ""),
                "price_cents": 999,  # $9.99/month
                "name": "Starter Plan"
            },
            "professional": {
                "product_id": os.getenv("LEMONSQUEEZY_PROFESSIONAL_PRODUCT_ID", ""),
                "variant_id": os.getenv("LEMONSQUEEZY_PROFESSIONAL_VARIANT_ID", ""),
                "price_cents": 2000,  # $20/month
                "name": "Professional Plan"
            },
            "enterprise": {
                "product_id": os.getenv("LEMONSQUEEZY_ENTERPRISE_PRODUCT_ID", ""),
                "variant_id": os.getenv("LEMONSQUEEZY_ENTERPRISE_VARIANT_ID", ""),
                "price_cents": 9900,  # $99/month
                "name": "Enterprise Plan"
            }
        }
        
        # Checkout URL template
        self.checkout_base_url = "https://your-store.lemonsqueezy.com/checkout/buy"
        
    def get_product_info(self, tier: str) -> Dict[str, str]:
        """Get product information for a subscription tier."""
        return self.products.get(tier, {})
    
    def get_variant_id(self, tier: str) -> str:
        """Get variant ID for a subscription tier."""
        product = self.products.get(tier, {})
        return product.get("variant_id", "")
    
    def is_configured(self) -> bool:
        """Check if LemonSqueezy is properly configured."""
        return bool(self.api_key and self.store_id)

# Global configuration instance
lemonsqueezy_config = LemonSqueezyConfig()
