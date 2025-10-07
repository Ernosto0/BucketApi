import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
# MongoDB operations handled through mongodb service
from ..models import (
    APIMetadata, InternalToken, InternalTokenBalance, APIExecutionCost,
    APIExecutionTokenUsage, EstimateAPIUsageCostRequest, EstimateAPIUsageCostResponse,
    CreateInternalTokenRequest, InternalTokenUsageStatsResponse, SeparatedTokenBalance
)
from .mongodb import mongodb
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class APIPricingService:
    def __init__(self):
        # Internal token pricing - how many internal tokens equal 1 cent
        self.TOKENS_PER_CENT = 10  # 10 internal tokens = 1 cent
        
        # Monthly token allocations by plan (free tier)
        self.DEFAULT_MONTHLY_TOKEN_ALLOCATION = 10000  # 10k internal tokens = $10 worth
        
        # AI model access by subscription tier
        self.TIER_AI_MODELS = {
            'free': ['gpt-3.5-turbo', 'gpt-4o-mini', 'claude-3-haiku'],
            'starter': ['gpt-3.5-turbo', 'gpt-4o-mini', 'gpt-4', 'claude-3-haiku', 'claude-3-sonnet'],
            'professional': ['gpt-3.5-turbo', 'gpt-4o-mini', 'gpt-4', 'gpt-4-turbo', 'claude-3-haiku', 'claude-3-sonnet', 'claude-3-opus'],
            'enterprise': ['gpt-3.5-turbo', 'gpt-4o-mini', 'gpt-4', 'gpt-4-turbo', 'claude-3-haiku', 'claude-3-sonnet', 'claude-3-opus', 'claude-4']
        }
        
        # Base pricing multipliers by complexity
        self.COMPLEXITY_MULTIPLIERS = {
            'simple': 1.0,      # Basic APIs (text processing, simple calculations)
            'medium': 1.5,      # APIs with moderate logic (data transformation, validation)
            'complex': 2.0      # Advanced APIs (ML inference, complex business logic)
        }
        
        # AI model base costs (per 1k tokens) in cents
        self.AI_MODEL_BASE_COSTS = {
            'gpt-4o-mini': 0.15,      # $0.0015 per 1k tokens
            'gpt-4': 3.0,               # $0.03 per 1k tokens
            'gpt-4-turbo': 1.0,         # $0.01 per 1k tokens
            'gpt-3.5-turbo': 0.3,       # $0.003 per 1k tokens
            # GPT-5 models (based on your pricing table)
            'gpt-5': 125.0,             # $1.25 per 1k tokens
            'gpt-5-mini': 25.0,         # $0.25 per 1k tokens  
            'gpt-5-nano': 5.0,          # $0.05 per 1k tokens
            'gpt-5-chat-latest': 125.0, # $1.25 per 1k tokens
            'claude-3-haiku': 0.25,     # $0.0025 per 1k tokens
            'claude-3-sonnet': 3.0,     # $0.03 per 1k tokens (fixed from 30.0)
            'claude-3-opus': 15.0,      # $0.15 per 1k tokens (fixed from 150.0)
            'claude-4': 30.0,           # $0.30 per 1k tokens
            'none': 0.0,                # No AI service used - free processing
        }
        
        logger.info("APIPricingService initialized")
    
    async def check_ai_model_access(self, user_id: str, ai_model: str) -> bool:
        """Check if user can access a specific AI model based on their subscription tier."""
        try:
            user = mongodb.users.find_one({"_id": user_id})
            
            if not user:
                return False
            
            tier = user.get("subscription_tier", "free")
            allowed_models = self.TIER_AI_MODELS.get(tier, self.TIER_AI_MODELS['free'])
            
            return ai_model in allowed_models
                
        except Exception as e:
            logger.error(f"Failed to check AI model access: {str(e)}")
            # Default to allowing access if we can't check
            return True
    
    async def get_available_ai_models(self, user_id: str) -> List[str]:
        """Get list of AI models available to a user based on their subscription tier."""
        try:
            user = mongodb.users.find_one({"_id": user_id})
            
            if not user:
                return self.TIER_AI_MODELS['free']
            
            tier = user.get("subscription_tier", "free")
            return self.TIER_AI_MODELS.get(tier, self.TIER_AI_MODELS['free'])
                
        except Exception as e:
            logger.error(f"Failed to get available AI models: {str(e)}")
            return self.TIER_AI_MODELS['free']
    
    async def save_api_metadata(
        self,
        api_slug: str,
        user_id: str,
        ai_model_used: str,
        estimated_tokens_per_call: int,
        base_complexity: str = 'medium'
    ) -> APIMetadata:
        """Save metadata about a generated API including its cost structure."""
        
        try:
            # Calculate estimated cost per call
            base_cost_per_1k_tokens = self.AI_MODEL_BASE_COSTS.get(ai_model_used, 1.0)
            complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(base_complexity, 1.5)
            
            estimated_cost_cents = int(
                (estimated_tokens_per_call / 1000) * base_cost_per_1k_tokens * complexity_multiplier
            )
            
            # Ensure minimum cost
            estimated_cost_cents = max(estimated_cost_cents, 1)  # Minimum 1 cent per call
            
            metadata_id = str(uuid.uuid4())
            
            # Check if metadata already exists
            existing = mongodb.api_metadata.find_one({
                "api_slug": api_slug,
                "user_id": user_id
            })
            
            if existing:
                # Update existing
                mongodb.api_metadata.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "ai_model_used": ai_model_used,
                        "estimated_tokens_per_call": estimated_tokens_per_call,
                        "estimated_cost_per_call_cents": estimated_cost_cents,
                        "base_complexity": base_complexity,
                        "last_updated": datetime.utcnow()
                    }}
                )
                db_metadata = mongodb.api_metadata.find_one({"_id": existing["_id"]})
            else:
                # Create new
                db_metadata = {
                    "_id": metadata_id,
                    "api_slug": api_slug,
                    "user_id": user_id,
                    "ai_model_used": ai_model_used,
                    "estimated_tokens_per_call": estimated_tokens_per_call,
                    "estimated_cost_per_call_cents": estimated_cost_cents,
                    "base_complexity": base_complexity,
                    "created_at": datetime.utcnow(),
                    "last_updated": datetime.utcnow()
                }
                mongodb.api_metadata.insert_one(db_metadata)
                
            metadata = APIMetadata(
                api_slug=db_metadata["api_slug"],
                user_id=db_metadata["user_id"],
                ai_model_used=db_metadata["ai_model_used"],
                estimated_tokens_per_call=db_metadata["estimated_tokens_per_call"],
                estimated_cost_per_call_cents=db_metadata["estimated_cost_per_call_cents"],
                base_complexity=db_metadata["base_complexity"],
                created_at=db_metadata["created_at"],
                last_updated=db_metadata["last_updated"]
            )
                
            logger.info(f"Saved API metadata for {api_slug}: {estimated_cost_cents} cents per call")
            return metadata
                
        except Exception as e:
            logger.error(f"Failed to save API metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to save API metadata: {str(e)}")
    
    async def get_api_execution_cost(
        self,
        api_slug: str,
        user_id: str
    ) -> APIExecutionCost:
        """Get the execution cost for a specific API."""
        
        try:
            metadata = mongodb.api_metadata.find_one({
                "api_slug": api_slug,
                "user_id": user_id
            })
            
            if not metadata:
                raise HTTPException(
                    status_code=404,
                    detail=f"API metadata not found for {api_slug}"
                )
            
            # Convert cost to internal tokens
            internal_tokens_per_call = metadata["estimated_cost_per_call_cents"] * self.TOKENS_PER_CENT
            complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(metadata["base_complexity"], 1.5)
            
            return APIExecutionCost(
                api_slug=metadata["api_slug"],
                user_id=metadata["user_id"],
                cost_per_call_cents=metadata["estimated_cost_per_call_cents"],
                internal_tokens_per_call=internal_tokens_per_call,
                ai_model_used=metadata["ai_model_used"],
                complexity_multiplier=complexity_multiplier,
                base_cost_cents=int(metadata["estimated_cost_per_call_cents"] / complexity_multiplier),
                estimated_tokens_used=metadata["estimated_tokens_per_call"],
                last_calculated=metadata["last_updated"]
            )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get API execution cost: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get API execution cost: {str(e)}")
    
    async def allocate_separated_monthly_tokens(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        generation_tokens: Optional[int] = None,
        execution_tokens: Optional[int] = None,
        source: str = "monthly_allocation"
    ) -> List[InternalToken]:
        """Allocate separated monthly tokens (generation + execution) to a user based on their subscription tier."""
        
        if generation_tokens is None or execution_tokens is None:
            # Get user's subscription tier to determine allocation
            from .subscription_service import subscription_service
            
            user = mongodb.users.find_one({"_id": user_id})
            
            if user and user.get("subscription_tier"):
                tier_info = subscription_service.SUBSCRIPTION_TIERS.get(user["subscription_tier"])
                if tier_info:
                    generation_tokens = tier_info.monthly_generation_tokens
                    execution_tokens = tier_info.monthly_execution_tokens
                else:
                    generation_tokens = 3000  # Free tier default
                    execution_tokens = 7000
            else:
                generation_tokens = 3000  # Free tier default
                execution_tokens = 7000
        
        allocated_tokens = []
        
        # Allocate generation tokens
        generation_token = await self._create_token_allocation(
            user_id=user_id,
            api_key_id=api_key_id,
            token_type="api_generation",
            amount=generation_tokens,
            source=source
        )
        allocated_tokens.append(generation_token)
        
        # Allocate execution tokens
        execution_token = await self._create_token_allocation(
            user_id=user_id,
            api_key_id=api_key_id,
            token_type="api_execution", 
            amount=execution_tokens,
            source=source
        )
        allocated_tokens.append(execution_token)
        
        logger.info(f"Allocated {generation_tokens} generation + {execution_tokens} execution tokens to user {user_id}")
        return allocated_tokens

    async def allocate_monthly_tokens(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        amount: Optional[int] = None,
        source: str = "monthly_allocation"
    ) -> InternalToken:
        """Legacy method - allocate monthly tokens to a user based on their subscription tier."""
        
        if amount is None:
            # Get user's subscription tier to determine allocation
            user = mongodb.users.find_one({"_id": user_id})
            
            if user and user.get("monthly_token_allocation"):
                amount = user["monthly_token_allocation"]
            else:
                amount = self.DEFAULT_MONTHLY_TOKEN_ALLOCATION
        
        try:
            token_id = str(uuid.uuid4())
            
            # Set expiration to end of next month
            now = datetime.utcnow()
            next_month = now.replace(day=1) + timedelta(days=32)
            expires_at = next_month.replace(day=1) - timedelta(days=1)
            
            db_token = {
                "_id": token_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "token_type": 'api_execution',
                "amount": amount,
                "source": source,
                "expires_at": expires_at,
                "created_at": datetime.utcnow(),
                "is_used": False
            }
            
            mongodb.internal_tokens.insert_one(db_token)
            
            token = InternalToken(
                id=db_token["_id"],
                user_id=db_token["user_id"],
                api_key_id=db_token["api_key_id"],
                token_type=db_token["token_type"],
                amount=db_token["amount"],
                source=db_token["source"],
                expires_at=db_token["expires_at"],
                created_at=db_token["created_at"],
                used_at=None,
                is_used=db_token["is_used"]
            )
            
            logger.info(f"Allocated {amount} monthly tokens to user {user_id}")
            return token
                
        except Exception as e:
            logger.error(f"Failed to allocate monthly tokens: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to allocate monthly tokens: {str(e)}")
    
    async def get_token_balance(
        self,
        user_id: str,
        api_key_id: Optional[str] = None
    ) -> InternalTokenBalance:
        """Get the current internal token balance for a user."""
        
        try:
            now = datetime.utcnow()
            seven_days_from_now = now + timedelta(days=7)
            
            # Get all unused tokens
            query = {
                "user_id": user_id,
                "is_used": False,
                "$or": [
                    {"expires_at": None},
                    {"expires_at": {"$gt": now}}
                ]
            }
            
            if api_key_id:
                query["api_key_id"] = api_key_id
            
            unused_tokens = list(mongodb.internal_tokens.find(query))
            
            total_tokens = sum(token["amount"] for token in unused_tokens)
            
            # Get tokens expiring soon
            expires_soon_tokens = sum(
                token["amount"] for token in unused_tokens 
                if token.get("expires_at") and token["expires_at"] <= seven_days_from_now
            )
            
            # Get used tokens this month
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            used_query = {
                "user_id": user_id,
                "created_at": {"$gte": month_start}
            }
            
            if api_key_id:
                used_query["api_key_id"] = api_key_id
            
            used_tokens_result = mongodb.api_execution_token_usage.aggregate([
                {"$match": used_query},
                {"$group": {"_id": None, "total": {"$sum": "$internal_tokens_used"}}}
            ])
            
            used_tokens = 0
            for result in used_tokens_result:
                used_tokens = result.get("total", 0)
                break
                
            return InternalTokenBalance(
                user_id=user_id,
                api_key_id=api_key_id,
                total_tokens=total_tokens,
                used_tokens=used_tokens,
                remaining_tokens=total_tokens,
                monthly_allocation=self.DEFAULT_MONTHLY_TOKEN_ALLOCATION,
                expires_soon_tokens=expires_soon_tokens,
                last_updated=now
            )
                
        except Exception as e:
            logger.error(f"Failed to get token balance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get token balance: {str(e)}")
    
    async def deduct_tokens_for_execution(
        self,
        user_id: str,
        api_key_id: Optional[str],
        api_slug: str,
        internal_tokens_needed: int,
        cost_cents: int,
        execution_successful: bool = True
    ) -> APIExecutionTokenUsage:
        """Deduct internal tokens for API execution."""
        
        try:
            usage_id = str(uuid.uuid4())
            
            # Only deduct tokens if execution was successful
            if execution_successful and internal_tokens_needed > 0:
                # Get available tokens (oldest first to use expiring tokens first)
                now = datetime.utcnow()
                
                query = {
                    "user_id": user_id,
                    "is_used": False,
                    "$or": [
                        {"expires_at": None},
                        {"expires_at": {"$gt": now}}
                    ]
                }
                
                if api_key_id:
                    query["api_key_id"] = api_key_id
                
                available_tokens = list(mongodb.internal_tokens.find(query).sort("expires_at", 1))
                
                total_available = sum(token["amount"] for token in available_tokens)
                
                if total_available < internal_tokens_needed:
                    raise HTTPException(
                        status_code=402,  # Payment Required
                        detail=f"Insufficient internal tokens. Need {internal_tokens_needed}, have {total_available}"
                    )
                
                # Deduct tokens (mark as used)
                tokens_remaining = internal_tokens_needed
                for token in available_tokens:
                    if tokens_remaining <= 0:
                        break
                    
                    if token["amount"] <= tokens_remaining:
                        # Use entire token
                        mongodb.internal_tokens.update_one(
                            {"_id": token["_id"]},
                            {"$set": {"is_used": True, "used_at": datetime.utcnow()}}
                        )
                        tokens_remaining -= token["amount"]
                    else:
                        # Split token (create new token with remaining amount)
                        new_token_id = str(uuid.uuid4())
                        remaining_amount = token["amount"] - tokens_remaining
                        
                        # Mark original as used
                        mongodb.internal_tokens.update_one(
                            {"_id": token["_id"]},
                            {"$set": {"is_used": True, "used_at": datetime.utcnow(), "amount": tokens_remaining}}
                        )
                        
                        # Create new token with remaining amount
                        new_token = {
                            "_id": new_token_id,
                            "user_id": token["user_id"],
                            "api_key_id": token["api_key_id"],
                            "token_type": token["token_type"],
                            "amount": remaining_amount,
                            "source": token["source"],
                            "expires_at": token["expires_at"],
                            "created_at": datetime.utcnow(),
                            "is_used": False
                        }
                        mongodb.internal_tokens.insert_one(new_token)
                        
                        tokens_remaining = 0
            
            # Record usage
            db_usage = {
                "_id": usage_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "api_slug": api_slug,
                "internal_tokens_used": internal_tokens_needed if execution_successful else 0,
                "cost_cents": cost_cents,
                "execution_successful": execution_successful,
                "created_at": datetime.utcnow()
            }
            
            mongodb.api_execution_token_usage.insert_one(db_usage)
            
            usage = APIExecutionTokenUsage(
                id=db_usage["_id"],
                user_id=db_usage["user_id"],
                api_key_id=db_usage["api_key_id"],
                api_slug=db_usage["api_slug"],
                internal_tokens_used=db_usage["internal_tokens_used"],
                cost_cents=db_usage["cost_cents"],
                execution_successful=db_usage["execution_successful"],
                created_at=db_usage["created_at"]
            )
            
            logger.info(f"Deducted {internal_tokens_needed} tokens for {api_slug} execution")
            return usage
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to deduct tokens: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to deduct tokens: {str(e)}")
    
    async def estimate_api_usage_cost(
        self,
        request: EstimateAPIUsageCostRequest
    ) -> EstimateAPIUsageCostResponse:
        """Estimate the cost and tokens needed for API usage."""
        
        try:
            # This would be called during API testing to establish pricing
            # For now, use default estimates based on prompt complexity
            prompt_length = len(request.sample_input) if request.sample_input else 100
            
            # Estimate complexity based on input length and expected usage
            if prompt_length < 100:
                complexity = 'simple'
                estimated_tokens = 500
                ai_model = 'gpt-4o-mini'
            elif prompt_length < 500:
                complexity = 'medium'
                estimated_tokens = 1500
                ai_model = 'gpt-4'
            else:
                complexity = 'complex'
                estimated_tokens = 3000
                ai_model = 'gpt-4'
            
            # Calculate costs
            base_cost_per_1k = self.AI_MODEL_BASE_COSTS.get(ai_model, 1.0)
            complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(complexity, 1.5)
            
            cost_per_call_cents = max(1, int(
                (estimated_tokens / 1000) * base_cost_per_1k * complexity_multiplier
            ))
            
            internal_tokens_per_call = cost_per_call_cents * self.TOKENS_PER_CENT
            
            estimated_monthly_cost = cost_per_call_cents * request.expected_calls_per_month
            estimated_monthly_tokens = internal_tokens_per_call * request.expected_calls_per_month
            
            breakdown = {
                'base_cost_per_1k_tokens': base_cost_per_1k,
                'estimated_ai_tokens': estimated_tokens,
                'complexity_multiplier': complexity_multiplier,
                'tokens_per_cent_ratio': self.TOKENS_PER_CENT,
                'expected_calls_per_month': request.expected_calls_per_month
            }
            
            return EstimateAPIUsageCostResponse(
                api_slug=request.api_slug,
                cost_per_call_cents=cost_per_call_cents,
                internal_tokens_per_call=internal_tokens_per_call,
                estimated_monthly_cost_cents=estimated_monthly_cost,
                estimated_monthly_tokens=estimated_monthly_tokens,
                ai_model_used=ai_model,
                complexity_rating=complexity,
                breakdown=breakdown
            )
            
        except Exception as e:
            logger.error(f"Failed to estimate API usage cost: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to estimate API usage cost: {str(e)}")
    
    async def _create_token_allocation(
        self,
        user_id: str,
        api_key_id: Optional[str],
        token_type: str,
        amount: int,
        source: str
    ) -> InternalToken:
        """Helper method to create a token allocation."""
        try:
            token_id = str(uuid.uuid4())
            
            # Set expiration to end of next month
            now = datetime.utcnow()
            next_month = now.replace(day=1) + timedelta(days=32)
            expires_at = next_month.replace(day=1) - timedelta(days=1)
            
            db_token = {
                "_id": token_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "token_type": token_type,
                "amount": amount,
                "source": source,
                "expires_at": expires_at,
                "created_at": datetime.utcnow(),
                "is_used": False
            }
            
            mongodb.internal_tokens.insert_one(db_token)
            
            return InternalToken(
                id=db_token["_id"],
                user_id=db_token["user_id"],
                api_key_id=db_token["api_key_id"],
                token_type=db_token["token_type"],
                amount=db_token["amount"],
                source=db_token["source"],
                expires_at=db_token["expires_at"],
                created_at=db_token["created_at"],
                used_at=None,
                is_used=db_token["is_used"]
            )
                
        except Exception as e:
            logger.error(f"Failed to create token allocation: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to create token allocation: {str(e)}")
    
    async def get_separated_token_balance(
        self,
        user_id: str,
        api_key_id: Optional[str] = None
    ) -> SeparatedTokenBalance:
        """Get separated token balance (generation vs execution) for a user."""
        try:
            now = datetime.utcnow()
            
            # Get generation tokens
            gen_query = {
                "user_id": user_id,
                "token_type": "api_generation",
                "is_used": False,
                "$or": [
                    {"expires_at": None},
                    {"expires_at": {"$gt": now}}
                ]
            }
            
            if api_key_id:
                gen_query["api_key_id"] = api_key_id
            
            gen_tokens = list(mongodb.internal_tokens.find(gen_query))
            
            # Get execution tokens
            exec_query = {
                "user_id": user_id,
                "token_type": "api_execution",
                "is_used": False,
                "$or": [
                    {"expires_at": None},
                    {"expires_at": {"$gt": now}}
                ]
            }
            
            if api_key_id:
                exec_query["api_key_id"] = api_key_id
            
            exec_tokens = list(mongodb.internal_tokens.find(exec_query))
            
            # Calculate totals
            generation_total = sum(token["amount"] for token in gen_tokens)
            execution_total = sum(token["amount"] for token in exec_tokens)
            
            # Get used tokens this month
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            # Generation tokens used
            used_query = {
                "user_id": user_id,
                "created_at": {"$gte": month_start}
            }
            
            # For now, we'll use the existing usage tracking
            # TODO: Add token_type field to APIExecutionTokenUsageDB
            total_used_result = mongodb.api_execution_token_usage.aggregate([
                {"$match": used_query},
                {"$group": {"_id": None, "total": {"$sum": "$internal_tokens_used"}}}
            ])
            
            total_used = 0
            for result in total_used_result:
                total_used = result.get("total", 0)
                break
            
            # For now, split usage 30/70 between generation and execution
            gen_used = int(total_used * 0.3)
            exec_used = int(total_used * 0.7)
            
            # Get monthly allocations from subscription tier
            from .subscription_service import subscription_service
            user = mongodb.users.find_one({"_id": user_id})
            
            gen_allocation = 3000  # Default free tier
            exec_allocation = 7000
            
            if user and user.get("subscription_tier"):
                tier_info = subscription_service.SUBSCRIPTION_TIERS.get(user["subscription_tier"])
                if tier_info:
                    gen_allocation = tier_info.monthly_generation_tokens
                    exec_allocation = tier_info.monthly_execution_tokens
            
            return SeparatedTokenBalance(
                user_id=user_id,
                api_key_id=api_key_id,
                generation_tokens_total=generation_total,
                generation_tokens_used=gen_used,
                generation_tokens_remaining=generation_total,
                generation_monthly_allocation=gen_allocation,
                execution_tokens_total=execution_total,
                execution_tokens_used=exec_used,
                execution_tokens_remaining=execution_total,
                execution_monthly_allocation=exec_allocation,
                total_tokens=generation_total + execution_total,
                total_used=gen_used + exec_used,
                total_remaining=generation_total + execution_total,
                last_updated=now
            )
                
        except Exception as e:
            logger.error(f"Failed to get separated token balance: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get separated token balance: {str(e)}")

# Global instance
api_pricing_service = APIPricingService() 