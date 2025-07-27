import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy import select, and_, func, text, or_
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import (
    APIMetadata, InternalToken, InternalTokenBalance, APIExecutionCost,
    APIExecutionTokenUsage, EstimateAPIUsageCostRequest, EstimateAPIUsageCostResponse,
    CreateInternalTokenRequest, InternalTokenUsageStatsResponse
)
from .database import APIMetadataDB, InternalTokenDB, APIExecutionTokenUsageDB, AsyncSessionLocal
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class APIPricingService:
    def __init__(self):
        # Internal token pricing - how many internal tokens equal 1 cent
        self.TOKENS_PER_CENT = 10  # 10 internal tokens = 1 cent
        
        # Monthly token allocations by plan (free tier)
        self.DEFAULT_MONTHLY_TOKEN_ALLOCATION = 10000  # 10k internal tokens = $10 worth
        
        # Base pricing multipliers by complexity
        self.COMPLEXITY_MULTIPLIERS = {
            'simple': 1.0,      # Basic APIs (text processing, simple calculations)
            'medium': 1.5,      # APIs with moderate logic (data transformation, validation)
            'complex': 2.0      # Advanced APIs (ML inference, complex business logic)
        }
        
        # AI model base costs (per 1k tokens) in cents
        self.AI_MODEL_BASE_COSTS = {
            'gpt-3.5-turbo': 0.15,      # $0.0015 per 1k tokens
            'gpt-4': 3.0,               # $0.03 per 1k tokens
            'gpt-4-turbo': 1.0,         # $0.01 per 1k tokens
            'claude-3-haiku': 0.25,     # $0.0025 per 1k tokens
            'claude-3-sonnet': 3.0,     # $0.03 per 1k tokens (fixed from 30.0)
            'claude-3-opus': 15.0,      # $0.15 per 1k tokens (fixed from 150.0)
            'none': 0.0,                # No AI service used - free processing
        }
        
        logger.info("APIPricingService initialized")
    
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
            
            async with AsyncSessionLocal() as session:
                # Check if metadata already exists
                existing = await session.execute(
                    select(APIMetadataDB).where(
                        and_(
                            APIMetadataDB.api_slug == api_slug,
                            APIMetadataDB.user_id == user_id
                        )
                    )
                )
                
                db_metadata = existing.scalar_one_or_none()
                
                if db_metadata:
                    # Update existing
                    db_metadata.ai_model_used = ai_model_used
                    db_metadata.estimated_tokens_per_call = estimated_tokens_per_call
                    db_metadata.estimated_cost_per_call_cents = estimated_cost_cents
                    db_metadata.base_complexity = base_complexity
                    db_metadata.last_updated = datetime.utcnow()
                else:
                    # Create new
                    db_metadata = APIMetadataDB(
                        id=metadata_id,
                        api_slug=api_slug,
                        user_id=user_id,
                        ai_model_used=ai_model_used,
                        estimated_tokens_per_call=estimated_tokens_per_call,
                        estimated_cost_per_call_cents=estimated_cost_cents,
                        base_complexity=base_complexity,
                        created_at=datetime.utcnow(),
                        last_updated=datetime.utcnow()
                    )
                    session.add(db_metadata)
                
                await session.commit()
                await session.refresh(db_metadata)
                
                metadata = APIMetadata(
                    api_slug=db_metadata.api_slug,
                    user_id=db_metadata.user_id,
                    ai_model_used=db_metadata.ai_model_used,
                    estimated_tokens_per_call=db_metadata.estimated_tokens_per_call,
                    estimated_cost_per_call_cents=db_metadata.estimated_cost_per_call_cents,
                    base_complexity=db_metadata.base_complexity,
                    created_at=db_metadata.created_at,
                    last_updated=db_metadata.last_updated
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
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(APIMetadataDB).where(
                        and_(
                            APIMetadataDB.api_slug == api_slug,
                            APIMetadataDB.user_id == user_id
                        )
                    )
                )
                
                metadata = result.scalar_one_or_none()
                
                if not metadata:
                    raise HTTPException(
                        status_code=404,
                        detail=f"API metadata not found for {api_slug}"
                    )
                
                # Convert cost to internal tokens
                internal_tokens_per_call = metadata.estimated_cost_per_call_cents * self.TOKENS_PER_CENT
                complexity_multiplier = self.COMPLEXITY_MULTIPLIERS.get(metadata.base_complexity, 1.5)
                
                return APIExecutionCost(
                    api_slug=metadata.api_slug,
                    user_id=metadata.user_id,
                    cost_per_call_cents=metadata.estimated_cost_per_call_cents,
                    internal_tokens_per_call=internal_tokens_per_call,
                    ai_model_used=metadata.ai_model_used,
                    complexity_multiplier=complexity_multiplier,
                    base_cost_cents=int(metadata.estimated_cost_per_call_cents / complexity_multiplier),
                    estimated_tokens_used=metadata.estimated_tokens_per_call,
                    last_calculated=metadata.last_updated
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get API execution cost: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get API execution cost: {str(e)}")
    
    async def allocate_monthly_tokens(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        amount: Optional[int] = None,
        source: str = "monthly_allocation"
    ) -> InternalToken:
        """Allocate monthly tokens to a user."""
        
        if amount is None:
            amount = self.DEFAULT_MONTHLY_TOKEN_ALLOCATION
        
        try:
            token_id = str(uuid.uuid4())
            
            async with AsyncSessionLocal() as session:
                # Set expiration to end of next month
                now = datetime.utcnow()
                next_month = now.replace(day=1) + timedelta(days=32)
                expires_at = next_month.replace(day=1) - timedelta(days=1)
                
                db_token = InternalTokenDB(
                    id=token_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    token_type='api_execution',
                    amount=amount,
                    source=source,
                    expires_at=expires_at,
                    created_at=datetime.utcnow(),
                    is_used=False
                )
                
                session.add(db_token)
                await session.commit()
                await session.refresh(db_token)
                
                token = InternalToken(
                    id=db_token.id,
                    user_id=db_token.user_id,
                    api_key_id=db_token.api_key_id,
                    token_type=db_token.token_type,
                    amount=db_token.amount,
                    source=db_token.source,
                    expires_at=db_token.expires_at,
                    created_at=db_token.created_at,
                    used_at=db_token.used_at,
                    is_used=db_token.is_used
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
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                seven_days_from_now = now + timedelta(days=7)
                
                # Get all unused tokens
                query = select(InternalTokenDB).where(
                    and_(
                        InternalTokenDB.user_id == user_id,
                        InternalTokenDB.is_used == False,
                        or_(
                            InternalTokenDB.expires_at.is_(None),
                            InternalTokenDB.expires_at > now
                        )
                    )
                )
                
                if api_key_id:
                    query = query.where(InternalTokenDB.api_key_id == api_key_id)
                
                result = await session.execute(query)
                unused_tokens = result.scalars().all()
                
                total_tokens = sum(token.amount for token in unused_tokens)
                
                # Get tokens expiring soon
                expires_soon_tokens = sum(
                    token.amount for token in unused_tokens 
                    if token.expires_at and token.expires_at <= seven_days_from_now
                )
                
                # Get used tokens this month
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                used_query = select(
                    func.sum(APIExecutionTokenUsageDB.internal_tokens_used)
                ).where(
                    and_(
                        APIExecutionTokenUsageDB.user_id == user_id,
                        APIExecutionTokenUsageDB.created_at >= month_start
                    )
                )
                
                if api_key_id:
                    used_query = used_query.where(APIExecutionTokenUsageDB.api_key_id == api_key_id)
                
                used_result = await session.execute(used_query)
                used_tokens = used_result.scalar() or 0
                
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
            
            async with AsyncSessionLocal() as session:
                # Only deduct tokens if execution was successful
                if execution_successful and internal_tokens_needed > 0:
                    # Get available tokens (oldest first to use expiring tokens first)
                    now = datetime.utcnow()
                    
                    query = select(InternalTokenDB).where(
                        and_(
                            InternalTokenDB.user_id == user_id,
                            InternalTokenDB.is_used == False,
                            or_(
                                InternalTokenDB.expires_at.is_(None),
                                InternalTokenDB.expires_at > now
                            )
                        )
                    ).order_by(InternalTokenDB.expires_at.asc().nulls_last())
                    
                    if api_key_id:
                        query = query.where(InternalTokenDB.api_key_id == api_key_id)
                    
                    result = await session.execute(query)
                    available_tokens = result.scalars().all()
                    
                    total_available = sum(token.amount for token in available_tokens)
                    
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
                        
                        if token.amount <= tokens_remaining:
                            # Use entire token
                            token.is_used = True
                            token.used_at = datetime.utcnow()
                            tokens_remaining -= token.amount
                        else:
                            # Split token (create new token with remaining amount)
                            new_token_id = str(uuid.uuid4())
                            remaining_amount = token.amount - tokens_remaining
                            
                            # Mark original as used
                            token.is_used = True
                            token.used_at = datetime.utcnow()
                            token.amount = tokens_remaining
                            
                            # Create new token with remaining amount
                            new_token = InternalTokenDB(
                                id=new_token_id,
                                user_id=token.user_id,
                                api_key_id=token.api_key_id,
                                token_type=token.token_type,
                                amount=remaining_amount,
                                source=token.source,
                                expires_at=token.expires_at,
                                created_at=datetime.utcnow(),
                                is_used=False
                            )
                            session.add(new_token)
                            
                            tokens_remaining = 0
                
                # Record usage
                db_usage = APIExecutionTokenUsageDB(
                    id=usage_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    internal_tokens_used=internal_tokens_needed if execution_successful else 0,
                    cost_cents=cost_cents,
                    execution_successful=execution_successful,
                    created_at=datetime.utcnow()
                )
                
                session.add(db_usage)
                await session.commit()
                await session.refresh(db_usage)
                
                usage = APIExecutionTokenUsage(
                    id=db_usage.id,
                    user_id=db_usage.user_id,
                    api_key_id=db_usage.api_key_id,
                    api_slug=db_usage.api_slug,
                    internal_tokens_used=db_usage.internal_tokens_used,
                    cost_cents=db_usage.cost_cents,
                    execution_successful=db_usage.execution_successful,
                    created_at=db_usage.created_at
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
                ai_model = 'gpt-3.5-turbo'
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

# Global instance
api_pricing_service = APIPricingService() 