"""
LemonSqueezy Subscription Service
Handles subscription management, webhooks, and tier-based token allocation.
"""

import uuid
import json
import logging
import hmac
import hashlib
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
# MongoDB operations handled through mongodb service
from fastapi import HTTPException
import httpx

from ..models import (
    Subscription, SubscriptionTier, CreateSubscriptionRequest, CreateSubscriptionResponse,
    SubscriptionStatusResponse, UpdateSubscriptionRequest, SubscriptionTiersResponse,
    SubscriptionEvent
)
from ..models_auth import User
from .mongodb import mongodb
from .api_pricing_service import api_pricing_service

logger = logging.getLogger(__name__)

class SubscriptionService:
    def __init__(self):
        # Subscription tiers configuration
        self.SUBSCRIPTION_TIERS = {
            "free": SubscriptionTier(
                name="free",
                display_name="Free",
                monthly_tokens=10000,  # Legacy - total tokens
                monthly_generation_tokens=3000,   # 3k for API generation
                monthly_execution_tokens=7000,    # 7k for API execution
                price_cents=0,
                features=[
                    "3,000 generation tokens/month (AI model usage)",
                    "7,000 execution tokens/month (API calls)",
                    "Basic API generation",
                    "Community support",
                    "Basic AI models (gpt-5-mini, Claude Haiku)"
                ],
                ai_models=["gpt-5-mini", "gpt-4o-mini", "claude-3-haiku"]
            ),
            "starter": SubscriptionTier(
                name="starter",
                display_name="Starter",
                monthly_tokens=50000,  # Legacy - total tokens
                monthly_generation_tokens=15000,  # 15k for API generation
                monthly_execution_tokens=35000,   # 35k for API execution
                price_cents=900,  # $9/month
                features=[
                    "15,000 generation tokens/month (AI model usage)",
                    "35,000 execution tokens/month (API calls)",
                    "Priority AI model access",
                    "Email support",
                    "API analytics",
                    "Advanced AI models"
                ],
                ai_models=["gpt-5-mini", "gpt-4o-mini", "gpt-4", "claude-3-haiku", "claude-3-sonnet"]
            ),
            "professional": SubscriptionTier(
                name="professional",
                display_name="Professional",
                monthly_tokens=200000,  # Legacy - total tokens
                monthly_generation_tokens=60000,   # 60k for API generation
                monthly_execution_tokens=140000,   # 140k for API execution
                price_cents=2900,  # $29/month
                features=[
                    "60,000 generation tokens/month (AI model usage)",
                    "140,000 execution tokens/month (API calls)",
                    "All AI models including GPT-4, Claude-3 Opus",
                    "Custom API complexity settings",
                    "Priority support",
                    "Advanced analytics"
                ],
                ai_models=["gpt-5-mini", "gpt-4o-mini", "gpt-4", "gpt-4-turbo", "claude-3-haiku", "claude-3-sonnet", "claude-3-opus"]
            ),
            "enterprise": SubscriptionTier(
                name="enterprise",
                display_name="Enterprise",
                monthly_tokens=1000000,  # Legacy - total tokens
                monthly_generation_tokens=300000,  # 300k for API generation
                monthly_execution_tokens=700000,   # 700k for API execution
                price_cents=9900,  # $99/month
                features=[
                    "300,000 generation tokens/month (AI model usage)",
                    "700,000 execution tokens/month (API calls)",
                    "All AI models including latest GPT-4 and Claude-4",
                    "Custom integrations",
                    "Dedicated support",
                    "White-label options",
                    "Custom rate limits"
                ],
                ai_models=["gpt-5-mini", "gpt-4o-mini", "gpt-4", "gpt-4-turbo", "claude-3-haiku", "claude-3-sonnet", "claude-3-opus", "claude-4"]
            )
        }
        
        # LemonSqueezy configuration (set these via environment variables)
        self.lemonsqueezy_api_key = None  # Set from environment
        self.lemonsqueezy_store_id = None  # Set from environment
        self.webhook_secret = None  # Set from environment
        
        logger.info("SubscriptionService initialized")
    
    async def get_available_tiers(self, user_id: Optional[str] = None) -> SubscriptionTiersResponse:
        """Get all available subscription tiers."""
        try:
            current_tier = None
            if user_id:
                subscription = await self.get_user_subscription(user_id)
                current_tier = subscription.tier if subscription else "free"
            
            return SubscriptionTiersResponse(
                success=True,
                tiers=list(self.SUBSCRIPTION_TIERS.values()),
                current_tier=current_tier
            )
        except Exception as e:
            logger.error(f"Failed to get subscription tiers: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get subscription tiers: {str(e)}")
    
    async def get_user_subscription(self, user_id: str) -> Optional[Subscription]:
        """Get current subscription for a user."""
        try:
            db_subscription = mongodb.subscriptions.find_one({
                "user_id": user_id,
                "status": {"$in": ["active", "past_due", "paused"]}
            }, sort=[("created_at", -1)])
            
            if not db_subscription:
                return None
                
            return Subscription(
                id=db_subscription["_id"],
                user_id=db_subscription["user_id"],
                lemonsqueezy_subscription_id=db_subscription["lemonsqueezy_subscription_id"],
                lemonsqueezy_customer_id=db_subscription["lemonsqueezy_customer_id"],
                lemonsqueezy_product_id=db_subscription["lemonsqueezy_product_id"],
                lemonsqueezy_variant_id=db_subscription["lemonsqueezy_variant_id"],
                tier=db_subscription["tier"],
                status=db_subscription["status"],
                current_period_start=db_subscription.get("current_period_start"),
                current_period_end=db_subscription.get("current_period_end"),
                trial_start=db_subscription.get("trial_start"),
                trial_end=db_subscription.get("trial_end"),
                monthly_token_allocation=db_subscription["monthly_token_allocation"],
                created_at=db_subscription["created_at"],
                updated_at=db_subscription["updated_at"]
            )
                
        except Exception as e:
            logger.error(f"Failed to get user subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get user subscription: {str(e)}")
    
    async def create_lemonsqueezy_checkout(self, user_id: str, tier: str) -> str:
        """Create a LemonSqueezy checkout URL for a subscription tier."""
        
        if tier not in self.SUBSCRIPTION_TIERS:
            raise HTTPException(status_code=400, detail=f"Invalid subscription tier: {tier}")
        
        tier_info = self.SUBSCRIPTION_TIERS[tier]
        
        # Get LemonSqueezy configuration directly from environment
        import os
        
        store_id = os.getenv("LEMONSQUEEZY_STORE_ID")
        if not store_id:
            raise HTTPException(status_code=500, detail="LemonSqueezy store ID not configured")
        
        # Get variant ID for the tier (LemonSqueezy checkout uses variant ID)
        variant_id = None
        if tier == "starter":
            variant_id = os.getenv("LEMONSQUEEZY_STARTER_VARIANT_ID")
            logger.info(f"Starter variant ID from env: {variant_id}")
        elif tier == "professional":
            variant_id = os.getenv("LEMONSQUEEZY_PROFESSIONAL_VARIANT_ID")
        elif tier == "enterprise":
            variant_id = os.getenv("LEMONSQUEEZY_ENTERPRISE_VARIANT_ID")
        
        if not variant_id:
            logger.error(f"Variant ID not found for tier: {tier}. Available env vars: LEMONSQUEEZY_STARTER_VARIANT_ID={os.getenv('LEMONSQUEEZY_STARTER_VARIANT_ID')}")
            raise HTTPException(status_code=500, detail=f"Variant ID not configured for tier: {tier}")
        
        try:
            # Create checkout using LemonSqueezy Checkouts API
            api_key = os.getenv("LEMONSQUEEZY_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
            
            checkout_data = {
                "data": {
                    "type": "checkouts",
                    "attributes": {
                        "checkout_data": {
                            "custom": {
                                "user_id": user_id,
                                "tier": tier,
                                "source": "api_generator"
                            }
                        },
                        "product_options": {
                            "name": f"{tier_info.display_name} Plan",
                            "description": f"Upgrade to {tier_info.display_name} for enhanced features and {tier_info.monthly_tokens:,} tokens per month.",
                            "redirect_url": "http://localhost:8001/subscription/success"
                        }
                    },
                    "relationships": {
                        "store": {
                            "data": {
                                "type": "stores",
                                "id": str(store_id)
                            }
                        },
                        "variant": {
                            "data": {
                                "type": "variants",
                                "id": str(variant_id)
                            }
                        }
                    }
                }
            }
            
            # Make API request to create checkout
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.lemonsqueezy.com/v1/checkouts",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/vnd.api+json",
                        "Accept": "application/vnd.api+json"
                    },
                    json=checkout_data
                )
                
                if response.status_code != 201:
                    logger.error(f"LemonSqueezy API error: {response.status_code} - {response.text}")
                    raise HTTPException(status_code=500, detail=f"Failed to create checkout: {response.text}")
                
                checkout_response = response.json()
                checkout_url = checkout_response["data"]["attributes"]["url"]
                
                logger.info(f"Created LemonSqueezy checkout URL for user {user_id}, tier {tier}: {checkout_url}")
                return checkout_url
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP error creating LemonSqueezy checkout: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create checkout: {str(e)}")
        except Exception as e:
            logger.error(f"Failed to create LemonSqueezy checkout URL: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create checkout URL: {str(e)}")
    
    async def handle_subscription_webhook(self, payload: Dict[str, Any], signature: str) -> bool:
        """Handle LemonSqueezy webhook events."""
        try:
            # Verify webhook signature
            if not self._verify_webhook_signature(payload, signature):
                logger.warning("Invalid webhook signature")
                return False
            
            event_type = payload.get("meta", {}).get("event_name", "")
            event_id = payload.get("meta", {}).get("event_id", "")
            
            # Check if we've already processed this event
            existing_event = mongodb.subscription_events.find_one({
                "lemonsqueezy_event_id": event_id
            })
            
            if existing_event:
                logger.info(f"Event {event_id} already processed")
                return True
            
            # Process the event based on type
            if event_type == "subscription_created":
                await self._handle_subscription_created(payload)
            elif event_type == "subscription_updated":
                await self._handle_subscription_updated(payload)
            elif event_type == "subscription_cancelled":
                await self._handle_subscription_cancelled(payload)
            elif event_type == "subscription_payment_success":
                await self._handle_payment_success(payload)
            elif event_type == "subscription_payment_failed":
                await self._handle_payment_failed(payload)
            else:
                logger.warning(f"Unhandled event type: {event_type}")
            
            # Record the event as processed
            await self._record_webhook_event(payload, processed=True)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to handle webhook: {str(e)}")
            # Record the event as failed
            await self._record_webhook_event(payload, processed=False)
            return False
    
    async def _handle_subscription_created(self, payload: Dict[str, Any]):
        """Handle subscription creation webhook."""
        data = payload.get("data", {})
        attributes = data.get("attributes", {})
        
        # Extract subscription data
        lemonsqueezy_subscription_id = str(data.get("id", ""))
        lemonsqueezy_customer_id = str(attributes.get("customer_id", ""))
        product_id = str(attributes.get("product_id", ""))
        variant_id = str(attributes.get("variant_id", ""))
        
        # Map variant to tier (you'll need to configure this based on your LemonSqueezy setup)
        tier = self._map_variant_to_tier(variant_id)
        
        # Find user by customer ID (you'll need to store this mapping)
        user_id = await self._get_user_by_customer_id(lemonsqueezy_customer_id)
        
        if not user_id:
            logger.error(f"User not found for customer ID: {lemonsqueezy_customer_id}")
            return
        
        tier_info = self.SUBSCRIPTION_TIERS.get(tier)
        if not tier_info:
            logger.error(f"Invalid tier: {tier}")
            return
        
        # Create subscription record
        subscription_id = str(uuid.uuid4())
        
        # Create subscription document
        subscription_doc = {
            "_id": subscription_id,
            "user_id": user_id,
            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
            "lemonsqueezy_customer_id": lemonsqueezy_customer_id,
            "lemonsqueezy_product_id": product_id,
            "lemonsqueezy_variant_id": variant_id,
            "tier": tier,
            "status": "active",
            "current_period_start": datetime.fromisoformat(attributes.get("current_period_start", "")),
            "current_period_end": datetime.fromisoformat(attributes.get("current_period_end", "")),
            "monthly_token_allocation": tier_info.monthly_tokens,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Insert subscription
        mongodb.subscriptions.insert_one(subscription_doc)
        
        # Update user's subscription info
        mongodb.users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "subscription_tier": tier,
                    "subscription_status": "active",
                    "monthly_token_allocation": tier_info.monthly_tokens,
                    "lemonsqueezy_customer_id": lemonsqueezy_customer_id,
                    "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id
                }
            }
        )
        
        # Allocate separated tokens for the new subscription
        await api_pricing_service.allocate_separated_monthly_tokens(
            user_id=user_id,
            generation_tokens=tier_info.monthly_generation_tokens,
            execution_tokens=tier_info.monthly_execution_tokens,
            source="subscription_created"
        )
        
        logger.info(f"Created subscription for user {user_id}, tier {tier}")
    
    async def _handle_subscription_updated(self, payload: Dict[str, Any]):
        """Handle subscription update webhook."""
        # Similar implementation to subscription_created
        # Update existing subscription record
        pass
    
    async def _handle_subscription_cancelled(self, payload: Dict[str, Any]):
        """Handle subscription cancellation webhook."""
        # Update subscription status to cancelled
        # Keep existing tokens until they expire
        pass
    
    async def _handle_payment_success(self, payload: Dict[str, Any]):
        """Handle successful payment webhook."""
        # Allocate new monthly tokens
        # Update subscription period
        pass
    
    async def _handle_payment_failed(self, payload: Dict[str, Any]):
        """Handle failed payment webhook."""
        # Update subscription status to past_due
        # Send notification to user
        pass
    
    def _verify_webhook_signature(self, payload: Dict[str, Any], signature: str) -> bool:
        """Verify LemonSqueezy webhook signature."""
        if not self.webhook_secret:
            logger.warning("Webhook secret not configured")
            return False
        
        # Implement LemonSqueezy signature verification
        # This is a placeholder implementation
        return True
    
    def _map_variant_to_tier(self, variant_id: str) -> str:
        """Map LemonSqueezy variant ID to subscription tier."""
        # You'll need to configure this mapping based on your LemonSqueezy products
        variant_mapping = {
            "starter_variant_id": "starter",
            "professional_variant_id": "professional", 
            "enterprise_variant_id": "enterprise"
        }
        return variant_mapping.get(variant_id, "starter")
    
    async def _get_user_by_customer_id(self, customer_id: str) -> Optional[str]:
        """Get user ID by LemonSqueezy customer ID."""
        try:
            user = mongodb.users.find_one({
                "lemonsqueezy_customer_id": customer_id
            })
            return user["_id"] if user else None
        except Exception as e:
            logger.error(f"Failed to get user by customer ID: {str(e)}")
            return None
    
    async def _record_webhook_event(self, payload: Dict[str, Any], processed: bool = False):
        """Record webhook event in database."""
        try:
            event_id = str(uuid.uuid4())
            meta = payload.get("meta", {})
            
            # Create event document
            event_doc = {
                "_id": event_id,
                "subscription_id": "",  # Will be filled if available
                "user_id": "",  # Will be filled if available
                "event_type": meta.get("event_name", ""),
                "lemonsqueezy_event_id": meta.get("event_id", ""),
                "event_data": json.dumps(payload),
                "processed": processed,
                "created_at": datetime.utcnow()
            }
            
            # Insert event
            mongodb.subscription_events.insert_one(event_doc)
                
        except Exception as e:
            logger.error(f"Failed to record webhook event: {str(e)}")

# Global instance
subscription_service = SubscriptionService()
