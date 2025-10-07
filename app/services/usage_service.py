import uuid
import json
import logging
import re
import functools
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
# MongoDB operations handled through mongodb service

# Token counting libraries
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

try:
    import warnings
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*PyTorch, TensorFlow.*")
        from transformers import AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False

from ..models import (
    Usage, UsageStatsResponse, UsageLimitsResponse, CreateUsageRequest
)
from .mongodb import mongodb
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class UsageService:
    def __init__(self):
        # Default limits (can be made configurable per user/plan)
        self.DEFAULT_DAILY_TOKEN_LIMIT = 100000  # 100k tokens per day
        self.DEFAULT_MONTHLY_TOKEN_LIMIT = 1000000  # 1M tokens per month
        self.DEFAULT_DAILY_COST_LIMIT_CENTS = 1000  # $10 per day
        
        # Short-term rate limits for burst protection
        self.DEFAULT_HOURLY_TOKEN_LIMIT = 20000  # 10k tokens per hour
        self.DEFAULT_MINUTELY_REQUEST_LIMIT = 100  # 100 requests per minute
        
        # Initialize token estimation components
        self._init_token_estimators()
        
        # Cost per token in cents (approximate, based on current pricing)
        self.COST_PER_TOKEN = {
            # TODO Update this to use the actual pricing from the API at deployment
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
            'gpt-3.5-turbo': {'input': 0.000015, 'output': 0.00003},
            'gpt-4o': {'input': 0.000015, 'output': 0.00003},
            'gpt-4o-mini': {'input': 0.000015, 'output': 0.00003},
            'gpt-4': {'input': 0.000015, 'output': 0.00003},
            'gpt-4-turbo': {'input': 0.000015, 'output': 0.00003},
            'gpt-5-mini': {'input': 0.00015, 'output': 0.0002},
        }
        
        # Log warnings for missing dependencies
        if not TIKTOKEN_AVAILABLE:
            logger.warning("tiktoken not available, falling back to approximation for OpenAI models")
        if not TRANSFORMERS_AVAILABLE:
            logger.warning("transformers not available, advanced tokenization features disabled")
            
        logger.info("UsageService initialized")
    
    def _init_token_estimators(self):
        """Initialize token estimation tools for different models"""
        self.token_estimators = {}
        self.tokenizer_cache = {}
        
        # Initialize OpenAI encoders if tiktoken is available
        if TIKTOKEN_AVAILABLE:
            try:
                # Common OpenAI model encodings
                openai_models = {
                    'gpt-4': 'cl100k_base',
                    'gpt-4-turbo': 'cl100k_base', 
                    'gpt-4o': 'o200k_base',
                    'gpt-4o-mini': 'o200k_base',
                    'gpt-5-mini': 'o200k_base',  # Assuming similar encoding
                    'gpt-3.5-turbo': 'cl100k_base'
                }
                
                for model, encoding_name in openai_models.items():
                    try:
                        self.token_estimators[model] = tiktoken.get_encoding(encoding_name)
                        logger.info(f"Loaded tiktoken encoder for {model}")
                    except Exception as e:
                        logger.warning(f"Failed to load tiktoken encoder for {model}: {e}")
                        
            except Exception as e:
                logger.warning(f"Failed to initialize tiktoken encoders: {e}")
        
        # Model-specific token patterns and multipliers for better estimation
        self.model_estimation_params = {
            # Claude models - based on observed patterns
            'claude-3-haiku': {'chars_per_token': 3.8, 'overhead_tokens': 10},
            'claude-3.5-haiku': {'chars_per_token': 3.8, 'overhead_tokens': 12},
            'claude-3-sonnet': {'chars_per_token': 4.1, 'overhead_tokens': 15},
            'claude-3.5-sonnet': {'chars_per_token': 4.1, 'overhead_tokens': 15},
            'claude-3.7-sonnet': {'chars_per_token': 4.1, 'overhead_tokens': 15},
            'claude-3-opus': {'chars_per_token': 4.2, 'overhead_tokens': 20},
            'claude-4-opus': {'chars_per_token': 4.2, 'overhead_tokens': 20},
            'claude-4-sonnet': {'chars_per_token': 4.1, 'overhead_tokens': 15},
            
            # OpenAI models - fallback if tiktoken fails
            'gpt-4': {'chars_per_token': 4.0, 'overhead_tokens': 8},
            'gpt-4-turbo': {'chars_per_token': 4.0, 'overhead_tokens': 8},
            'gpt-4o': {'chars_per_token': 3.9, 'overhead_tokens': 10},
            'gpt-4o-mini': {'chars_per_token': 3.9, 'overhead_tokens': 10},
            'gpt-5-mini': {'chars_per_token': 3.9, 'overhead_tokens': 10},
            'gpt-3.5-turbo': {'chars_per_token': 4.2, 'overhead_tokens': 6},
        }
        
        logger.info(f"Initialized token estimation for {len(self.model_estimation_params)} models")
    
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
            
            # Create usage record in MongoDB
            db_usage = {
                "_id": usage_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "service_type": service_type,
                "operation_type": operation_type,
                "model_name": model_name,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "estimated_cost_cents": estimated_cost_cents,
                "prompt_length": prompt_length,
                "response_length": response_length,
                "request_duration_ms": request_duration_ms,
                "operation_context": context_json,
                "api_slug": api_slug,
                "created_at": datetime.utcnow(),
                "completed_at": datetime.utcnow() if success else None,
                "success": success,
                "error_message": error_message
            }
            
            mongodb.llm_usage.insert_one(db_usage)
            
            # Convert to Pydantic model
            usage = Usage(
                user_id=db_usage["user_id"],
                api_key_id=db_usage["api_key_id"],
                    service_type=db_usage["service_type"],
                    operation_type=db_usage["operation_type"],
                    model_name=db_usage["model_name"],
                    input_tokens=db_usage["input_tokens"],
                    output_tokens=db_usage["output_tokens"],
                    total_tokens=db_usage["total_tokens"],
                    estimated_cost_cents=db_usage["estimated_cost_cents"],
                    prompt_length=db_usage["prompt_length"],
                    response_length=db_usage["response_length"],
                    request_duration_ms=db_usage["request_duration_ms"],
                    operation_context=db_usage["operation_context"],
                    api_slug=db_usage["api_slug"],
                    created_at=db_usage["created_at"],
                    completed_at=db_usage["completed_at"],
                    success=db_usage["success"],
                    error_message=db_usage["error_message"]
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
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            hour_start = now.replace(minute=0, second=0, microsecond=0)
            minute_start = now.replace(second=0, microsecond=0)
            
            # Build base match conditions
            base_match = {
                "user_id": user_id,
                "created_at": {"$gte": today_start},
                "success": True
            }
            
            if api_key_id:
                base_match["api_key_id"] = api_key_id
            
            # Query daily usage
            daily_pipeline = [
                {"$match": base_match},
                {"$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$total_tokens"},
                    "total_cost": {"$sum": "$estimated_cost_cents"}
                }}
            ]
            
            daily_result = list(mongodb.llm_usage.aggregate(daily_pipeline))
            daily_tokens_used = daily_result[0]["total_tokens"] if daily_result else 0
            daily_cost_used_cents = daily_result[0]["total_cost"] if daily_result else 0
                
            # Query monthly usage
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
                    "total_tokens": {"$sum": "$total_tokens"}
                }}
            ]
            
            monthly_result = list(mongodb.llm_usage.aggregate(monthly_pipeline))
            monthly_tokens_used = monthly_result[0]["total_tokens"] if monthly_result else 0
            
            # Query hourly usage
            hourly_match = {
                "user_id": user_id,
                "created_at": {"$gte": hour_start},
                "success": True
            }
            
            if api_key_id:
                hourly_match["api_key_id"] = api_key_id
            
            hourly_pipeline = [
                {"$match": hourly_match},
                {"$group": {
                    "_id": None,
                    "total_tokens": {"$sum": "$total_tokens"}
                }}
            ]
            
            hourly_result = list(mongodb.llm_usage.aggregate(hourly_pipeline))
            hourly_tokens_used = hourly_result[0]["total_tokens"] if hourly_result else 0
            
            # Query minute usage (request count)
            minute_match = {
                "user_id": user_id,
                "created_at": {"$gte": minute_start},
                "success": True
            }
            
            if api_key_id:
                minute_match["api_key_id"] = api_key_id
            
            minute_pipeline = [
                {"$match": minute_match},
                {"$group": {
                    "_id": None,
                    "request_count": {"$sum": 1}
                }}
            ]
            
            minute_result = list(mongodb.llm_usage.aggregate(minute_pipeline))
            minute_requests_used = minute_result[0]["request_count"] if minute_result else 0
            
            # Calculate limits and remaining usage
            daily_token_limit = self.DEFAULT_DAILY_TOKEN_LIMIT
            monthly_token_limit = self.DEFAULT_MONTHLY_TOKEN_LIMIT
            daily_cost_limit_cents = self.DEFAULT_DAILY_COST_LIMIT_CENTS
            hourly_token_limit = self.DEFAULT_HOURLY_TOKEN_LIMIT
            minutely_request_limit = self.DEFAULT_MINUTELY_REQUEST_LIMIT
            
            daily_tokens_remaining = max(0, daily_token_limit - daily_tokens_used)
            monthly_tokens_remaining = max(0, monthly_token_limit - monthly_tokens_used)
            daily_cost_remaining_cents = max(0, daily_cost_limit_cents - daily_cost_used_cents)
            hourly_tokens_remaining = max(0, hourly_token_limit - hourly_tokens_used)
            minutely_requests_remaining = max(0, minutely_request_limit - minute_requests_used)
            
            # Estimate cost for the new tokens
            estimated_new_cost_cents = self._calculate_cost_cents(
                "gpt-5-mini",  # Use default model for estimation
                tokens_to_use // 2,  # Rough split between input/output
                tokens_to_use // 2
            )
            
            # Check if adding the new tokens would exceed limits
            is_over_limit = (
                (daily_tokens_used + tokens_to_use) > daily_token_limit or
                (monthly_tokens_used + tokens_to_use) > monthly_token_limit or
                (daily_cost_used_cents + estimated_new_cost_cents) > daily_cost_limit_cents or
                (hourly_tokens_used + tokens_to_use) > hourly_token_limit or
                (minute_requests_used + 1) > minutely_request_limit  # +1 for this request
            )
            
            # Determine which limit was exceeded for better error messages
            limit_exceeded_reason = None
            if (daily_tokens_used + tokens_to_use) > daily_token_limit:
                limit_exceeded_reason = f"Daily token limit exceeded: {daily_tokens_used + tokens_to_use}/{daily_token_limit}"
            elif (monthly_tokens_used + tokens_to_use) > monthly_token_limit:
                limit_exceeded_reason = f"Monthly token limit exceeded: {monthly_tokens_used + tokens_to_use}/{monthly_token_limit}"
            elif (daily_cost_used_cents + estimated_new_cost_cents) > daily_cost_limit_cents:
                limit_exceeded_reason = f"Daily cost limit exceeded: ${(daily_cost_used_cents + estimated_new_cost_cents)/100:.2f}/${daily_cost_limit_cents/100:.2f}"
            elif (hourly_tokens_used + tokens_to_use) > hourly_token_limit:
                limit_exceeded_reason = f"Hourly token limit exceeded: {hourly_tokens_used + tokens_to_use}/{hourly_token_limit}"
            elif (minute_requests_used + 1) > minutely_request_limit:
                limit_exceeded_reason = f"Rate limit exceeded: {minute_requests_used + 1}/{minutely_request_limit} requests per minute"
            
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
                is_over_limit=is_over_limit,
                # New short-term limits
                hourly_token_limit=hourly_token_limit,
                hourly_tokens_used=hourly_tokens_used,
                hourly_tokens_remaining=hourly_tokens_remaining,
                minutely_request_limit=minutely_request_limit,
                minutely_requests_used=minute_requests_used,
                minutely_requests_remaining=minutely_requests_remaining,
                limit_exceeded_reason=limit_exceeded_reason
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
            now = datetime.utcnow()
            period_start = now - timedelta(days=days)
            
            # Build base query
            base_match = {
                "user_id": user_id,
                "created_at": {"$gte": period_start},
                "success": True
            }
            
            if api_key_id:
                base_match["api_key_id"] = api_key_id
            
            usage_records = list(mongodb.llm_usage.find(base_match))
            
            # Calculate totals
            total_requests = len(usage_records)
            total_tokens = sum(record["total_tokens"] for record in usage_records)
            total_cost_cents = sum(record["estimated_cost_cents"] for record in usage_records)
            
            # Group by service
            by_service = {}
            by_operation = {}
            
            for record in usage_records:
                # By service
                if record["service_type"] not in by_service:
                    by_service[record["service_type"]] = {
                        'requests': 0, 'tokens': 0, 'cost_cents': 0
                    }
                by_service[record["service_type"]]['requests'] += 1
                by_service[record["service_type"]]['tokens'] += record["total_tokens"]
                by_service[record["service_type"]]['cost_cents'] += record["estimated_cost_cents"]
                
                # By operation
                if record["operation_type"] not in by_operation:
                    by_operation[record["operation_type"]] = {
                        'requests': 0, 'tokens': 0, 'cost_cents': 0
                    }
                by_operation[record["operation_type"]]['requests'] += 1
                by_operation[record["operation_type"]]['tokens'] += record["total_tokens"]
                by_operation[record["operation_type"]]['cost_cents'] += record["estimated_cost_cents"]
            
            # Get recent usage (last 10 records)
            recent_records = list(mongodb.llm_usage.find(base_match).sort("created_at", -1).limit(10))
            
            recent_usage = [
                Usage(
                    user_id=record["user_id"],
                    api_key_id=record["api_key_id"],
                    service_type=record["service_type"],
                    operation_type=record["operation_type"],
                    model_name=record["model_name"],
                    input_tokens=record["input_tokens"],
                    output_tokens=record["output_tokens"],
                    total_tokens=record["total_tokens"],
                    estimated_cost_cents=record["estimated_cost_cents"],
                    prompt_length=record["prompt_length"],
                    response_length=record["response_length"],
                    request_duration_ms=record["request_duration_ms"],
                    operation_context=record["operation_context"],
                    api_slug=record["api_slug"],
                    created_at=record["created_at"],
                    completed_at=record["completed_at"],
                    success=record["success"],
                    error_message=record["error_message"]
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
    

    def calculate_estimated_tokens(self, model_name: str, system_prompt: str, user_prompt: str, response_length: int, success: bool) -> Tuple[int, int]:
        """
        Calculate estimated tokens for a request using sophisticated methods.
        
        Args:
            model_name: The LLM model name
            system_prompt: System/instruction prompt text
            user_prompt: User input text  
            response_length: Length of response text (characters)
            success: Whether the request was successful
            
        Returns:
            Tuple of (estimated_input_tokens, estimated_output_tokens)
        """
        try:
            # Combine input texts
            combined_input = f"{system_prompt}\n{user_prompt}".strip()
            
            # Calculate input tokens
            input_tokens = self._estimate_tokens_for_text(model_name, combined_input, is_input=True)
            
            # Calculate output tokens (0 if failed)
            output_tokens = 0
            if success and response_length > 0:
                # For output estimation, we need to estimate based on response length
                # Since we don't have the actual response text, use length-based estimation
                output_tokens = self._estimate_tokens_from_length(model_name, response_length, is_input=False)
            
            # Ensure minimum values
            input_tokens = max(1, input_tokens)
            output_tokens = max(0, output_tokens)
            
            logger.debug(f"Token estimation for {model_name}: input={input_tokens}, output={output_tokens}")
            return input_tokens, output_tokens
            
        except Exception as e:
            logger.warning(f"Token estimation failed for {model_name}: {e}, falling back to basic estimation")
            return self._fallback_token_estimation(system_prompt, user_prompt, response_length, success)
    
    def _estimate_tokens_for_text(self, model_name: str, text: str, is_input: bool = True) -> int:
        """Estimate tokens for a given text using the best available method"""
        
        if not text or len(text.strip()) == 0:
            return 0
            
        # Method 1: Use tiktoken for OpenAI models (most accurate)
        if model_name in self.token_estimators and TIKTOKEN_AVAILABLE:
            try:
                tokens = len(self.token_estimators[model_name].encode(text))
                logger.debug(f"Used tiktoken for {model_name}: {tokens} tokens")
                return tokens
            except Exception as e:
                logger.warning(f"Tiktoken estimation failed for {model_name}: {e}")
        
        # Method 2: Use model-specific parameters (good accuracy)
        if model_name in self.model_estimation_params:
            params = self.model_estimation_params[model_name]
            
            # Enhanced estimation considering text characteristics
            base_tokens = len(text) / params['chars_per_token']
            
            # Adjust for text complexity
            complexity_multiplier = self._calculate_text_complexity_multiplier(text)
            adjusted_tokens = base_tokens * complexity_multiplier
            
            # Add overhead tokens (for special tokens, formatting, etc.)
            overhead = params['overhead_tokens']
            if is_input:
                overhead += self._calculate_input_overhead(text)
            
            total_tokens = int(adjusted_tokens + overhead)
            logger.debug(f"Used model-specific estimation for {model_name}: {total_tokens} tokens")
            return total_tokens
        
        # Method 3: Fallback to improved general estimation
        return self._general_token_estimation(text)
    
    def _estimate_tokens_from_length(self, model_name: str, char_length: int, is_input: bool = True) -> int:
        """Estimate tokens from character length when we don't have the actual text"""
        
        if char_length <= 0:
            return 0
            
        # Use model-specific parameters if available
        if model_name in self.model_estimation_params:
            params = self.model_estimation_params[model_name]
            base_tokens = char_length / params['chars_per_token']
            
            # Apply a moderate complexity multiplier for generated text
            complexity_multiplier = 1.1 if is_input else 1.05  # Generated text is often simpler
            adjusted_tokens = base_tokens * complexity_multiplier
            
            # Add minimal overhead for output
            overhead = params['overhead_tokens'] // 2 if not is_input else params['overhead_tokens']
            
            return int(adjusted_tokens + overhead)
        
        # Fallback: use general estimation
        return max(1, char_length // 4)
    
    def _calculate_text_complexity_multiplier(self, text: str) -> float:
        """Calculate a multiplier based on text complexity characteristics"""
        
        if not text:
            return 1.0
            
        base_multiplier = 1.0
        
        # Check for code patterns (more tokens per character)
        code_patterns = [
            r'def\s+\w+\(', r'class\s+\w+', r'import\s+\w+', r'from\s+\w+\s+import',
            r'function\s+\w+\(', r'const\s+\w+\s*=', r'let\s+\w+\s*=', r'var\s+\w+\s*=',
            r'\{\s*\w+:', r'\[\s*\w+', r'=>', r'&&', r'\|\|'
        ]
        
        code_score = sum(1 for pattern in code_patterns if re.search(pattern, text))
        if code_score > 0:
            base_multiplier += min(0.3, code_score * 0.1)  # Up to 30% increase for code
        
        # Check for JSON/structured data
        if '{' in text and '}' in text and '"' in text:
            base_multiplier += 0.15
        
        # Check for special characters and symbols
        special_char_ratio = len(re.findall(r'[^\w\s]', text)) / len(text) if text else 0
        if special_char_ratio > 0.1:  # More than 10% special characters
            base_multiplier += min(0.2, special_char_ratio)
        
        # Check for repeated patterns (might be more efficient)
        if len(set(text.split())) / len(text.split()) if text.split() else 1 < 0.5:
            base_multiplier -= 0.1  # Slight reduction for repetitive text
        
        return max(0.8, min(1.5, base_multiplier))  # Clamp between 0.8 and 1.5
    
    def _calculate_input_overhead(self, text: str) -> int:
        """Calculate additional overhead tokens for input text characteristics"""
        
        overhead = 0
        
        # Add overhead for system prompts (usually have special formatting)
        if any(keyword in text.lower() for keyword in ['system:', 'instruction:', 'you are', 'your task']):
            overhead += 5
        
        # Add overhead for structured prompts
        if text.count('\n') > 3:  # Multi-line prompts
            overhead += 2
            
        # Add overhead for questions
        if '?' in text:
            overhead += 1
            
        return overhead
    
    def _general_token_estimation(self, text: str) -> int:
        """Improved general token estimation when model-specific data isn't available"""
        
        if not text:
            return 0
            
        # More sophisticated character-to-token ratio
        char_count = len(text)
        word_count = len(text.split())
        
        # Base estimation: average of character-based and word-based
        char_based = char_count / 4.0  # Traditional approximation
        word_based = word_count * 1.3  # Most words are 1-2 tokens
        
        # Use the higher estimate for safety
        base_estimate = max(char_based, word_based)
        
        # Apply complexity multiplier
        complexity = self._calculate_text_complexity_multiplier(text)
        adjusted_estimate = base_estimate * complexity
        
        return max(1, int(adjusted_estimate))
    
    def _fallback_token_estimation(self, system_prompt: str, user_prompt: str, response_length: int, success: bool) -> Tuple[int, int]:
        """Fallback estimation method when sophisticated methods fail"""
        
        # Improved fallback with better ratios
        combined_input = f"{system_prompt}\n{user_prompt}".strip()
        
        # Use slightly more conservative estimates
        input_tokens = max(1, len(combined_input) // 3.5)  # Slightly more generous than original
        output_tokens = max(0, response_length // 3.5) if success else 0
        
        return int(input_tokens), int(output_tokens)
    
    @functools.lru_cache(maxsize=1000)
    def _cached_token_estimation(self, model_name: str, text_hash: str, text_length: int, is_input: bool) -> int:
        """Cached token estimation for frequently used texts"""
        # This method signature allows caching while the actual logic is in the non-cached method
        # The hash ensures we're not storing sensitive data in cache
        return self._estimate_tokens_from_length(model_name, text_length, is_input)
    
    def estimate_tokens_for_actual_text(self, model_name: str, actual_text: str) -> int:
        """
        Estimate tokens for actual response text (when available).
        This provides more accurate estimates than length-based estimation.
        """
        if not actual_text:
            return 0
            
        return self._estimate_tokens_for_text(model_name, actual_text, is_input=False)
    
    def batch_estimate_tokens(self, requests: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
        """
        Batch estimate tokens for multiple requests for better performance.
        
        Args:
            requests: List of dicts with keys: model_name, system_prompt, user_prompt, response_length, success
            
        Returns:
            List of (input_tokens, output_tokens) tuples
        """
        results = []
        
        for req in requests:
            try:
                input_tokens, output_tokens = self.calculate_estimated_tokens(
                    model_name=req.get('model_name', 'gpt-4'),
                    system_prompt=req.get('system_prompt', ''),
                    user_prompt=req.get('user_prompt', ''),
                    response_length=req.get('response_length', 0),
                    success=req.get('success', True)
                )
                results.append((input_tokens, output_tokens))
            except Exception as e:
                logger.warning(f"Batch token estimation failed for request: {e}")
                results.append((1, 0))  # Minimal fallback
                
        return results
    
    def get_token_estimation_stats(self) -> Dict[str, Any]:
        """Get statistics about token estimation capabilities"""
        return {
            "tiktoken_available": TIKTOKEN_AVAILABLE,
            "transformers_available": TRANSFORMERS_AVAILABLE,
            "supported_models": list(self.model_estimation_params.keys()),
            "tiktoken_models": list(self.token_estimators.keys()) if hasattr(self, 'token_estimators') else [],
            "cache_info": self._cached_token_estimation.cache_info() if hasattr(self._cached_token_estimation, 'cache_info') else None
        }



    def _calculate_cost_cents(self, model_name: str, input_tokens: int, output_tokens: int) -> int:
        """Calculate estimated cost in cents for token usage."""
        
        # Get pricing for model
        if model_name not in self.COST_PER_TOKEN:
            logger.warning(f"Unknown model {model_name}, using default pricing")
            # Default to GPT-3.5 pricing
            pricing = self.COST_PER_TOKEN['gpt-5-mini']
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