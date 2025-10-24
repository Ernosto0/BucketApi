import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
from .mongodb import mongodb
from app.services.usage_service import usage_service

logger = logging.getLogger(__name__)

@dataclass
class APIUsageStats:
    """Real usage statistics for an API based on actual executions."""
    api_slug: str
    user_id: str
    total_executions: int
    successful_executions: int
    failed_executions: int
    
    # Token usage statistics
    avg_input_tokens: float
    avg_output_tokens: float
    avg_total_tokens: float
    max_tokens_used: int
    min_tokens_used: int
    
    # Cost statistics
    avg_cost_per_call_cents: float
    total_cost_cents: float
    max_cost_per_call_cents: float
    
    # Model usage
    primary_model_used: Optional[str]
    models_used: List[str]
    
    # Time-based data
    first_execution: datetime
    last_execution: datetime
    last_updated: datetime

class APIUsageAggregator:
    """Service to aggregate real usage statistics from executed APIs."""
    
    def __init__(self):
        logger.info("APIUsageAggregator initialized")
    
    async def get_api_usage_stats(
        self, 
        api_slug: str, 
        user_id: str, 
        days_back: int = 30
    ) -> Optional[APIUsageStats]:
        """
        Get real usage statistics for an API based on actual executions.
        
        Args:
            api_slug: The API slug to analyze
            user_id: The user ID who owns the API
            days_back: Number of days to look back for usage data
            
        Returns:
            APIUsageStats if usage data exists, None otherwise
        """
        try:
            # Calculate date range
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days_back)
            
            # Query usage data from MongoDB
            usage_data = list(mongodb.llm_usage.find({
                "api_slug": api_slug,
                "user_id": user_id,
                "created_at": {"$gte": start_date, "$lte": end_date}
            }))
            
            if not usage_data:
                logger.debug(f"No usage data found for API {api_slug}")
                return None
            
            # Aggregate statistics
            stats = self._calculate_usage_statistics(usage_data, api_slug, user_id)
            
            logger.info(f"Aggregated usage stats for {api_slug}: "
                       f"{stats.total_executions} executions, "
                       f"avg {stats.avg_total_tokens:.1f} tokens, "
                       f"avg ${stats.avg_cost_per_call_cents/100:.4f} per call")
            
            return stats
            
        except Exception as e:
            logger.error(f"Error aggregating usage stats for {api_slug}: {e}")
            return None
    
    def _calculate_usage_statistics(
        self, 
        usage_data: List[Dict], 
        api_slug: str, 
        user_id: str
    ) -> APIUsageStats:
        """Calculate aggregated statistics from raw usage data."""
        
        total_executions = len(usage_data)
        successful_executions = sum(1 for record in usage_data if record.get('success', False))
        failed_executions = total_executions - successful_executions
        
        # Filter successful executions for token/cost calculations
        successful_records = [r for r in usage_data if r.get('success', False)]
        
        if successful_records:
            # Token statistics
            input_tokens = [r.get('input_tokens', 0) for r in successful_records]
            output_tokens = [r.get('output_tokens', 0) for r in successful_records]
            total_tokens = [r.get('total_tokens', 0) for r in successful_records]
            
            avg_input_tokens = sum(input_tokens) / len(input_tokens)
            avg_output_tokens = sum(output_tokens) / len(output_tokens)
            avg_total_tokens = sum(total_tokens) / len(total_tokens)
            max_tokens_used = max(total_tokens) if total_tokens else 0
            min_tokens_used = min(total_tokens) if total_tokens else 0
            
            # Cost statistics
            costs = [r.get('estimated_cost_cents', 0) for r in successful_records]
            avg_cost_per_call_cents = sum(costs) / len(costs)
            total_cost_cents = sum(costs)
            max_cost_per_call_cents = max(costs) if costs else 0
            
            # Model usage
            models_used = list(set(r.get('model_name', 'unknown') for r in successful_records))
            # Determine primary model (most frequently used)
            model_counts = {}
            for record in successful_records:
                model = record.get('model_name', 'unknown')
                model_counts[model] = model_counts.get(model, 0) + 1
            primary_model_used = max(model_counts.items(), key=lambda x: x[1])[0] if model_counts else None
            
        else:
            # No successful executions
            avg_input_tokens = avg_output_tokens = avg_total_tokens = 0.0
            max_tokens_used = min_tokens_used = 0
            avg_cost_per_call_cents = total_cost_cents = max_cost_per_call_cents = 0.0
            models_used = []
            primary_model_used = None
        
        # Time-based data
        timestamps = [r.get('created_at') for r in usage_data if r.get('created_at')]
        first_execution = min(timestamps) if timestamps else datetime.utcnow()
        last_execution = max(timestamps) if timestamps else datetime.utcnow()
        
        return APIUsageStats(
            api_slug=api_slug,
            user_id=user_id,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
            avg_input_tokens=avg_input_tokens,
            avg_output_tokens=avg_output_tokens,
            avg_total_tokens=avg_total_tokens,
            max_tokens_used=max_tokens_used,
            min_tokens_used=min_tokens_used,
            avg_cost_per_call_cents=avg_cost_per_call_cents,
            total_cost_cents=total_cost_cents,
            max_cost_per_call_cents=max_cost_per_call_cents,
            primary_model_used=primary_model_used,
            models_used=models_used,
            first_execution=first_execution,
            last_execution=last_execution,
            last_updated=datetime.utcnow()
        )
    
    async def update_api_pricing_with_real_usage(
        self, 
        api_slug: str, 
        user_id: str
    ) -> bool:
        """
        Update API pricing metadata with real usage statistics.
        
        Args:
            api_slug: The API slug to update
            user_id: The user ID who owns the API
            
        Returns:
            True if pricing was updated, False otherwise
        """
        try:
            # Get real usage statistics
            usage_stats = await self.get_api_usage_stats(api_slug, user_id)
            
            if not usage_stats or usage_stats.successful_executions == 0:
                logger.debug(f"No usage data available to update pricing for {api_slug}")
                return False
            
            # Update API metadata with real usage data (ensure integers where needed)
            update_data = {
                "real_avg_tokens_per_call": int(round(usage_stats.avg_total_tokens)),
                "real_avg_cost_per_call_cents": int(round(usage_stats.avg_cost_per_call_cents)),
                "real_model_used": usage_stats.primary_model_used,
                "total_executions": usage_stats.total_executions,
                "successful_executions": usage_stats.successful_executions,
                "usage_last_updated": usage_stats.last_updated,
                "has_real_usage_data": True
            }
            
            # Update in MongoDB
            result = mongodb.api_metadata.update_one(
                {"api_slug": api_slug, "user_id": user_id},
                {"$set": update_data}
            )
            
            if result.modified_count > 0:
                logger.info(f"Updated pricing for {api_slug} with real usage: "
                           f"avg {usage_stats.avg_total_tokens:.1f} tokens, "
                           f"${usage_stats.avg_cost_per_call_cents/100:.4f} per call")
                return True
            else:
                logger.warning(f"No API metadata found to update for {api_slug}")
                return False
                
        except Exception as e:
            logger.error(f"Error updating API pricing with real usage for {api_slug}: {e}")
            return False

# Global instance
api_usage_aggregator = APIUsageAggregator()
