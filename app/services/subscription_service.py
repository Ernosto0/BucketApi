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
        # Custom domain limits per subscription tier
        self.MAX_DOMAINS_PER_TIER = {
            "free": 0,
            "starter": 1,
            "professional": 3,
            "enterprise": 999  # Effectively unlimited
        }
        
        # Subscription tiers configuration
        self.SUBSCRIPTION_TIERS = {
            "free": SubscriptionTier(
                name="free",
                display_name="Free",
                monthly_tokens=10000,  # Legacy - total tokens
                monthly_generation_tokens=3000,   # 3k for API generation
                monthly_execution_tokens=7000,    # 7k for API execution
                monthly_api_generations=1,  # 1 API generation per month
                price_cents=0,
                features=[
                    "1 API generation/month",
                    "7,000 execution tokens/month (API calls)",
                    "Basic API generation",
                    "Community support",
                    "Basic AI models (gpt-5-mini, Claude Haiku)",
                    "No custom domains"
                ],
                ai_models=["gpt-5-mini", "gpt-4o-mini", "claude-3-haiku"]
            ),
            "starter": SubscriptionTier(
                name="starter",
                display_name="Starter",
                monthly_tokens=50000,  # Legacy - total tokens
                monthly_generation_tokens=15000,  # 15k for API generation
                monthly_execution_tokens=35000,   # 35k for API execution
                monthly_api_generations=4,  # 4 API generations per month
                price_cents=999,  # $9.99/month
                features=[
                    "4 API generations/month",
                    "35,000 execution tokens/month (API calls)",
                    "1 custom domain with SSL",
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
                monthly_api_generations=20,  # 20 API generations per month
                price_cents=2000,  # $20/month
                features=[
                    "20 API generations/month",
                    "140,000 execution tokens/month (API calls)",
                    "3 custom domains with SSL",
                    "All AI models including GPT-5, Claude-4 Opus",
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
                monthly_api_generations=100,  # 100 API generations per month
                price_cents=9900,  # $99/month
                features=[
                    "100 API generations/month",
                    "700,000 execution tokens/month (API calls)",
                    "Unlimited custom domains with SSL",
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
    
    def get_max_domains_for_tier(self, tier: str) -> int:
        """Get the maximum number of custom domains allowed for a subscription tier."""
        return self.MAX_DOMAINS_PER_TIER.get(tier, 0)
    
    async def check_domain_limit(self, user_id: str) -> tuple[bool, int, int]:
        """
        Check if user can create more domains.
        
        Returns:
            tuple: (can_create, current_count, max_allowed)
        """
        try:
            # Get user's subscription tier
            user = mongodb.users.find_one({"_id": user_id})
            tier = user.get("subscription_tier", "free") if user else "free"
            
            max_domains = self.get_max_domains_for_tier(tier)
            
            # Count current domains (excluding failed ones)
            current_count = mongodb.custom_domains.count_documents({
                "user_id": user_id,
                "status": {"$ne": "failed"}
            })
            
            can_create = current_count < max_domains
            return can_create, current_count, max_domains
            
        except Exception as e:
            logger.error(f"Error checking domain limit: {str(e)}")
            return False, 0, 0
    
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
            # Include cancelled subscriptions that haven't expired yet
            db_subscription = mongodb.subscriptions.find_one({
                "user_id": user_id,
                "status": {"$in": ["active", "past_due", "paused", "cancelled"]}
            }, sort=[("created_at", -1)])
            
            if not db_subscription:
                return None
            
            # Check if cancelled subscription has expired
            subscription = Subscription(
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
            
            # If subscription is cancelled, check if it has expired
            if subscription.status == "cancelled" and subscription.current_period_end:
                if datetime.utcnow() > subscription.current_period_end:
                    # Subscription has expired, downgrade user to free tier
                    await self._expire_cancelled_subscription(user_id, subscription.id)
                    return None  # Return None so user is treated as free tier
            
            return subscription
                
        except Exception as e:
            logger.error(f"Failed to get user subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get user subscription: {str(e)}")
    
    async def _expire_cancelled_subscription(self, user_id: str, subscription_id: str):
        """Handle expiration of a cancelled subscription by downgrading user to free tier."""
        try:
            # Update subscription status to expired
            mongodb.subscriptions.update_one(
                {"_id": subscription_id},
                {
                    "$set": {
                        "status": "expired",
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Update user to free tier
            mongodb.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "subscription_tier": "free",
                        "subscription_status": "active",  # Free tier is active
                        "monthly_token_allocation": 10000  # Free tier allocation
                    }
                }
            )
            
            # Allocate free tier tokens
            from app.services.api_pricing_service import api_pricing_service
            await api_pricing_service.allocate_separated_monthly_tokens(
                user_id=user_id,
                generation_tokens=3000,  # Free tier: 3k generation tokens
                execution_tokens=7000,   # Free tier: 7k execution tokens
                source="subscription_expired"
            )
            
            logger.info(f"Expired cancelled subscription for user {user_id}, downgraded to free tier")
            
        except Exception as e:
            logger.error(f"Failed to expire cancelled subscription: {str(e)}", exc_info=True)
    
    async def create_lemonsqueezy_checkout(self, user_id: str, tier: str) -> str:
        """Create a LemonSqueezy checkout URL for a subscription tier."""
        
        if tier not in self.SUBSCRIPTION_TIERS:
            raise HTTPException(status_code=400, detail=f"Invalid subscription tier: {tier}")
        
        # Free tier doesn't use LemonSqueezy
        if tier == "free":
            raise HTTPException(status_code=400, detail="Free tier does not require a checkout. Use change_subscription_tier instead.")
        
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
        
        # Get LemonSqueezy API key
        api_key = os.getenv("LEMONSQUEEZY_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
        
        # Verify variant exists before creating checkout
        try:
            async with httpx.AsyncClient() as client:
                # First, verify the variant exists
                variant_response = await client.get(
                    f"https://api.lemonsqueezy.com/v1/variants/{variant_id}",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/vnd.api+json"
                    }
                )
                
                if variant_response.status_code == 404:
                    # logger.error(f"Variant {variant_id} not found in LemonSqueezy. Please verify:")
                    # logger.error(f"  1. The variant ID is correct in your LemonSqueezy dashboard")
                    # logger.error(f"  2. The variant belongs to store {store_id}")
                    # logger.error(f"  3. The variant is not archived or deleted")
                    raise HTTPException(
                        status_code=404, 
                        detail=f"Variant ID {variant_id} not found in LemonSqueezy. Please verify the variant exists and belongs to your store."
                    )
                elif variant_response.status_code != 200:
                    logger.warning(f"Could not verify variant {variant_id}: {variant_response.status_code} - {variant_response.text}")
                    # Continue anyway - might be a permissions issue but variant could still exist
                else:
                    variant_data = variant_response.json()
                    variant_store_id = variant_data.get("data", {}).get("relationships", {}).get("store", {}).get("data", {}).get("id")
                    if variant_store_id and str(variant_store_id) != str(store_id):
                        # logger.error(f"Variant {variant_id} belongs to store {variant_store_id}, but you're using store {store_id}")
                        raise HTTPException(
                            status_code=400,
                            detail=f"Variant {variant_id} belongs to a different store. Please use the correct store ID or variant ID."
                        )
                    # logger.info(f"✅ Verified variant {variant_id} exists and belongs to store {store_id}")
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Could not verify variant existence: {str(e)}. Continuing with checkout creation...")
        
        try:
            # Create checkout using LemonSqueezy Checkouts API
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
                            "redirect_url": f"https://bucketapi.com/subscription/success"
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
            # logger.info(f"Creating checkout with store_id={store_id}, variant_id={variant_id}")
            
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
                    error_text = response.text
                    logger.error(f"LemonSqueezy API error: {response.status_code} - {error_text}")
                    
                    # Provide more helpful error messages
                    if response.status_code == 404:
                        try:
                            error_data = response.json()
                            error_detail = error_data.get("errors", [{}])[0].get("detail", "")
                            if "variant" in error_detail.lower():
                                raise HTTPException(
                                    status_code=404,
                                    detail=f"Variant ID {variant_id} not found. Please verify the variant exists in your LemonSqueezy dashboard and belongs to store {store_id}."
                                )
                        except:
                            pass
                    
                    raise HTTPException(status_code=500, detail=f"Failed to create checkout: {error_text}")
                
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
    
    async def handle_subscription_webhook(self, payload: Dict[str, Any], signature: str, raw_body: bytes = None) -> bool:
        """Handle LemonSqueezy webhook events."""
        try:
            # Verify webhook signature
            if not self._verify_webhook_signature(payload, signature, raw_body):
                logger.warning("Invalid webhook signature")
                return False
            
            event_type = payload.get("meta", {}).get("event_name", "")
            event_id = payload.get("meta", {}).get("event_id", "")
            webhook_id = payload.get("meta", {}).get("webhook_id", "")
            
            # Use webhook_id as fallback if event_id is missing
            dedup_id = event_id if event_id else webhook_id
            
            # Check if we've already processed this event (only if we have a valid ID)
            if dedup_id:
                existing_event = mongodb.subscription_events.find_one({
                    "lemonsqueezy_event_id": dedup_id
                })
                
                if existing_event:
                    logger.info(f"Event {event_type} ({dedup_id}) already processed")
                    return True
            
            # Process the event based on type
            if event_type == "order_created":
                # Order created is the first event when a subscription is purchased
                await self._handle_order_created(payload)
            elif event_type == "subscription_created":
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
    
    async def _handle_order_created(self, payload: Dict[str, Any]):
        """Handle order creation webhook - this fires first when a subscription is purchased."""
        try:
            data = payload.get("data", {})
            attributes = data.get("attributes", {})
            
            # Check if this is a subscription order
            first_order_item = attributes.get("first_order_item", {})
            if not first_order_item:
                logger.info("Order created but no subscription items found")
                return
            
            # Extract order data
            order_id = str(data.get("id", ""))
            customer_id = str(attributes.get("customer_id", ""))
            user_email = attributes.get("user_email", "")
            variant_id = str(first_order_item.get("variant_id", ""))
            product_id = str(first_order_item.get("product_id", ""))
            
            # Get custom data from meta (this is where our user_id lives!)
            custom_data = payload.get("meta", {}).get("custom_data", {})
            user_id = custom_data.get("user_id")
            tier = custom_data.get("tier")
            
            logger.info(f"Order created - Order ID: {order_id}, User ID from custom: {user_id}, Tier: {tier}, Email: {user_email}")
            
            # Fallback: try to get user by email if custom data missing
            if not user_id and user_email:
                user_id = await self._get_user_by_email(user_email)
                logger.info(f"Found user by email: {user_id}")
            
            # Fallback: try variant mapping if tier is missing
            if not tier and variant_id:
                tier = self._map_variant_to_tier(variant_id)
                logger.info(f"Mapped variant {variant_id} to tier: {tier}")
            
            if not user_id:
                logger.error(f"Cannot process order - user not found. Email: {user_email}, Custom data: {custom_data}")
                return
            
            if not tier:
                logger.error(f"Cannot process order - tier not found. Variant: {variant_id}, Custom data: {custom_data}")
                return
            
            tier_info = self.SUBSCRIPTION_TIERS.get(tier)
            if not tier_info:
                logger.error(f"Invalid tier: {tier}")
                return
            
            # Check if user already has an active subscription
            existing_sub = await self.get_user_subscription(user_id)
            if existing_sub and existing_sub.status == "active":
                logger.info(f"User {user_id} already has active subscription, skipping order creation")
                return
            
            # Create subscription record from order
            subscription_id = str(uuid.uuid4())
            current_time = datetime.utcnow()
            
            # For subscriptions, we'll get the actual subscription_id later in subscription_created event
            # For now, use order_id as temporary identifier
            subscription_doc = {
                "_id": subscription_id,
                "user_id": user_id,
                "lemonsqueezy_subscription_id": "",  # Will be filled by subscription_created event
                "lemonsqueezy_customer_id": customer_id,
                "lemonsqueezy_product_id": product_id,
                "lemonsqueezy_variant_id": variant_id,
                "lemonsqueezy_order_id": order_id,  # Track the order
                "tier": tier,
                "status": "active",
                "current_period_start": current_time,
                "current_period_end": current_time + timedelta(days=30),  # Default 30 days
                "monthly_token_allocation": tier_info.monthly_tokens,
                "created_at": current_time,
                "updated_at": current_time
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
                        "lemonsqueezy_customer_id": customer_id
                    }
                }
            )
            
            # Allocate separated tokens for the new subscription
            await api_pricing_service.allocate_separated_monthly_tokens(
                user_id=user_id,
                generation_tokens=tier_info.monthly_generation_tokens,
                execution_tokens=tier_info.monthly_execution_tokens,
                source="order_created"
            )
            
            logger.info(f"✅ Successfully activated {tier} subscription for user {user_id} from order {order_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle order_created: {str(e)}", exc_info=True)
    
    async def _handle_subscription_created(self, payload: Dict[str, Any]):
        """Handle subscription creation webhook - updates the subscription with actual subscription ID."""
        try:
            data = payload.get("data", {})
            attributes = data.get("attributes", {})
            
            # Extract subscription data
            lemonsqueezy_subscription_id = str(data.get("id", ""))
            lemonsqueezy_customer_id = str(attributes.get("customer_id", ""))
            product_id = str(attributes.get("product_id", ""))
            variant_id = str(attributes.get("variant_id", ""))
            order_id = str(attributes.get("order_id", ""))
            
            # Try to find existing subscription from order_created event
            existing_sub = mongodb.subscriptions.find_one({
                "lemonsqueezy_order_id": order_id,
                "user_id": {"$exists": True}
            })
            
            if existing_sub:
                # Parse period dates with fallbacks
                current_time = datetime.utcnow()
                try:
                    period_start = datetime.fromisoformat(attributes.get("current_period_start", "")) if attributes.get("current_period_start") else current_time
                except (ValueError, TypeError):
                    period_start = current_time
                
                try:
                    period_end = datetime.fromisoformat(attributes.get("current_period_end", "")) if attributes.get("current_period_end") else current_time + timedelta(days=30)
                except (ValueError, TypeError):
                    period_end = current_time + timedelta(days=30)
                
                # Update existing subscription with actual subscription ID
                mongodb.subscriptions.update_one(
                    {"_id": existing_sub["_id"]},
                    {
                        "$set": {
                            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                            "current_period_start": period_start,
                            "current_period_end": period_end,
                            "updated_at": datetime.utcnow()
                        }
                    }
                )
                
                # Update user record
                mongodb.users.update_one(
                    {"_id": existing_sub["user_id"]},
                    {
                        "$set": {
                            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id
                        }
                    }
                )
                
                logger.info(f"Updated subscription {existing_sub['_id']} with LemonSqueezy subscription ID {lemonsqueezy_subscription_id}")
                return
            
            # If no existing subscription (order_created event didn't fire), create one
            logger.warning(f"No existing subscription found for order {order_id}, creating new one")
            
            # Map variant to tier
            tier = self._map_variant_to_tier(variant_id)
            
            # Get user_id from custom data or fallbacks
            custom_data = payload.get("meta", {}).get("custom_data", {})
            user_id = custom_data.get("user_id")
            
            if not user_id:
                user_id = await self._get_user_by_customer_id(lemonsqueezy_customer_id)
            
            if not user_id:
                user_email = attributes.get("user_email")
                if user_email:
                    user_id = await self._get_user_by_email(user_email)
            
            if not user_id:
                logger.error(f"User not found for subscription. Customer ID: {lemonsqueezy_customer_id}")
                return
            
            tier_info = self.SUBSCRIPTION_TIERS.get(tier)
            if not tier_info:
                logger.error(f"Invalid tier: {tier}")
                return
            
            # Create new subscription record
            subscription_id = str(uuid.uuid4())
            
            # Parse period dates with fallbacks
            current_time = datetime.utcnow()
            try:
                current_period_start = datetime.fromisoformat(attributes.get("current_period_start", "")) if attributes.get("current_period_start") else current_time
            except (ValueError, TypeError):
                current_period_start = current_time
            
            try:
                current_period_end = datetime.fromisoformat(attributes.get("current_period_end", "")) if attributes.get("current_period_end") else current_time + timedelta(days=30)
            except (ValueError, TypeError):
                current_period_end = current_time + timedelta(days=30)
            
            subscription_doc = {
                "_id": subscription_id,
                "user_id": user_id,
                "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                "lemonsqueezy_customer_id": lemonsqueezy_customer_id,
                "lemonsqueezy_product_id": product_id,
                "lemonsqueezy_variant_id": variant_id,
                "lemonsqueezy_order_id": order_id,
                "tier": tier,
                "status": "active",
                "current_period_start": current_period_start,
                "current_period_end": current_period_end,
                "monthly_token_allocation": tier_info.monthly_tokens,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            
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
            
            # Allocate separated tokens
            await api_pricing_service.allocate_separated_monthly_tokens(
                user_id=user_id,
                generation_tokens=tier_info.monthly_generation_tokens,
                execution_tokens=tier_info.monthly_execution_tokens,
                source="subscription_created"
            )
            
            logger.info(f"Created subscription for user {user_id}, tier {tier}")
            
        except Exception as e:
            logger.error(f"Failed to handle subscription_created: {str(e)}", exc_info=True)
    
    async def _handle_subscription_updated(self, payload: Dict[str, Any]):
        """Handle subscription update webhook - can also activate new subscriptions."""
        try:
            data = payload.get("data", {})
            attributes = data.get("attributes", {})
            
            # Extract subscription data
            lemonsqueezy_subscription_id = str(data.get("id", ""))
            lemonsqueezy_customer_id = str(attributes.get("customer_id", ""))
            product_id = str(attributes.get("product_id", ""))
            variant_id = str(attributes.get("variant_id", ""))
            order_id = str(attributes.get("order_id", ""))
            status = attributes.get("status", "")
            
            logger.info(f"Subscription updated - ID: {lemonsqueezy_subscription_id}, Status: {status}, Order: {order_id}")
            
            # Try to find existing subscription
            existing_sub = mongodb.subscriptions.find_one({
                "$or": [
                    {"lemonsqueezy_subscription_id": lemonsqueezy_subscription_id},
                    {"lemonsqueezy_order_id": order_id}
                ]
            })
            
            # Get user_id from custom data or find user
            custom_data = payload.get("meta", {}).get("custom_data", {})
            user_id = custom_data.get("user_id")
            tier = custom_data.get("tier")
            
            # If no existing subscription or no user_id yet, try to find user
            if not user_id:
                if existing_sub and existing_sub.get("user_id"):
                    user_id = existing_sub["user_id"]
                else:
                    user_id = await self._get_user_by_customer_id(lemonsqueezy_customer_id)
                    if not user_id:
                        user_email = attributes.get("user_email")
                        if user_email:
                            user_id = await self._get_user_by_email(user_email)
            
            if not user_id:
                logger.error(f"Cannot process subscription_updated - user not found. Customer: {lemonsqueezy_customer_id}, Custom data: {custom_data}")
                return
            
            # Get tier from variant if not in custom data
            if not tier:
                tier = self._map_variant_to_tier(variant_id)
            
            tier_info = self.SUBSCRIPTION_TIERS.get(tier)
            if not tier_info:
                logger.error(f"Invalid tier: {tier}")
                return
            
            current_time = datetime.utcnow()
            
            # Parse period dates if available
            period_start = current_time
            period_end = current_time + timedelta(days=30)
            
            renews_at = attributes.get("renews_at")
            if renews_at:
                try:
                    period_end = datetime.fromisoformat(renews_at.replace('Z', '+00:00'))
                except:
                    pass
            
            if existing_sub:
                # Update existing subscription
                update_data = {
                    "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                    "status": status,
                    "current_period_end": period_end,
                    "updated_at": current_time
                }
                
                mongodb.subscriptions.update_one(
                    {"_id": existing_sub["_id"]},
                    {"$set": update_data}
                )
                
                # Update user record
                mongodb.users.update_one(
                    {"_id": user_id},
                    {
                        "$set": {
                            "subscription_tier": tier,
                            "subscription_status": status,
                            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                            "lemonsqueezy_customer_id": lemonsqueezy_customer_id
                        }
                    }
                )
                
                logger.info(f"✅ Updated existing subscription {existing_sub['_id']} for user {user_id}")
                
            else:
                # No existing subscription - create new one (this handles the case where order_created didn't fire)
                logger.warning(f"No existing subscription found, creating new one from subscription_updated event")
                
                subscription_id = str(uuid.uuid4())
                
                subscription_doc = {
                    "_id": subscription_id,
                    "user_id": user_id,
                    "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                    "lemonsqueezy_customer_id": lemonsqueezy_customer_id,
                    "lemonsqueezy_product_id": product_id,
                    "lemonsqueezy_variant_id": variant_id,
                    "lemonsqueezy_order_id": order_id,
                    "tier": tier,
                    "status": status,
                    "current_period_start": period_start,
                    "current_period_end": period_end,
                    "monthly_token_allocation": tier_info.monthly_tokens,
                    "created_at": current_time,
                    "updated_at": current_time
                }
                
                mongodb.subscriptions.insert_one(subscription_doc)
                
                # Update user's subscription info
                mongodb.users.update_one(
                    {"_id": user_id},
                    {
                        "$set": {
                            "subscription_tier": tier,
                            "subscription_status": status,
                            "monthly_token_allocation": tier_info.monthly_tokens,
                            "lemonsqueezy_customer_id": lemonsqueezy_customer_id,
                            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id
                        }
                    }
                )
                
                # Allocate tokens for new subscription
                await api_pricing_service.allocate_separated_monthly_tokens(
                    user_id=user_id,
                    generation_tokens=tier_info.monthly_generation_tokens,
                    execution_tokens=tier_info.monthly_execution_tokens,
                    source="subscription_updated"
                )
                
                logger.info(f"✅ Created new {tier} subscription for user {user_id} from subscription_updated event")
                
        except Exception as e:
            logger.error(f"Failed to handle subscription_updated: {str(e)}", exc_info=True)
    
    async def _handle_subscription_cancelled(self, payload: Dict[str, Any]):
        """Handle subscription cancellation webhook."""
        try:
            data = payload.get("data", {})
            attributes = data.get("attributes", {})
            
            # Extract subscription data
            lemonsqueezy_subscription_id = str(data.get("id", ""))
            ends_at = attributes.get("ends_at")
            
            logger.info(f"Subscription cancelled webhook - ID: {lemonsqueezy_subscription_id}, Ends at: {ends_at}")
            
            # Find the subscription in our database
            db_subscription = mongodb.subscriptions.find_one({
                "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id
            })
            
            if not db_subscription:
                logger.warning(f"Subscription not found for cancellation: {lemonsqueezy_subscription_id}")
                return
            
            user_id = db_subscription["user_id"]
            
            # Parse the ends_at date
            ends_at_datetime = None
            if ends_at:
                try:
                    ends_at_datetime = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse ends_at date: {ends_at}")
                    ends_at_datetime = db_subscription.get("current_period_end")
            else:
                ends_at_datetime = db_subscription.get("current_period_end")
            
            # Update subscription status
            update_data = {
                "status": "cancelled",
                "updated_at": datetime.utcnow()
            }
            
            if ends_at_datetime:
                update_data["current_period_end"] = ends_at_datetime
            
            mongodb.subscriptions.update_one(
                {"_id": db_subscription["_id"]},
                {"$set": update_data}
            )
            
            # Downgrade user to free tier immediately
            # User retains execution tokens until period end, but API generation limit is downgraded immediately
            free_tier = self.SUBSCRIPTION_TIERS["free"]
            mongodb.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "subscription_status": "cancelled",
                        "subscription_tier": "free",  # Downgrade to free tier immediately
                        "monthly_token_allocation": free_tier.monthly_tokens
                    }
                }
            )
            
            logger.info(f"✅ Processed subscription cancellation for user {user_id}, downgraded to free tier")
            
        except Exception as e:
            logger.error(f"Failed to handle subscription_cancelled: {str(e)}", exc_info=True)
    
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
    
    def _verify_webhook_signature(self, payload: Dict[str, Any], signature: str, raw_body: bytes = None) -> bool:
        """Verify LemonSqueezy webhook signature."""
        import os
        webhook_secret = os.getenv("LEMONSQUEEZY_WEBHOOK_SECRET")
        
        # Check if this is a test webhook
        is_test_mode = payload.get("meta", {}).get("test_mode", False)
        
        if is_test_mode:
            logger.info("Test webhook received - skipping signature verification")
            return True
        
        if not webhook_secret:
            logger.warning("Webhook secret not configured")
            return False
        
        if not signature:
            logger.warning("No signature provided")
            return False
        
        try:
            # Use raw body if available, otherwise serialize payload
            if raw_body:
                payload_bytes = raw_body
            else:
                import json
                payload_bytes = json.dumps(payload, separators=(',', ':')).encode('utf-8')
            
            # LemonSqueezy uses HMAC-SHA256 for webhook signatures
            expected_signature = hmac.new(
                webhook_secret.encode('utf-8'),
                payload_bytes,
                hashlib.sha256
            ).hexdigest()
            
            # LemonSqueezy sends signature as "sha256=<hash>"
            if signature.startswith("sha256="):
                received_signature = signature[7:]  # Remove "sha256=" prefix
            else:
                received_signature = signature
            
            # Compare signatures
            is_valid = hmac.compare_digest(expected_signature, received_signature)
            
            if not is_valid:
                logger.warning(f"Signature mismatch. Expected: {expected_signature}, Received: {received_signature}")
            
            return is_valid
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {str(e)}")
            return False
    
    def _map_variant_to_tier(self, variant_id: str) -> str:
        """Map LemonSqueezy variant ID to subscription tier."""
        import os
        
        # Get actual variant IDs from environment
        variant_mapping = {
            os.getenv("LEMONSQUEEZY_STARTER_VARIANT_ID"): "starter",
            os.getenv("LEMONSQUEEZY_PROFESSIONAL_VARIANT_ID"): "professional", 
            os.getenv("LEMONSQUEEZY_ENTERPRISE_VARIANT_ID"): "enterprise"
        }
        
        tier = variant_mapping.get(variant_id)
        if tier:
            logger.info(f"Mapped variant {variant_id} to tier {tier}")
            return tier
        
        # Log unmapped variant for debugging
        logger.warning(f"Unknown variant ID: {variant_id}. Using 'starter' as fallback. Configured variants: {list(variant_mapping.keys())}")
        return "starter"
    
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
    
    async def _get_user_by_email(self, email: str) -> Optional[str]:
        """Get user ID by email address."""
        try:
            user = mongodb.users.find_one({
                "email": email
            })
            return user["_id"] if user else None
        except Exception as e:
            logger.error(f"Failed to get user by email: {str(e)}")
            return None
    
    async def _record_webhook_event(self, payload: Dict[str, Any], processed: bool = False):
        """Record webhook event in database."""
        try:
            event_id = str(uuid.uuid4())
            meta = payload.get("meta", {})
            
            # Use webhook_id as fallback if event_id is missing
            lemonsqueezy_event_id = meta.get("event_id", "") or meta.get("webhook_id", "")
            
            # Create event document
            event_doc = {
                "_id": event_id,
                "subscription_id": "",  # Will be filled if available
                "user_id": "",  # Will be filled if available
                "event_type": meta.get("event_name", ""),
                "lemonsqueezy_event_id": lemonsqueezy_event_id,
                "event_data": json.dumps(payload),
                "processed": processed,
                "created_at": datetime.utcnow()
            }
            
            # Insert event
            mongodb.subscription_events.insert_one(event_doc)
                
        except Exception as e:
            logger.error(f"Failed to record webhook event: {str(e)}")
    
    async def cancel_subscription(self, user_id: str) -> Dict[str, Any]:
        """Cancel user's subscription via LemonSqueezy API."""
        try:
            import os
            
            logger.info(f"Attempting to cancel subscription for user: {user_id}")
            
            # Get user's subscription
            subscription = await self.get_user_subscription(user_id)
            if not subscription:
                # Check if user has any subscription records at all
                all_subs = mongodb.subscriptions.find({"user_id": user_id}).sort("created_at", -1).limit(5)
                sub_list = list(all_subs)
                logger.warning(f"No active subscription found for user {user_id}. Found {len(sub_list)} total subscriptions: {[s.get('status', 'unknown') for s in sub_list]}")
                raise HTTPException(status_code=404, detail="No active subscription found")
            
            if subscription.status in ["cancelled", "expired"]:
                raise HTTPException(status_code=400, detail="Subscription is already cancelled")
            
            # Get LemonSqueezy API key
            api_key = os.getenv("LEMONSQUEEZY_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
            
            # Cancel subscription via LemonSqueezy API
            lemonsqueezy_sub_id = subscription.lemonsqueezy_subscription_id
            logger.info(f"Cancelling LemonSqueezy subscription ID: {lemonsqueezy_sub_id} for user: {user_id}")
            
            if not lemonsqueezy_sub_id:
                logger.error(f"No LemonSqueezy subscription ID found for user {user_id}")
                raise HTTPException(status_code=400, detail="Invalid subscription - missing LemonSqueezy subscription ID")
            
            async with httpx.AsyncClient() as client:
                cancel_url = f"https://api.lemonsqueezy.com/v1/subscriptions/{lemonsqueezy_sub_id}"
                logger.info(f"Making DELETE request to: {cancel_url}")
                
                response = await client.delete(
                    cancel_url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/vnd.api+json",
                        "Content-Type": "application/vnd.api+json"
                    }
                )
                
                logger.info(f"LemonSqueezy API response: {response.status_code}")
                
                if response.status_code == 404:
                    logger.warning(f"LemonSqueezy subscription not found: {lemonsqueezy_sub_id}. Proceeding with local cancellation.")
                    # If subscription doesn't exist in LemonSqueezy, we'll still cancel it locally
                    # This handles cases where the subscription was already deleted or never properly created
                    ends_at_datetime = subscription.current_period_end or datetime.utcnow()
                    
                    # Update local subscription status
                    mongodb.subscriptions.update_one(
                        {"_id": subscription.id},
                        {
                            "$set": {
                                "status": "cancelled",
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    
                    # Update user status and downgrade to free tier immediately
                    free_tier = self.SUBSCRIPTION_TIERS["free"]
                    mongodb.users.update_one(
                        {"_id": user_id},
                        {
                            "$set": {
                                "subscription_status": "cancelled",
                                "subscription_tier": "free",  # Downgrade to free tier immediately
                                "monthly_token_allocation": free_tier.monthly_tokens
                            }
                        }
                    )
                    
                    logger.info(f"Successfully cancelled local subscription for user {user_id} (LemonSqueezy subscription not found)")
                    
                    return {
                        "success": True,
                        "message": f"Subscription cancelled successfully. You will retain access until {ends_at_datetime.strftime('%B %d, %Y') if ends_at_datetime else 'the end of your billing period'}.",
                        "ends_at": ends_at_datetime.isoformat() if ends_at_datetime else None,
                        "ends_at_formatted": ends_at_datetime.strftime("%B %d, %Y") if ends_at_datetime else None,
                        "status": "cancelled",
                        "note": "Subscription was cancelled locally (not found in payment provider)"
                    }
                elif response.status_code not in [200, 201]:
                    logger.error(f"LemonSqueezy API error: {response.status_code} - {response.text}")
                    raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {response.text}")
                
                # Parse the response to get cancellation details
                response_data = response.json()
                cancelled_subscription = response_data.get("data", {})
                attributes = cancelled_subscription.get("attributes", {})
                
                # Extract important dates from LemonSqueezy response
                ends_at = attributes.get("ends_at")
                renews_at = attributes.get("renews_at")
                cancelled_status = attributes.get("cancelled", False)
                status = attributes.get("status", "cancelled")
                
                logger.info(f"LemonSqueezy cancellation response - Status: {status}, Cancelled: {cancelled_status}, Ends at: {ends_at}")
            
            # Parse the ends_at date
            ends_at_datetime = None
            if ends_at:
                try:
                    # LemonSqueezy returns dates in ISO format
                    ends_at_datetime = datetime.fromisoformat(ends_at.replace('Z', '+00:00'))
                except (ValueError, TypeError):
                    logger.warning(f"Could not parse ends_at date: {ends_at}")
                    ends_at_datetime = subscription.current_period_end
            else:
                ends_at_datetime = subscription.current_period_end
            
            # Update local subscription status with LemonSqueezy data
            update_data = {
                "status": "cancelled",
                "updated_at": datetime.utcnow()
            }
            
            if ends_at_datetime:
                update_data["current_period_end"] = ends_at_datetime
            
            mongodb.subscriptions.update_one(
                {"_id": subscription.id},
                {"$set": update_data}
            )
            
            # Update user status and downgrade to free tier immediately
            # User retains execution tokens until period end, but API generation limit is downgraded immediately
            free_tier = self.SUBSCRIPTION_TIERS["free"]
            mongodb.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "subscription_status": "cancelled",
                        "subscription_tier": "free",  # Downgrade to free tier immediately
                        "monthly_token_allocation": free_tier.monthly_tokens
                    }
                }
            )
            
            logger.info(f"Successfully cancelled subscription for user {user_id}")
            
            # Format the end date for user display
            ends_at_display = None
            if ends_at_datetime:
                ends_at_display = ends_at_datetime.strftime("%B %d, %Y")
            
            return {
                "success": True,
                "message": f"Subscription cancelled successfully. You will retain access until {ends_at_display or 'the end of your billing period'}.",
                "ends_at": ends_at_datetime.isoformat() if ends_at_datetime else None,
                "ends_at_formatted": ends_at_display,
                "status": "cancelled"
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to cancel subscription: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {str(e)}")
    
    async def get_customer_portal_url(self, user_id: str) -> str:
        """Get LemonSqueezy customer portal URL for payment method updates."""
        try:
            import os
            
            # Get user's subscription
            subscription = await self.get_user_subscription(user_id)
            if not subscription:
                raise HTTPException(status_code=404, detail="No active subscription found")
            
            # Get LemonSqueezy API key
            api_key = os.getenv("LEMONSQUEEZY_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
            
            # Get customer portal URL from LemonSqueezy subscription
            lemonsqueezy_sub_id = subscription.lemonsqueezy_subscription_id
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.lemonsqueezy.com/v1/subscriptions/{lemonsqueezy_sub_id}",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/vnd.api+json"
                    }
                )
                
                if response.status_code != 200:
                    logger.error(f"LemonSqueezy API error: {response.status_code} - {response.text}")
                    raise HTTPException(status_code=500, detail=f"Failed to get customer portal URL: {response.text}")
                
                data = response.json()
                subscription_data = data.get("data", {})
                attributes = subscription_data.get("attributes", {})
                urls = attributes.get("urls", {})
                
                # Get both URLs from the subscription response
                update_payment_url = urls.get("update_payment_method")
                portal_url = urls.get("customer_portal")
                
                # Prefer update_payment_method (more specific), fallback to customer_portal
                final_url = update_payment_url or portal_url
                
                if not final_url:
                    logger.error(f"No portal URLs found in response: {urls}")
                    raise HTTPException(status_code=500, detail="Customer portal URL not available")
                
                logger.info(f"Retrieved customer portal URL for user {user_id}: {final_url}")
                return final_url
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get customer portal URL: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to get customer portal URL: {str(e)}")
    
    async def get_invoices(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get user's invoices from LemonSqueezy."""
        try:
            import os
            
            # Get user's subscription
            subscription = await self.get_user_subscription(user_id)
            if not subscription:
                return []
            
            # Get LemonSqueezy API key
            api_key = os.getenv("LEMONSQUEEZY_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
            
            # Get invoices from LemonSqueezy using subscription-invoices endpoint
            lemonsqueezy_sub_id = subscription.lemonsqueezy_subscription_id
            
            async with httpx.AsyncClient() as client:
                # Use the subscription-invoices relationship endpoint
                response = await client.get(
                    f"https://api.lemonsqueezy.com/v1/subscriptions/{lemonsqueezy_sub_id}/subscription-invoices",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/vnd.api+json"
                    },
                    params={"page[size]": limit}
                )
                
                if response.status_code != 200:
                    logger.warning(f"LemonSqueezy subscription-invoices API error: {response.status_code} - {response.text}")
                    
                    # Fallback: try to get invoices by filtering all subscription invoices
                    response = await client.get(
                        "https://api.lemonsqueezy.com/v1/subscription-invoices",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Accept": "application/vnd.api+json"
                        },
                        params={
                            "filter[subscription_id]": lemonsqueezy_sub_id,
                            "page[size]": limit
                        }
                    )
                    
                    if response.status_code != 200:
                        logger.error(f"LemonSqueezy invoices API error: {response.status_code} - {response.text}")
                        return []
                
                data = response.json()
                invoices_data = data.get("data", [])
                
                # Format invoices
                invoices = []
                for invoice in invoices_data:
                    attrs = invoice.get("attributes", {})
                    
                    # Convert total from cents to dollars if needed
                    total = attrs.get("total", 0)
                    if isinstance(total, int) and total > 100:
                        # Assume it's in cents, convert to dollars
                        total_dollars = total / 100
                    else:
                        total_dollars = total
                    
                    invoices.append({
                        "id": invoice.get("id"),
                        "status": attrs.get("status", "unknown"),
                        "total": total_dollars,
                        "total_cents": attrs.get("total", 0),
                        "currency": attrs.get("currency", "USD"),
                        "created_at": attrs.get("created_at"),
                        "invoice_url": attrs.get("urls", {}).get("invoice_url"),
                        "billing_reason": attrs.get("billing_reason", "Subscription"),
                        "subscription_id": attrs.get("subscription_id")
                    })
                
                logger.info(f"Retrieved {len(invoices)} invoices for user {user_id}")
                return invoices
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get invoices: {str(e)}", exc_info=True)
            return []
    
    async def change_subscription_tier(self, user_id: str, new_tier: str) -> Dict[str, Any]:
        """Change user's subscription tier (upgrade/downgrade)."""
        try:
            import os
            
            if new_tier not in self.SUBSCRIPTION_TIERS:
                raise HTTPException(status_code=400, detail=f"Invalid subscription tier: {new_tier}")
            
            # Get current subscription
            current_subscription = await self.get_user_subscription(user_id)
            if not current_subscription:
                # No subscription - check if trying to subscribe to free tier
                if new_tier == "free":
                    # Free tier doesn't need LemonSqueezy - just set up locally
                    tier_info = self.SUBSCRIPTION_TIERS[new_tier]
                    
                    # Update user to free tier
                    mongodb.users.update_one(
                        {"_id": user_id},
                        {
                            "$set": {
                                "subscription_tier": new_tier,
                                "subscription_status": "active",
                                "monthly_token_allocation": tier_info.monthly_tokens
                            }
                        }
                    )
                    
                    # Allocate free tier tokens
                    await api_pricing_service.allocate_separated_monthly_tokens(
                        user_id=user_id,
                        generation_tokens=tier_info.monthly_generation_tokens,
                        execution_tokens=tier_info.monthly_execution_tokens,
                        source="free_tier_setup"
                    )
                    
                    return {
                        "success": True,
                        "message": "Successfully set up free tier",
                        "new_tier": new_tier,
                        "new_allocation": tier_info.monthly_tokens,
                        "requires_checkout": False
                    }
                
                # No subscription - create new paid subscription
                checkout_url = await self.create_lemonsqueezy_checkout(user_id, new_tier)
                return {
                    "success": True,
                    "message": "Please complete checkout to subscribe",
                    "checkout_url": checkout_url,
                    "requires_checkout": True
                }
            
            current_tier = current_subscription.tier
            
            # Check if it's the same tier
            if current_tier == new_tier:
                raise HTTPException(status_code=400, detail="You are already on this tier")
            
            # Check if downgrading to free
            if new_tier == "free":
                # Cancel current subscription in LemonSqueezy
                cancel_result = await self.cancel_subscription(user_id)
                
                # Update user to free tier immediately
                tier_info = self.SUBSCRIPTION_TIERS[new_tier]
                
                # Update user's tier to free
                mongodb.users.update_one(
                    {"_id": user_id},
                    {
                        "$set": {
                            "subscription_tier": "free",
                            "subscription_status": "cancelled",  # Subscription is cancelled but access continues
                            "monthly_token_allocation": tier_info.monthly_tokens
                        }
                    }
                )
                
                # Allocate free tier tokens
                await api_pricing_service.allocate_separated_monthly_tokens(
                    user_id=user_id,
                    generation_tokens=tier_info.monthly_generation_tokens,
                    execution_tokens=tier_info.monthly_execution_tokens,
                    source="downgrade_to_free"
                )
                
                # Return success message with cancellation info
                return {
                    "success": True,
                    "message": f"Subscription cancelled successfully. You will retain access until {cancel_result.get('ends_at_formatted', 'the end of your billing period')}. You have been downgraded to the Free tier.",
                    "ends_at": cancel_result.get("ends_at"),
                    "ends_at_formatted": cancel_result.get("ends_at_formatted"),
                    "new_tier": "free",
                    "new_allocation": tier_info.monthly_tokens,
                    "status": "cancelled",
                    "requires_checkout": False
                }
            
            # Get LemonSqueezy API key
            api_key = os.getenv("LEMONSQUEEZY_API_KEY")
            if not api_key:
                raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
            
            # Get new variant ID
            new_variant_id = None
            if new_tier == "starter":
                new_variant_id = os.getenv("LEMONSQUEEZY_STARTER_VARIANT_ID")
            elif new_tier == "professional":
                new_variant_id = os.getenv("LEMONSQUEEZY_PROFESSIONAL_VARIANT_ID")
            elif new_tier == "enterprise":
                new_variant_id = os.getenv("LEMONSQUEEZY_ENTERPRISE_VARIANT_ID")
            
            if not new_variant_id:
                raise HTTPException(status_code=500, detail=f"Variant ID not configured for tier: {new_tier}")
            
            # Update subscription via LemonSqueezy API
            lemonsqueezy_sub_id = current_subscription.lemonsqueezy_subscription_id
            
            logger.info(f"Changing subscription {lemonsqueezy_sub_id} from {current_tier} to {new_tier} with variant_id: {new_variant_id}")
            
            async with httpx.AsyncClient() as client:
                response = await client.patch(
                    f"https://api.lemonsqueezy.com/v1/subscriptions/{lemonsqueezy_sub_id}",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/vnd.api+json",
                        "Accept": "application/vnd.api+json"
                    },
                    json={
                        "data": {
                            "type": "subscriptions",
                            "id": str(lemonsqueezy_sub_id),
                            "attributes": {
                                "variant_id": str(new_variant_id)
                            }
                        }
                    }
                )
                
                if response.status_code not in [200, 201]:
                    logger.error(f"LemonSqueezy API error: {response.status_code} - {response.text}")
                    raise HTTPException(status_code=500, detail=f"Failed to change subscription tier: {response.text}")
            
            # Update local subscription
            new_tier_info = self.SUBSCRIPTION_TIERS[new_tier]
            
            mongodb.subscriptions.update_one(
                {"_id": current_subscription.id},
                {
                    "$set": {
                        "tier": new_tier,
                        "lemonsqueezy_variant_id": new_variant_id,
                        "monthly_token_allocation": new_tier_info.monthly_tokens,
                        "updated_at": datetime.utcnow()
                    }
                }
            )
            
            # Update user
            mongodb.users.update_one(
                {"_id": user_id},
                {
                    "$set": {
                        "subscription_tier": new_tier,
                        "monthly_token_allocation": new_tier_info.monthly_tokens
                    }
                }
            )
            
            # Allocate new token amounts
            await api_pricing_service.allocate_separated_monthly_tokens(
                user_id=user_id,
                generation_tokens=new_tier_info.monthly_generation_tokens,
                execution_tokens=new_tier_info.monthly_execution_tokens,
                source="tier_change"
            )
            
            action = "upgraded" if self.SUBSCRIPTION_TIERS[new_tier].price_cents > self.SUBSCRIPTION_TIERS[current_tier].price_cents else "downgraded"
            
            logger.info(f"Successfully {action} subscription for user {user_id} from {current_tier} to {new_tier}")
            
            return {
                "success": True,
                "message": f"Successfully {action} to {new_tier_info.display_name} plan",
                "new_tier": new_tier,
                "new_allocation": new_tier_info.monthly_tokens,
                "requires_checkout": False
            }
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to change subscription tier: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to change subscription tier: {str(e)}")

# Global instance
subscription_service = SubscriptionService()