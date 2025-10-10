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
                # Update existing subscription with actual subscription ID
                mongodb.subscriptions.update_one(
                    {"_id": existing_sub["_id"]},
                    {
                        "$set": {
                            "lemonsqueezy_subscription_id": lemonsqueezy_subscription_id,
                            "current_period_start": datetime.fromisoformat(attributes.get("current_period_start", "")),
                            "current_period_end": datetime.fromisoformat(attributes.get("current_period_end", "")),
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
                "current_period_start": datetime.fromisoformat(attributes.get("current_period_start", "")),
                "current_period_end": datetime.fromisoformat(attributes.get("current_period_end", "")),
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

# Global instance
subscription_service = SubscriptionService()
