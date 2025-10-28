import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
# MongoDB operations handled through mongodb service
from ..models import (
    APIMetadata, InternalToken, InternalTokenBalance, APIExecutionCost,
    APIExecutionTokenUsage, EstimateAPIUsageCostResponse,
    CreateInternalTokenRequest, InternalTokenUsageStatsResponse, SeparatedTokenBalance
)
from .mongodb import mongodb
from .api_code_analyzer import api_code_analyzer
from .api_usage_aggregator import api_usage_aggregator
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class APIPricingService:
    def __init__(self):
        # Internal token pricing - simplified system
        self.TOKENS_PER_DOLLAR = 10000  # 10,000 internal tokens = $1
        self.TOKENS_PER_CENT = 100  # 100 internal tokens = 1 cent (derived from above)
        
        # Monthly token allocations by plan (free tier)
        self.DEFAULT_MONTHLY_TOKEN_ALLOCATION = 100000  # 100k internal tokens = $10 worth
        
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
        
        # AI model base costs (per 1M tokens) in cents - Updated with real OpenAI pricing
        # Format: {'input': cents_per_1M_tokens, 'output': cents_per_1M_tokens}
        self.AI_MODEL_BASE_COSTS = {
            # GPT-5 models (corrected pricing - much lower costs)
            'gpt-5': {'input': 0.15, 'output': 0.60},              # $0.0015/$0.006 per 1M tokens
            'gpt-5-mini': {'input': 0.015, 'output': 0.06},        # $0.00015/$0.0006 per 1M tokens  
            'gpt-5-nano': {'input': 0.005, 'output': 0.02},        # $0.00005/$0.0002 per 1M tokens
            'gpt-5-chat-latest': {'input': 0.15, 'output': 0.60},  # $0.0015/$0.006 per 1M tokens
            'gpt-5-codex': {'input': 0.15, 'output': 0.60},        # $0.0015/$0.006 per 1M tokens
            'gpt-5-pro': {'input': 1.5, 'output': 6.0},            # $0.015/$0.06 per 1M tokens
            
            # GPT-4.1 models (real pricing)
            'gpt-4.1': {'input': 200, 'output': 800},             # $2.00/$8.00 per 1M tokens
            'gpt-4.1-mini': {'input': 40, 'output': 160},         # $0.40/$1.60 per 1M tokens
            'gpt-4.1-nano': {'input': 10, 'output': 40},          # $0.10/$0.40 per 1M tokens
            
            # GPT-4o models (corrected pricing)
            'gpt-4o': {'input': 0.25, 'output': 1.0},             # $0.0025/$0.01 per 1M tokens
            'gpt-4o-2024-05-13': {'input': 0.5, 'output': 1.5},   # $0.005/$0.015 per 1M tokens
            'gpt-4o-mini': {'input': 0.015, 'output': 0.06},      # $0.00015/$0.0006 per 1M tokens
            
            # Legacy models (corrected pricing)
            'gpt-4': {'input': 0.3, 'output': 0.6},               # $0.003/$0.006 per 1M tokens
            'gpt-4-turbo': {'input': 0.1, 'output': 0.3},         # $0.001/$0.003 per 1M tokens
            'gpt-3.5-turbo': {'input': 0.05, 'output': 0.15},     # $0.0005/$0.0015 per 1M tokens
            
            # Claude models (corrected pricing)
            'claude-3-haiku': {'input': 0.025, 'output': 0.125},       # $0.00025/$0.00125 per 1M tokens
            'claude-3-sonnet': {'input': 0.3, 'output': 1.5},          # $0.003/$0.015 per 1M tokens
            'claude-3-opus': {'input': 1.5, 'output': 7.5},            # $0.015/$0.075 per 1M tokens
            'claude-4': {'input': 3.0, 'output': 15.0},                # $0.03/$0.15 per 1M tokens
            
            # No AI service used
            'none': {'input': 0.0, 'output': 0.0},
        }
        
        logger.info("APIPricingService initialized")
    
    async def analyze_and_price_api_code(
        self,
        api_slug: str,
        user_id: str,
        api_code: str,
        original_prompt: str = "",
        generation_model_used: Optional[str] = None
    ) -> APIMetadata:
        """
        Analyze generated API code to detect LLM usage and calculate accurate pricing.
        This should be called during the first API test to establish real pricing.
        """
        try:
            logger.info(f"Analyzing API code for pricing: {api_slug}")
            
            # Analyze the code for LLM usage
            analysis = await api_code_analyzer.analyze_api_code(api_code, original_prompt)
            
            # Determine AI model and tokens
            if analysis.uses_llm and analysis.primary_model:
                execution_model_used = analysis.primary_model  # Model detected in the API code
                ai_model_used = execution_model_used  # Use execution model as primary
                estimated_tokens_per_call = analysis.initial_tokens_estimate  # Initial estimate only
                base_complexity = analysis.complexity_rating
                
                logger.info(f"LLM usage detected: execution_model={execution_model_used}, generation_model={generation_model_used}")
                logger.info(f"Initial tokens={estimated_tokens_per_call}, complexity={base_complexity}")
                logger.info("Note: Initial token estimate will be replaced with real usage data after API executions")
            else:
                # No LLM usage detected - this is a regular processing API
                execution_model_used = None
                ai_model_used = 'none'
                estimated_tokens_per_call = 0
                base_complexity = 'simple'
                
                logger.info(f"No LLM usage detected - using free pricing model")
            
            # Save the analyzed metadata with proper model separation
            metadata = await self.save_api_metadata(
                api_slug=api_slug,
                user_id=user_id,
                ai_model_used=ai_model_used,
                estimated_tokens_per_call=estimated_tokens_per_call,
                base_complexity=base_complexity,
                generation_model_used=generation_model_used,
                execution_model_used=execution_model_used
            )
            
            # Add analysis details to metadata
            if hasattr(metadata, 'analysis_details'):
                metadata.analysis_details = analysis.analysis_details
            
            return metadata
            
        except Exception as e:
            logger.error(f"Failed to analyze and price API code: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to analyze API code: {str(e)}")
    
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
        base_complexity: str = 'medium',
        generation_model_used: Optional[str] = None,
        execution_model_used: Optional[str] = None
    ) -> APIMetadata:
        """Save metadata about a generated API including its cost structure."""
        
        try:
            # Calculate estimated cost per call using input/output pricing
            model_costs = self.AI_MODEL_BASE_COSTS.get(ai_model_used, {'input': 1.0, 'output': 1.0})
            complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(base_complexity, 1.5)
            
            # Estimate input/output token split (typically 70% input, 30% output for most APIs)
            input_tokens = estimated_tokens_per_call * 0.7
            output_tokens = estimated_tokens_per_call * 0.3
            
            # Calculate cost using input/output pricing (per 1M tokens)
            input_cost = (input_tokens / 1000000) * model_costs['input']
            output_cost = (output_tokens / 1000000) * model_costs['output']
            base_cost_cents = (input_cost + output_cost) * complexity_multiplier
            
            # Store cost in fractional cents (no multiplication needed since we corrected the base costs)
            # Example: 0.002 cents -> 0.002, 0.0015 cents -> 0.0015
            estimated_cost_cents_int = round(base_cost_cents, 6)
            
            metadata_id = str(uuid.uuid4())
            
            # Check if metadata already exists
            existing = mongodb.api_metadata.find_one({
                "api_slug": api_slug,
                "user_id": user_id
            })
            
            if existing:
                # Update existing
                update_data = {
                    "ai_model_used": ai_model_used,
                    "estimated_tokens_per_call": estimated_tokens_per_call,
                    "estimated_cost_per_call_cents": estimated_cost_cents_int,
                    "base_complexity": base_complexity,
                    "last_updated": datetime.utcnow()
                }
                
                # Add new fields if provided
                if generation_model_used:
                    update_data["generation_model_used"] = generation_model_used
                if execution_model_used:
                    update_data["execution_model_used"] = execution_model_used
                    # If we have execution model, use it as the primary ai_model_used
                    update_data["ai_model_used"] = execution_model_used
                
                mongodb.api_metadata.update_one(
                    {"_id": existing["_id"]},
                    {"$set": update_data}
                )
                db_metadata = mongodb.api_metadata.find_one({"_id": existing["_id"]})
            else:
                # Create new
                db_metadata = {
                    "_id": metadata_id,
                    "api_slug": api_slug,
                    "user_id": user_id,
                    "ai_model_used": execution_model_used or ai_model_used,  # Prefer execution model
                    "estimated_tokens_per_call": estimated_tokens_per_call,
                    "estimated_cost_per_call_cents": estimated_cost_cents_int,
                    "base_complexity": base_complexity,
                    "generation_model_used": generation_model_used,
                    "execution_model_used": execution_model_used,
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
                last_updated=db_metadata["last_updated"],
                generation_model_used=db_metadata.get("generation_model_used"),
                execution_model_used=db_metadata.get("execution_model_used"),
                real_avg_tokens_per_call=db_metadata.get("real_avg_tokens_per_call"),
                real_avg_cost_per_call_cents=db_metadata.get("real_avg_cost_per_call_cents"),
                real_model_used=db_metadata.get("real_model_used"),
                total_executions=db_metadata.get("total_executions"),
                successful_executions=db_metadata.get("successful_executions"),
                usage_last_updated=db_metadata.get("usage_last_updated"),
                has_real_usage_data=db_metadata.get("has_real_usage_data", False)
            )
                
            logger.info(f"Saved API metadata for {api_slug}: {estimated_cost_cents_int:.6f} cents per call")
            return metadata
                
        except Exception as e:
            logger.error(f"Failed to save API metadata: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to save API metadata: {str(e)}")
    
    async def get_api_execution_cost(
        self,
        api_slug: str,
        user_id: str
    ) -> APIExecutionCost:
        """Get the execution cost for a specific API, using real usage data when available."""
        logger.info(f"Getting API execution cost for {api_slug} for user {user_id}")
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
            
            # Check if metadata is outdated (missing new fields) and needs re-analysis
            needs_reanalysis = (
                metadata.get("generation_model_used") is None and 
                metadata.get("execution_model_used") is None and
                metadata.get("ai_model_used") != 'none'  # Only re-analyze APIs that use LLMs
            )
            
            if needs_reanalysis:
                logger.info(f"Detected outdated metadata for {api_slug}, triggering re-analysis")
                try:
                    # Load the API code for re-analysis
                    from .file_service import file_service
                    api_code = file_service.load_api_code(user_id, api_slug)
                    
                    # Get the generation model (fallback to current setting)
                    from app.config import settings
                    generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
                    
                    # Re-analyze the code
                    updated_metadata = await self.analyze_and_price_api_code(
                        api_slug=api_slug,
                        user_id=user_id,
                        api_code=api_code,
                        original_prompt="",  # We don't have the original prompt
                        generation_model_used=generation_model
                    )
                    
                    # Reload the updated metadata
                    metadata = mongodb.api_metadata.find_one({
                        "api_slug": api_slug,
                        "user_id": user_id
                    })
                    
                    logger.info(f"Re-analysis complete for {api_slug}: execution_model={metadata.get('execution_model_used')}, generation_model={metadata.get('generation_model_used')}")
                    
                except Exception as e:
                    logger.warning(f"Failed to re-analyze API {api_slug}: {e}")
                    # Continue with existing metadata as fallback
            
            # Check if we have real usage data
            usage_stats = await api_usage_aggregator.get_api_usage_stats(api_slug, user_id)
            
            if usage_stats and usage_stats.successful_executions >= 1:
                # Use real usage data (even with 1 execution for better accuracy)
                # Real usage already includes accurate cost calculation - no multipliers needed
                cost_per_call_cents = round(usage_stats.avg_cost_per_call_cents, 2)
                tokens_used = int(round(usage_stats.avg_total_tokens))
                
                # Prioritize real usage model over metadata
                if usage_stats.primary_model_used:
                    model_used = usage_stats.primary_model_used
                    logger.info(f"Using real execution model from usage data: {model_used}")
                else:
                    # Fallback to execution model from metadata, then ai_model_used
                    model_used = metadata.get("execution_model_used") or metadata["ai_model_used"]
                    logger.info(f"Using model from metadata (no real usage model): {model_used}")
                
                if usage_stats.successful_executions >= 3:
                    logger.info(f"Using reliable real usage data for {api_slug}: "
                               f"avg ${cost_per_call_cents/100:.6f} per call, "
                               f"avg {tokens_used} tokens, {usage_stats.successful_executions} executions, "
                               f"model: {model_used}")
                else:
                    logger.info(f"Using real usage data for {api_slug} (limited sample): "
                               f"avg ${cost_per_call_cents/100:.6f} per call, "
                               f"avg {tokens_used} tokens, {usage_stats.successful_executions} executions, "
                               f"model: {model_used}")
                
                # Update metadata with real usage data
                await api_usage_aggregator.update_api_pricing_with_real_usage(api_slug, user_id)
                
            else:
                # Fall back to initial estimates
                # estimated_cost_per_call_cents is now stored as fractional cents directly
                cost_per_call_cents = metadata["estimated_cost_per_call_cents"]
                tokens_used = int(metadata["estimated_tokens_per_call"])
                
                # Use execution model if available, otherwise fall back to ai_model_used
                model_used = metadata.get("execution_model_used") or metadata["ai_model_used"]
                
                logger.info(f"Using initial estimates for {api_slug} (no usage data yet): {cost_per_call_cents:.6f} cents per call, model: {model_used}")
            
            # Convert cost to internal tokens (handle fractional cents)
            internal_tokens_per_call = max(1, int(round(cost_per_call_cents * self.TOKENS_PER_CENT)))
            
            # Determine if we're using real usage or estimates
            using_real_data = usage_stats and usage_stats.successful_executions >= 1
            
            if using_real_data:
                # Real usage data - no complexity multiplier needed
                complexity_multiplier = 1.0  # Real data is already accurate
                base_cost_cents = cost_per_call_cents
            else:
                # Initial estimates - apply complexity multiplier
                complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(metadata["base_complexity"], 1.5)
                base_cost_cents = cost_per_call_cents / complexity_multiplier
            
            return APIExecutionCost(
                api_slug=metadata["api_slug"],
                user_id=metadata["user_id"],
                cost_per_call_cents=cost_per_call_cents,
                internal_tokens_per_call=internal_tokens_per_call,
                ai_model_used=model_used,
                complexity_multiplier=complexity_multiplier,
                base_cost_cents=base_cost_cents,
                estimated_tokens_used=tokens_used,
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
    
    async def get_api_usage_cost_with_real_data(
        self,
        api_slug: str,
        user_id: str,
        expected_calls_per_month: int = 1000
    ) -> EstimateAPIUsageCostResponse:
        """Get API usage cost using real usage data when available, fallback to initial estimates."""
        
        try:
            # Get current cost information (uses real usage if available)
            cost_info = await self.get_api_execution_cost(api_slug, user_id)
            
            # Check if we have real usage data
            usage_stats = await api_usage_aggregator.get_api_usage_stats(api_slug, user_id)
            
            # Calculate monthly projections (ensure integers)
            cost_per_call_cents = cost_info.cost_per_call_cents  # Keep fractional precision
            internal_tokens_per_call = int(cost_info.internal_tokens_per_call)
            
            estimated_monthly_cost = cost_per_call_cents * expected_calls_per_month
            estimated_monthly_tokens = internal_tokens_per_call * expected_calls_per_month
            
            # Determine if this is based on real usage or estimates
            data_source = "real_usage" if usage_stats and usage_stats.successful_executions >= 1 else "initial_estimate"
            
            breakdown = {
                'data_source': data_source,
                'successful_executions': usage_stats.successful_executions if usage_stats else 0,
                'avg_tokens_per_call': int(usage_stats.avg_total_tokens) if usage_stats else cost_info.estimated_tokens_used,
                'cost_per_call_cents': cost_per_call_cents,
                'internal_tokens_per_call': internal_tokens_per_call,
                'expected_calls_per_month': expected_calls_per_month,
                'note': f'Based on real usage data ({usage_stats.successful_executions} executions)' if data_source == "real_usage" else 'Based on initial estimates - will improve with usage'
            }
            
            return EstimateAPIUsageCostResponse(
                api_slug=api_slug,
                cost_per_call_cents=cost_per_call_cents,
                internal_tokens_per_call=internal_tokens_per_call,
                estimated_monthly_cost_cents=estimated_monthly_cost,
                estimated_monthly_tokens=estimated_monthly_tokens,
                ai_model_used=cost_info.ai_model_used,
                complexity_rating="real_usage" if data_source == "real_usage" else "estimated",
                breakdown=breakdown
            )
            
        except Exception as e:
            logger.error(f"Failed to get API usage cost: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get API usage cost: {str(e)}")
    
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