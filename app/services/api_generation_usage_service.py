import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from ..models import APIGenerationUsage, APIGenerationLimitsResponse
from .mongodb import mongodb
from .subscription_service import subscription_service
from .usage_service import usage_service

logger = logging.getLogger(__name__)

class APIGenerationUsageService:
    def __init__(self):
        logger.info("APIGenerationUsageService initialized")
    
    async def record_api_generation(
        self,
        user_id: str,
        api_key_id: Optional[str],
        api_slug: str,
        generation_model: str,
        prompt: str,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> str:
        """Record a new API generation usage entry."""
        
        try:
            # Create usage record
            usage_id = str(uuid.uuid4())
            
            # Create usage record in MongoDB
            db_usage = {
                "_id": usage_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "api_slug": api_slug,
                "generation_model": generation_model,
                "prompt": prompt[:500],  # Store first 500 chars of prompt
                "success": success,
                "error_message": error_message,
                "created_at": datetime.utcnow()
            }
            
            mongodb.api_generation_usage.insert_one(db_usage)
            
            logger.info(f"Recorded API generation for user {user_id}: {api_slug} using {generation_model}")
            return usage_id
                
        except Exception as e:
            logger.error(f"Failed to record API generation usage: {str(e)}")
            raise Exception(f"Failed to record API generation usage: {str(e)}")
    
    async def check_generation_limits(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        tokens_to_use: int = 2000  # Estimated tokens for API generation
    ) -> APIGenerationLimitsResponse:
        """Check if user has exceeded their API generation limits and daily token limits."""
        
        try:
            # Get current time boundaries
            now = datetime.utcnow()
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Get user's subscription tier to determine limits
            # FIXED: Always get the latest subscription from subscriptions collection
            # This is the source of truth and prevents sync issues with user document
            subscription = await subscription_service.get_user_subscription(user_id)
            subscription_tier = subscription.tier if subscription else "free"
            
            # Fallback: if no subscription found, check user document
            if not subscription:
                user = mongodb.users.find_one({"_id": user_id})
                subscription_tier = user.get("subscription_tier", "free") if user else "free"
            
            tier_info = subscription_service.SUBSCRIPTION_TIERS.get(subscription_tier)
            monthly_generation_limit = tier_info.monthly_api_generations if tier_info else 1
            
            # Query monthly API generation usage
            monthly_match = {
                "user_id": user_id,
                "created_at": {"$gte": month_start},
                "success": True
            }
            
            if api_key_id:
                monthly_match["api_key_id"] = api_key_id
            
            monthly_pipeline = [
                {"$match": monthly_match},
                {"$group": {
                    "_id": None,
                    "total_generations": {"$sum": 1}
                }}
            ]
            
            monthly_result = list(mongodb.api_generation_usage.aggregate(monthly_pipeline))
            monthly_generations_used = monthly_result[0]["total_generations"] if monthly_result else 0
            
            logger.info(f"API Generation Limit Check - User: {user_id}, Used: {monthly_generations_used}, Limit: {monthly_generation_limit}, Tier: {subscription_tier}")
            
            # Calculate remaining usage
            monthly_generations_remaining = max(0, monthly_generation_limit - monthly_generations_used)
            
            # Check if user has already reached or exceeded API generation limits
            # Use >= instead of > to prevent any generation once limit is reached
            is_over_api_limit = monthly_generations_used >= monthly_generation_limit
            
            if is_over_api_limit:
                logger.warning(f"⛔ API generation limit exceeded - User: {user_id}, Used: {monthly_generations_used}/{monthly_generation_limit}")
            
            # Also check daily token limits using the existing usage service
            token_limits = await usage_service.check_usage_limits(
                user_id=user_id,
                api_key_id=api_key_id,
                tokens_to_use=tokens_to_use
            )
            
            # Combine both checks - user is over limit if either limit is exceeded
            is_over_limit = is_over_api_limit or token_limits.is_over_limit
            
            # Next reset time (first day of next month)
            if now.month == 12:
                next_month = now.replace(year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                next_month = now.replace(month=now.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Determine which limit was exceeded for better error messages
            limit_exceeded_reason = None
            if is_over_api_limit and token_limits.is_over_limit:
                limit_exceeded_reason = f"Both API generation limit ({monthly_generations_used}/{monthly_generation_limit} generations) and daily token limit exceeded."
            elif is_over_api_limit:
                limit_exceeded_reason = f"Monthly API generation limit exceeded. You have used {monthly_generations_used}/{monthly_generation_limit} generations this month."
            elif token_limits.is_over_limit:
                limit_exceeded_reason = token_limits.limit_exceeded_reason
            
            return APIGenerationLimitsResponse(
                is_over_limit=is_over_limit,
                monthly_generation_limit=monthly_generation_limit,
                monthly_generations_used=monthly_generations_used,
                monthly_generations_remaining=monthly_generations_remaining,
                limit_reset_time=next_month,
                limit_exceeded_reason=limit_exceeded_reason,
                subscription_tier=subscription_tier,
                # Include token limit information
                daily_token_limit=token_limits.daily_token_limit,
                daily_tokens_used=token_limits.daily_tokens_used,
                daily_tokens_remaining=token_limits.daily_tokens_remaining,
                token_limit_exceeded=token_limits.is_over_limit
            )
                
        except Exception as e:
            logger.error(f"Failed to check API generation limits: {str(e)}")
            raise Exception(f"Failed to check API generation limits: {str(e)}")
    
    async def get_generation_stats(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        days: int = 30
    ) -> Dict[str, Any]:
        """Get API generation statistics for a user."""
        
        try:
            # Get time boundaries
            now = datetime.utcnow()
            start_date = now - timedelta(days=days)
            
            # Base match query
            match_query = {
                "user_id": user_id,
                "created_at": {"$gte": start_date}
            }
            
            if api_key_id:
                match_query["api_key_id"] = api_key_id
            
            # Aggregate statistics
            pipeline = [
                {"$match": match_query},
                {"$group": {
                    "_id": None,
                    "total_generations": {"$sum": 1},
                    "successful_generations": {"$sum": {"$cond": ["$success", 1, 0]}},
                    "failed_generations": {"$sum": {"$cond": ["$success", 0, 1]}},
                    "unique_models": {"$addToSet": "$generation_model"}
                }}
            ]
            
            result = list(mongodb.api_generation_usage.aggregate(pipeline))
            
            if result:
                stats = result[0]
                return {
                    "total_generations": stats["total_generations"],
                    "successful_generations": stats["successful_generations"],
                    "failed_generations": stats["failed_generations"],
                    "success_rate": stats["successful_generations"] / stats["total_generations"] if stats["total_generations"] > 0 else 0,
                    "unique_models_used": stats["unique_models"],
                    "period_days": days
                }
            else:
                return {
                    "total_generations": 0,
                    "successful_generations": 0,
                    "failed_generations": 0,
                    "success_rate": 0,
                    "unique_models_used": [],
                    "period_days": days
                }
                
        except Exception as e:
            logger.error(f"Failed to get API generation stats: {str(e)}")
            raise Exception(f"Failed to get API generation stats: {str(e)}")

# Create singleton instance
api_generation_usage_service = APIGenerationUsageService()
