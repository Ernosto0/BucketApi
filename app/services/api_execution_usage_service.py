import uuid
import json
import logging
import sys
import psutil
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
# MongoDB operations handled through mongodb service
from ..models import (
    APIExecutionUsage, APIExecutionStatsResponse, APIExecutionLimitsResponse, 
    CreateAPIExecutionUsageRequest, APIExecutionUsageRequest
)
from .mongodb import mongodb
from .sandbox_service import sandbox_service
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class APIExecutionUsageService:
    def __init__(self):
        # Default limits (can be made configurable per user/plan)
        self.DEFAULT_DAILY_EXECUTION_LIMIT = 1000  # 1000 API calls per day
        self.DEFAULT_MONTHLY_EXECUTION_LIMIT = 10000  # 10k API calls per month
        self.DEFAULT_DAILY_DATA_LIMIT_BYTES = 100 * 1024 * 1024  # 100MB per day
        
        # Resource limits
        self.DEFAULT_TIMEOUT_SECONDS = 30
        self.DEFAULT_MEMORY_LIMIT_MB = 512
        self.DEFAULT_CPU_LIMIT_SECONDS = 30
        
        logger.info("APIExecutionUsageService initialized")
    
    async def record_execution_usage(
        self,
        user_id: str,
        api_key_id: Optional[str],
        api_slug: str,
        execution_time_ms: int,
        input_data_size: int = 0,
        output_data_size: int = 0,
        success: bool = True,
        error_message: Optional[str] = None
    ) -> APIExecutionUsage:
        """Record a new API execution usage entry."""
        
        try:
            # Create usage record
            usage_id = str(uuid.uuid4())
            
            # Create usage record in MongoDB
            db_usage = {
                "_id": usage_id,
                "user_id": user_id,
                "api_key_id": api_key_id,
                "api_slug": api_slug,
                "execution_time_ms": execution_time_ms,
                "input_data_size": input_data_size,
                "output_data_size": output_data_size,
                "success": success,
                "error_message": error_message,
                "created_at": datetime.utcnow()
            }
            
            mongodb.api_execution_usage.insert_one(db_usage)
                
            # Convert to Pydantic model
            usage = APIExecutionUsage(
                id=db_usage["_id"],
                user_id=db_usage["user_id"],
                api_key_id=db_usage["api_key_id"],
                api_slug=db_usage["api_slug"],
                execution_time_ms=db_usage["execution_time_ms"],
                input_data_size=db_usage["input_data_size"],
                output_data_size=db_usage["output_data_size"],
                success=db_usage["success"],
                error_message=db_usage["error_message"],
                created_at=db_usage["created_at"]
            )
                
            total_data = input_data_size + output_data_size
            logger.info(f"Recorded API execution for user {user_id}: {api_slug}, {execution_time_ms}ms, {total_data} bytes")
            return usage
                
        except Exception as e:
            logger.error(f"Failed to record API execution usage: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to record API execution usage: {str(e)}")
    
    async def check_execution_limits(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        data_size_to_use: int = 0
    ) -> APIExecutionLimitsResponse:
        """Check if user is within API execution limits."""
        
        try:
            now = datetime.utcnow()
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
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
                    "total_executions": {"$sum": 1},
                    "total_data": {"$sum": {"$add": ["$input_data_size", "$output_data_size"]}}
                }}
            ]
            
            daily_result = list(mongodb.api_execution_usage.aggregate(daily_pipeline))
            daily_executions_used = daily_result[0]["total_executions"] if daily_result else 0
            daily_data_used_bytes = daily_result[0]["total_data"] if daily_result else 0
                
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
                    "total_executions": {"$sum": 1}
                }}
            ]
            
            monthly_result = list(mongodb.api_execution_usage.aggregate(monthly_pipeline))
            monthly_executions_used = monthly_result[0]["total_executions"] if monthly_result else 0
                
            # Calculate limits and remaining usage
            daily_execution_limit = self.DEFAULT_DAILY_EXECUTION_LIMIT
            monthly_execution_limit = self.DEFAULT_MONTHLY_EXECUTION_LIMIT
            daily_data_limit_bytes = self.DEFAULT_DAILY_DATA_LIMIT_BYTES
            
            daily_executions_remaining = max(0, daily_execution_limit - daily_executions_used)
            monthly_executions_remaining = max(0, monthly_execution_limit - monthly_executions_used)
            daily_data_remaining_bytes = max(0, daily_data_limit_bytes - daily_data_used_bytes)
            
            # Check if adding the new execution would exceed limits
            is_over_execution_limit = (
                (daily_executions_used + 1) > daily_execution_limit or
                (monthly_executions_used + 1) > monthly_execution_limit
            )
            
            is_over_data_limit = (
                (daily_data_used_bytes + data_size_to_use) > daily_data_limit_bytes
            )
            
            # Next reset time (tomorrow at midnight)
            limit_reset_time = today_start + timedelta(days=1)
            
            return APIExecutionLimitsResponse(
                user_id=user_id,
                api_key_id=api_key_id,
                daily_execution_limit=daily_execution_limit,
                daily_executions_used=daily_executions_used,
                daily_executions_remaining=daily_executions_remaining,
                monthly_execution_limit=monthly_execution_limit,
                monthly_executions_used=monthly_executions_used,
                monthly_executions_remaining=monthly_executions_remaining,
                daily_data_limit_bytes=daily_data_limit_bytes,
                daily_data_used_bytes=daily_data_used_bytes,
                daily_data_remaining_bytes=daily_data_remaining_bytes,
                limit_reset_time=limit_reset_time,
                is_over_execution_limit=is_over_execution_limit,
                is_over_data_limit=is_over_data_limit
            )
                
        except Exception as e:
            logger.error(f"Failed to check execution limits: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to check execution limits: {str(e)}")
    
    async def get_execution_stats(
        self,
        user_id: str,
        api_key_id: Optional[str] = None,
        days: int = 30
    ) -> APIExecutionStatsResponse:
        """Get API execution statistics for a user."""
        
        try:
            now = datetime.utcnow()
            period_start = now - timedelta(days=days)
            
            # Build base query
            base_match = {
                "user_id": user_id,
                "created_at": {"$gte": period_start}
            }
            
            if api_key_id:
                base_match["api_key_id"] = api_key_id
            
            execution_records = list(mongodb.api_execution_usage.find(base_match))
                
            # Calculate totals
            total_executions = len(execution_records)
            successful_executions = sum(1 for record in execution_records if record["success"])
            failed_executions = total_executions - successful_executions
            total_execution_time_ms = sum(record["execution_time_ms"] for record in execution_records)
            average_execution_time_ms = total_execution_time_ms / total_executions if total_executions > 0 else 0
            total_data_processed_bytes = sum(
                record["input_data_size"] + record["output_data_size"] for record in execution_records
            )
                
            # Group by API
            by_api = {}
            for record in execution_records:
                api_slug = record["api_slug"]
                if api_slug not in by_api:
                    by_api[api_slug] = {
                        'executions': 0, 'successful': 0, 'failed': 0, 
                        'total_time_ms': 0, 'data_bytes': 0
                    }
                by_api[api_slug]['executions'] += 1
                if record["success"]:
                    by_api[api_slug]['successful'] += 1
                else:
                    by_api[api_slug]['failed'] += 1
                by_api[api_slug]['total_time_ms'] += record["execution_time_ms"]
                by_api[api_slug]['data_bytes'] += record["input_data_size"] + record["output_data_size"]
                
            # Get recent executions (last 10 records)
            recent_records = list(mongodb.api_execution_usage.find(base_match).sort("created_at", -1).limit(10))
            
            recent_executions = [
                APIExecutionUsage(
                    id=record["_id"],
                    user_id=record["user_id"],
                    api_key_id=record["api_key_id"],
                    api_slug=record["api_slug"],
                    execution_time_ms=record["execution_time_ms"],
                    input_data_size=record["input_data_size"],
                    output_data_size=record["output_data_size"],
                    success=record["success"],
                    error_message=record.get("error_message"),
                    created_at=record["created_at"]
                )
                for record in recent_records
            ]
            
            return APIExecutionStatsResponse(
                user_id=user_id,
                api_key_id=api_key_id,
                total_executions=total_executions,
                successful_executions=successful_executions,
                failed_executions=failed_executions,
                total_execution_time_ms=total_execution_time_ms,
                average_execution_time_ms=average_execution_time_ms,
                total_data_processed_bytes=total_data_processed_bytes,
                by_api=by_api,
                recent_executions=recent_executions,
                period_start=period_start,
                period_end=now
            )
                
        except Exception as e:
            logger.error(f"Failed to get execution stats: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Failed to get execution stats: {str(e)}")
    
    async def execute_api_with_limits(
        self,
        code: str,
        input_data: Dict[str, Any],
        file_bytes: Optional[bytes] = None,
        timeout_seconds: Optional[int] = None,
        memory_limit_mb: Optional[int] = None,
        cpu_limit: Optional[int] = None,
        is_test_execution: bool = False
    ) -> Tuple[Any, float, bool, Optional[str]]:
        """
        Execute an API with resource limits and tracking.
        Returns: (result, execution_time, success, error_message)
        """
        start_time = datetime.now()
        success = False
        error_message = None
        result = None
        
        try:
            # Execute in sandbox with limits
            result = await sandbox_service.execute_api_sandboxed(
                code=code,
                input_data=input_data,
                file_bytes=file_bytes,
                timeout_seconds=timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS,
                memory_limit_mb=memory_limit_mb or self.DEFAULT_MEMORY_LIMIT_MB,
                cpu_limit=cpu_limit or self.DEFAULT_CPU_LIMIT_SECONDS,
                is_test_execution=is_test_execution
            )
            success = True
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"API execution failed: {error_message}")
        
        execution_time = (datetime.now() - start_time).total_seconds() * 1000  # Convert to milliseconds
        
        return result, execution_time, success, error_message

    def _calculate_data_size(self, data: Any) -> int:
        """Calculate the size of data in bytes."""
        if data is None:
            return 0
        
        try:
            if isinstance(data, str):
                return len(data.encode('utf-8'))
            elif isinstance(data, (dict, list)):
                return len(json.dumps(data).encode('utf-8'))
            elif isinstance(data, bytes):
                return len(data)
            else:
                return len(str(data).encode('utf-8'))
        except Exception:
            return sys.getsizeof(data)

# Global instance
api_execution_usage_service = APIExecutionUsageService() 