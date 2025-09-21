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
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException
import httpx

from ..models import (
    Subscription, SubscriptionTier, CreateSubscriptionRequest, CreateSubscriptionResponse,
    SubscriptionStatusResponse, UpdateSubscriptionRequest, SubscriptionTiersResponse,
    SubscriptionEvent
)
from ..models_auth import User
from .database import SubscriptionDB, SubscriptionEventDB, UserDB, AsyncSessionLocal
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
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SubscriptionDB).where(
                        and_(
                            SubscriptionDB.user_id == user_id,
                            SubscriptionDB.status.in_(["active", "past_due", "paused"])
                        )
                    ).order_by(SubscriptionDB.created_at.desc())
                )
                
                db_subscription = result.scalar_one_or_none()
                
                if not db_subscription:
                    return None
                
                return Subscription(
                    id=db_subscription.id,
                    user_id=db_subscription.user_id,
                    lemonsqueezy_subscription_id=db_subscription.lemonsqueezy_subscription_id,
                    lemonsqueezy_customer_id=db_subscription.lemonsqueezy_customer_id,
                    lemonsqueezy_product_id=db_subscription.lemonsqueezy_product_id,
                    lemonsqueezy_variant_id=db_subscription.lemonsqueezy_variant_id,
                    tier=db_subscription.tier,
                    status=db_subscription.status,
                    current_period_start=db_subscription.current_period_start,
                    current_period_end=db_subscription.current_period_end,
                    trial_start=db_subscription.trial_start,
                    trial_end=db_subscription.trial_end,
                    monthly_token_allocation=db_subscription.monthly_token_allocation,
                    created_at=db_subscription.created_at,
                    updated_at=db_subscription.updated_at
                )
                
        except Exception as e:
            logger.error(f"Failed to get user subscription: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get user subscription: {str(e)}")
    
    async def create_lemonsqueezy_checkout(self, user_id: str, tier: str) -> str:
        """Create a LemonSqueezy checkout URL for a subscription tier."""
        # This is a placeholder - you'll need to implement actual LemonSqueezy API calls
        # For now, return a mock checkout URL
        
        if tier not in self.SUBSCRIPTION_TIERS:
            raise HTTPException(status_code=400, detail=f"Invalid subscription tier: {tier}")
        
        tier_info = self.SUBSCRIPTION_TIERS[tier]
        
        # TODO: Implement actual LemonSqueezy API integration
        # This would involve:
        # 1. Creating a customer in LemonSqueezy
        # 2. Creating a checkout session
        # 3. Returning the checkout URL
        
        # For now, return a placeholder URL
        checkout_url = f"https://your-store.lemonsqueezy.com/checkout/custom/{tier}?user_id={user_id}"
        
        logger.info(f"Created checkout URL for user {user_id}, tier {tier}")
        return checkout_url
    
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
            async with AsyncSessionLocal() as session:
                existing_event = await session.execute(
                    select(SubscriptionEventDB).where(
                        SubscriptionEventDB.lemonsqueezy_event_id == event_id
                    )
                )
                
                if existing_event.scalar_one_or_none():
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
        
        async with AsyncSessionLocal() as session:
            db_subscription = SubscriptionDB(
                id=subscription_id,
                user_id=user_id,
                lemonsqueezy_subscription_id=lemonsqueezy_subscription_id,
                lemonsqueezy_customer_id=lemonsqueezy_customer_id,
                lemonsqueezy_product_id=product_id,
                lemonsqueezy_variant_id=variant_id,
                tier=tier,
                status="active",
                current_period_start=datetime.fromisoformat(attributes.get("current_period_start", "")),
                current_period_end=datetime.fromisoformat(attributes.get("current_period_end", "")),
                monthly_token_allocation=tier_info.monthly_tokens,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            )
            
            session.add(db_subscription)
            
            # Update user's subscription info
            user_result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if user:
                user.subscription_tier = tier
                user.subscription_status = "active"
                user.monthly_token_allocation = tier_info.monthly_tokens
                user.lemonsqueezy_customer_id = lemonsqueezy_customer_id
                user.lemonsqueezy_subscription_id = lemonsqueezy_subscription_id
            
            await session.commit()
        
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
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(UserDB.id).where(UserDB.lemonsqueezy_customer_id == customer_id)
                )
                user_id = result.scalar_one_or_none()
                return user_id
        except Exception as e:
            logger.error(f"Failed to get user by customer ID: {str(e)}")
            return None
    
    async def _record_webhook_event(self, payload: Dict[str, Any], processed: bool = False):
        """Record webhook event in database."""
        try:
            event_id = str(uuid.uuid4())
            meta = payload.get("meta", {})
            
            async with AsyncSessionLocal() as session:
                db_event = SubscriptionEventDB(
                    id=event_id,
                    subscription_id="",  # Will be filled if available
                    user_id="",  # Will be filled if available
                    event_type=meta.get("event_name", ""),
                    lemonsqueezy_event_id=meta.get("event_id", ""),
                    event_data=json.dumps(payload),
                    processed=processed,
                    created_at=datetime.utcnow()
                )
                
                session.add(db_event)
                await session.commit()
                
        except Exception as e:
            logger.error(f"Failed to record webhook event: {str(e)}")

# Global instance
subscription_service = SubscriptionService()
