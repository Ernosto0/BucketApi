import uuid
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from sqlalchemy import select, and_, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import (
    Usage, UsageStatsResponse, UsageLimitsResponse, CreateUsageRequest
)
from .database import LLMUsageDB, AsyncSessionLocal
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class UsageService:
    def __init__(self):
        # Default limits (can be made configurable per user/plan)
        self.DEFAULT_DAILY_TOKEN_LIMIT = 100000  # 100k tokens per day
        self.DEFAULT_MONTHLY_TOKEN_LIMIT = 1000000  # 1M tokens per month
        self.DEFAULT_DAILY_COST_LIMIT_CENTS = 1000  # $10 per day
        
        # Cost per token in cents (approximate, based on current pricing)
        self.COST_PER_TOKEN = {
            # Claude pricing (input/output tokens) - Updated December 2024
            'claude-3-haiku': {'input': 0.000025, 'output': 0.000125},  # $0.25/$1.25 per MTok
            'claude-3.5-haiku': {'input': 0.00008, 'output': 0.0004},   # $0.80/$4.00 per MTok
            'claude-3-sonnet': {'input': 0.0003, 'output': 0.0015},     # $3/$15 per MTok
            'claude-3.5-sonnet': {'input': 0.0003, 'output': 0.0015},   # $3/$15 per MTok (legacy)
            'claude-3.7-sonnet': {'input': 0.0003, 'output': 0.0015},   # $3/$15 per MTok
            'claude-3-opus': {'input': 0.0015, 'output': 0.0075},       # $15/$75 per MTok
            'claude-4-opus': {'input': 0.0015, 'output': 0.0075},       # $15/$75 per MTok
            'claude-4-sonnet': {'input': 0.0003, 'output': 0.0015},     # $3/$15 per MTok
            
            # OpenAI pricing (keeping existing for compatibility)
            'gpt-3.5-turbo': {'input': 0.00015, 'output': 0.0002},
            'gpt-4': {'input': 0.003, 'output': 0.006},
            'gpt-4-turbo': {'input': 0.001, 'output': 0.002},
        }
        
        logger.info("UsageService initialized")
    
    async def record_usage(
        self,
        user_id: str,
        api_key_id: Optional[str],
        service_type: str,
        operation_type: str,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        prompt_length: int = 0,
        response_length: int = 0,
        request_duration_ms: int = 0,
        operation_context: Optional[Dict[str, Any]] = None,
        api_slug: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> Usage:
        """Record a new LLM usage entry."""
        
        try:
            # Calculate total tokens and estimated cost
            total_tokens = input_tokens + output_tokens
            estimated_cost_cents = self._calculate_cost_cents(
                model_name, input_tokens, output_tokens
            )
            
            # Create usage record
            usage_id = str(uuid.uuid4())
            context_json = json.dumps(operation_context) if operation_context else None
            
            async with AsyncSessionLocal() as session:
                db_usage = LLMUsageDB(
                    id=usage_id,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    service_type=service_type,
                    operation_type=operation_type,
                    model_name=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_cents=estimated_cost_cents,
                    prompt_length=prompt_length,
                    response_length=response_length,
                    request_duration_ms=request_duration_ms,
                    operation_context=context_json,
                    api_slug=api_slug,
                    created_at=datetime.utcnow(),
                    completed_at=datetime.utcnow() if success else None,
                    success=success,
                    error_message=error_message
                )
                
                session.add(db_usage)
                await session.commit()
                await session.refresh(db_usage)
                
                # Convert to Pydantic model
                usage = Usage(
                    user_id=db_usage.user_id,
                    api_key_id=db_usage.api_key_id,
                    service_type=db_usage.service_type,
                    operation_type=db_usage.operation_type,
                    model_name=db_usage.model_name,
                    input_tokens=db_usage.input_tokens,
                    output_tokens=db_usage.output_tokens,
                    total_tokens=db_usage.total_tokens,
                    estimated_cost_cents=db_usage.estimated_cost_cents,
                    prompt_length=db_usage.prompt_length,
                    response_length=db_usage.response_length,
                    request_duration_ms=db_usage.request_duration_ms,
                    operation_context=db_usage.operation_context,
                    api_slug=db_usage.api_slug,
                    created_at=db_usage.created_at,
                    completed_at=db_usage.completed_at,
                    success=db_usage.success,
                    error_message=db_usage.error_message
                )
                
                logger.info(f"Recorded usage for user {user_id}: {total_tokens} tokens, ${estimated_cost_cents/100:.4f}")
                return usage
                
        except Exception as e:
            logger.error(f"Failed to record usage: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to record usage: {str(e)}")
    
    async def check_usage_limits(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        tokens_to_use: int = 0
    ) -> UsageLimitsResponse:
        """Check if user is within usage limits."""
        
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                
                # Query daily usage
                daily_query = select(
                    func.sum(LLMUsageDB.total_tokens).label('total_tokens'),
                    func.sum(LLMUsageDB.estimated_cost_cents).label('total_cost')
                ).where(
                    and_(
                        LLMUsageDB.user_id == user_id,
                        LLMUsageDB.created_at >= today_start,
                        LLMUsageDB.success == True
                    )
                )
                
                if api_key_id:
                    daily_query = daily_query.where(LLMUsageDB.api_key_id == api_key_id)
                
                daily_result = await session.execute(daily_query)
                daily_row = daily_result.first()
                
                daily_tokens_used = daily_row.total_tokens or 0
                daily_cost_used_cents = daily_row.total_cost or 0
                
                # Query monthly usage
                monthly_query = select(
                    func.sum(LLMUsageDB.total_tokens).label('total_tokens')
                ).where(
                    and_(
                        LLMUsageDB.user_id == user_id,
                        LLMUsageDB.created_at >= month_start,
                        LLMUsageDB.success == True
                    )
                )
                
                if api_key_id:
                    monthly_query = monthly_query.where(LLMUsageDB.api_key_id == api_key_id)
                
                monthly_result = await session.execute(monthly_query)
                monthly_row = monthly_result.first()
                monthly_tokens_used = monthly_row.total_tokens or 0
                
                # Calculate limits and remaining usage
                daily_token_limit = self.DEFAULT_DAILY_TOKEN_LIMIT
                monthly_token_limit = self.DEFAULT_MONTHLY_TOKEN_LIMIT
                daily_cost_limit_cents = self.DEFAULT_DAILY_COST_LIMIT_CENTS
                
                daily_tokens_remaining = max(0, daily_token_limit - daily_tokens_used)
                monthly_tokens_remaining = max(0, monthly_token_limit - monthly_tokens_used)
                daily_cost_remaining_cents = max(0, daily_cost_limit_cents - daily_cost_used_cents)
                
                # Check if adding the new tokens would exceed limits
                is_over_limit = (
                    (daily_tokens_used + tokens_to_use) > daily_token_limit or
                    (monthly_tokens_used + tokens_to_use) > monthly_token_limit
                )
                
                # Next reset time (tomorrow at midnight)
                limit_reset_time = today_start + timedelta(days=1)
                
                return UsageLimitsResponse(
                    user_id=user_id,
                    api_key_id=api_key_id,
                    daily_token_limit=daily_token_limit,
                    daily_tokens_used=daily_tokens_used,
                    daily_tokens_remaining=daily_tokens_remaining,
                    monthly_token_limit=monthly_token_limit,
                    monthly_tokens_used=monthly_tokens_used,
                    monthly_tokens_remaining=monthly_tokens_remaining,
                    daily_cost_limit_cents=daily_cost_limit_cents,
                    daily_cost_used_cents=daily_cost_used_cents,
                    daily_cost_remaining_cents=daily_cost_remaining_cents,
                    limit_reset_time=limit_reset_time,
                    is_over_limit=is_over_limit
                )
                
        except Exception as e:
            logger.error(f"Failed to check usage limits: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to check usage limits: {str(e)}")
    
    async def get_usage_stats(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        days: int = 30
    ) -> UsageStatsResponse:
        """Get usage statistics for a user."""
        
        try:
            async with AsyncSessionLocal() as session:
                now = datetime.utcnow()
                period_start = now - timedelta(days=days)
                
                # Build base query
                base_query = select(LLMUsageDB).where(
                    and_(
                        LLMUsageDB.user_id == user_id,
                        LLMUsageDB.created_at >= period_start,
                        LLMUsageDB.success == True
                    )
                )
                
                if api_key_id:
                    base_query = base_query.where(LLMUsageDB.api_key_id == api_key_id)
                
                result = await session.execute(base_query)
                usage_records = result.scalars().all()
                
                # Calculate totals
                total_requests = len(usage_records)
                total_tokens = sum(record.total_tokens for record in usage_records)
                total_cost_cents = sum(record.estimated_cost_cents for record in usage_records)
                
                # Group by service
                by_service = {}
                by_operation = {}
                
                for record in usage_records:
                    # By service
                    if record.service_type not in by_service:
                        by_service[record.service_type] = {
                            'requests': 0, 'tokens': 0, 'cost_cents': 0
                        }
                    by_service[record.service_type]['requests'] += 1
                    by_service[record.service_type]['tokens'] += record.total_tokens
                    by_service[record.service_type]['cost_cents'] += record.estimated_cost_cents
                    
                    # By operation
                    if record.operation_type not in by_operation:
                        by_operation[record.operation_type] = {
                            'requests': 0, 'tokens': 0, 'cost_cents': 0
                        }
                    by_operation[record.operation_type]['requests'] += 1
                    by_operation[record.operation_type]['tokens'] += record.total_tokens
                    by_operation[record.operation_type]['cost_cents'] += record.estimated_cost_cents
                
                # Get recent usage (last 10 records)
                recent_query = base_query.order_by(LLMUsageDB.created_at.desc()).limit(10)
                recent_result = await session.execute(recent_query)
                recent_records = recent_result.scalars().all()
                
                recent_usage = [
                    Usage(
                        user_id=record.user_id,
                        api_key_id=record.api_key_id,
                        service_type=record.service_type,
                        operation_type=record.operation_type,
                        model_name=record.model_name,
                        input_tokens=record.input_tokens,
                        output_tokens=record.output_tokens,
                        total_tokens=record.total_tokens,
                        estimated_cost_cents=record.estimated_cost_cents,
                        prompt_length=record.prompt_length,
                        response_length=record.response_length,
                        request_duration_ms=record.request_duration_ms,
                        operation_context=record.operation_context,
                        api_slug=record.api_slug,
                        created_at=record.created_at,
                        completed_at=record.completed_at,
                        success=record.success,
                        error_message=record.error_message
                    )
                    for record in recent_records
                ]
                
                return UsageStatsResponse(
                    user_id=user_id,
                    total_requests=total_requests,
                    total_tokens=total_tokens,
                    total_cost_cents=total_cost_cents,
                    by_service=by_service,
                    by_operation=by_operation,
                    recent_usage=recent_usage,
                    period_start=period_start,
                    period_end=now
                )
                
        except Exception as e:
            logger.error(f"Failed to get usage stats: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get usage stats: {str(e)}")
    
    def _calculate_cost_cents(self, model_name: str, input_tokens: int, output_tokens: int) -> int:
        """Calculate estimated cost in cents for token usage."""
        
        # Get pricing for model
        if model_name not in self.COST_PER_TOKEN:
            logger.warning(f"Unknown model {model_name}, using default pricing")
            # Default to GPT-3.5 pricing
            pricing = self.COST_PER_TOKEN['gpt-3.5-turbo']
        else:
            pricing = self.COST_PER_TOKEN[model_name]
        
        # Calculate cost in dollars
        input_cost = input_tokens * pricing['input']
        output_cost = output_tokens * pricing['output']
        total_cost_dollars = input_cost + output_cost
        
        # Convert to cents
        return int(total_cost_dollars * 100)
    
    async def estimate_request_cost(
        self,
        model_name: str,
        estimated_input_tokens: int,
        estimated_output_tokens: int = 1000  # Default estimate
    ) -> int:
        """Estimate cost in cents for a request before making it."""
        return self._calculate_cost_cents(model_name, estimated_input_tokens, estimated_output_tokens)

# Global instance
usage_service = UsageService() 