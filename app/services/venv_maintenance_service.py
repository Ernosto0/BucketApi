"""
Maintenance service for the venv system.
Handles periodic cleanup, monitoring, and health checks.
"""
import asyncio
import logging
import schedule
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List
import json

from .venv_management_api import venv_management_api

logger = logging.getLogger(__name__)

class VenvMaintenanceService:
    """Handles maintenance tasks for the venv system."""
    
    def __init__(self):
        self.venv_api = venv_management_api
        self.is_running = False
        self.maintenance_thread = None
        
        # Maintenance configuration
        self.config = {
            "cleanup_interval_hours": 24,  # Daily cleanup
            "health_check_interval_minutes": 30,  # Health check every 30 minutes
            "max_venv_size_gb": 3.0,  # Auto-reset if exceeds 3 GB
            "max_failure_rate": 0.2,  # Alert if failure rate > 20%
            "log_retention_days": 7,  # Keep logs for 7 days
            "auto_cleanup_enabled": True,
            "health_monitoring_enabled": True
        }
        
        # Maintenance history
        self.maintenance_history = []
        self.last_cleanup = None
        self.last_health_check = None
        
        # Setup scheduled tasks
        self._setup_scheduled_tasks()
    
    def _setup_scheduled_tasks(self):
        """Setup scheduled maintenance tasks."""
        # Daily cleanup at 3 AM
        schedule.every().day.at("03:00").do(self._scheduled_cleanup)
        
        # Health check every 30 minutes
        schedule.every(30).minutes.do(self._scheduled_health_check)
        
        # Weekly deep cleanup on Sunday at 2 AM
        schedule.every().sunday.at("02:00").do(self._scheduled_deep_cleanup)
    
    def start_maintenance(self):
        """Start the maintenance service."""
        if self.is_running:
            logger.warning("Maintenance service is already running")
            return
        
        self.is_running = True
        self.maintenance_thread = threading.Thread(target=self._maintenance_loop, daemon=True)
        self.maintenance_thread.start()
        
        logger.info("Venv maintenance service started")
    
    def stop_maintenance(self):
        """Stop the maintenance service."""
        self.is_running = False
        if self.maintenance_thread:
            self.maintenance_thread.join(timeout=5)
        
        logger.info("Venv maintenance service stopped")
    
    def _maintenance_loop(self):
        """Main maintenance loop."""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")
                time.sleep(60)
    
    def _scheduled_cleanup(self):
        """Scheduled cleanup task."""
        if not self.config["auto_cleanup_enabled"]:
            return
        
        try:
            logger.info("Starting scheduled cleanup...")
            
            # Run cleanup
            cleanup_result = asyncio.run(self.venv_api.cleanup_system())
            
            # Log result
            self._log_maintenance_event("scheduled_cleanup", cleanup_result)
            self.last_cleanup = datetime.now()
            
            logger.info(f"Scheduled cleanup completed: {cleanup_result.get('success', False)}")
            
        except Exception as e:
            logger.error(f"Error in scheduled cleanup: {e}")
            self._log_maintenance_event("scheduled_cleanup", {
                "success": False,
                "error": str(e)
            })
    
    def _scheduled_health_check(self):
        """Scheduled health check task."""
        if not self.config["health_monitoring_enabled"]:
            return
        
        try:
            logger.debug("Running scheduled health check...")
            
            # Run health check
            health_result = asyncio.run(self.venv_api.health_check())
            
            # Log result
            self._log_maintenance_event("health_check", health_result)
            self.last_health_check = datetime.now()
            
            # Check for issues
            health_status = health_result.get("health_check", {})
            overall_health = health_status.get("overall_health", "unknown")
            
            if overall_health in ["unhealthy", "critical"]:
                logger.warning(f"Health check found issues: {health_status.get('issues', [])}")
                
                # Auto-recovery for critical issues
                if overall_health == "critical":
                    self._attempt_auto_recovery(health_status)
            
        except Exception as e:
            logger.error(f"Error in scheduled health check: {e}")
            self._log_maintenance_event("health_check", {
                "success": False,
                "error": str(e)
            })
    
    def _scheduled_deep_cleanup(self):
        """Scheduled deep cleanup task (weekly)."""
        try:
            logger.info("Starting scheduled deep cleanup...")
            
            # Reset API environment completely
            reset_result = asyncio.run(self.venv_api.reset_api_environment())
            
            # Reset statistics
            self.venv_api.venv_execution_service.reset_execution_stats()
            
            # Clean up maintenance history (keep only last 50 entries)
            if len(self.maintenance_history) > 50:
                self.maintenance_history = self.maintenance_history[-50:]
            
            # Log result
            self._log_maintenance_event("deep_cleanup", reset_result)
            
            logger.info(f"Deep cleanup completed: {reset_result.get('success', False)}")
            
        except Exception as e:
            logger.error(f"Error in deep cleanup: {e}")
            self._log_maintenance_event("deep_cleanup", {
                "success": False,
                "error": str(e)
            })
    
    def _attempt_auto_recovery(self, health_status: Dict):
        """Attempt automatic recovery from critical issues."""
        try:
            logger.warning("Attempting auto-recovery from critical health issues...")
            
            issues = health_status.get("issues", [])
            
            for issue in issues:
                if "api_venv size is critical" in issue:
                    # Reset API environment if size is critical
                    logger.info("Resetting API environment due to critical size")
                    reset_result = asyncio.run(self.venv_api.reset_api_environment())
                    self._log_maintenance_event("auto_recovery_reset", reset_result)
                
                elif "execution test failed" in issue:
                    # Try toggling execution mode
                    logger.info("Toggling execution mode due to test failure")
                    toggle_result = self.venv_api.toggle_venv_execution(False)
                    time.sleep(5)
                    toggle_result = self.venv_api.toggle_venv_execution(True)
                    self._log_maintenance_event("auto_recovery_toggle", toggle_result)
                
                elif "failure rate" in issue:
                    # Reset execution statistics
                    logger.info("Resetting execution statistics due to high failure rate")
                    self.venv_api.venv_execution_service.reset_execution_stats()
                    self._log_maintenance_event("auto_recovery_stats_reset", {"success": True})
            
        except Exception as e:
            logger.error(f"Error in auto-recovery: {e}")
            self._log_maintenance_event("auto_recovery", {
                "success": False,
                "error": str(e)
            })
    
    def _log_maintenance_event(self, event_type: str, result: Dict):
        """Log a maintenance event."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "event_type": event_type,
            "result": result,
            "success": result.get("success", False)
        }
        
        self.maintenance_history.append(event)
        
        # Keep only last 100 events
        if len(self.maintenance_history) > 100:
            self.maintenance_history = self.maintenance_history[-100:]
    
    async def manual_cleanup(self) -> Dict:
        """Manually trigger cleanup."""
        try:
            logger.info("Starting manual cleanup...")
            
            cleanup_result = await self.venv_api.cleanup_system()
            self._log_maintenance_event("manual_cleanup", cleanup_result)
            
            return cleanup_result
            
        except Exception as e:
            logger.error(f"Error in manual cleanup: {e}")
            error_result = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self._log_maintenance_event("manual_cleanup", error_result)
            return error_result
    
    async def manual_health_check(self) -> Dict:
        """Manually trigger health check."""
        try:
            logger.info("Starting manual health check...")
            
            health_result = await self.venv_api.health_check()
            self._log_maintenance_event("manual_health_check", health_result)
            
            return health_result
            
        except Exception as e:
            logger.error(f"Error in manual health check: {e}")
            error_result = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self._log_maintenance_event("manual_health_check", error_result)
            return error_result
    
    def get_maintenance_status(self) -> Dict:
        """Get current maintenance status."""
        return {
            "maintenance_service": {
                "is_running": self.is_running,
                "config": self.config,
                "last_cleanup": self.last_cleanup.isoformat() if self.last_cleanup else None,
                "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
                "scheduled_tasks": {
                    "next_cleanup": self._get_next_scheduled_time("03:00"),
                    "next_health_check": self._get_next_scheduled_time("30min"),
                    "next_deep_cleanup": self._get_next_scheduled_time("sunday_02:00")
                }
            },
            "maintenance_history": self.maintenance_history[-10:],  # Last 10 events
            "system_status": asyncio.run(self.venv_api.get_system_status()),
            "timestamp": datetime.now().isoformat()
        }
    
    def _get_next_scheduled_time(self, schedule_type: str) -> str:
        """Get next scheduled time for a task type."""
        # This is a simplified implementation
        # In a real implementation, you'd calculate based on the schedule
        now = datetime.now()
        
        if schedule_type == "03:00":
            # Next 3 AM
            next_run = now.replace(hour=3, minute=0, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)
            return next_run.isoformat()
        
        elif schedule_type == "30min":
            # Next 30-minute interval
            next_run = now + timedelta(minutes=30)
            return next_run.isoformat()
        
        elif schedule_type == "sunday_02:00":
            # Next Sunday at 2 AM
            days_ahead = 6 - now.weekday()  # Sunday is 6
            if days_ahead <= 0:
                days_ahead += 7
            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=2, minute=0, second=0, microsecond=0)
            return next_run.isoformat()
        
        return "unknown"
    
    def update_config(self, new_config: Dict) -> Dict:
        """Update maintenance configuration."""
        try:
            # Validate and update config
            for key, value in new_config.items():
                if key in self.config:
                    self.config[key] = value
            
            logger.info(f"Maintenance config updated: {new_config}")
            
            return {
                "success": True,
                "updated_config": self.config,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error updating maintenance config: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_maintenance_history(self, limit: int = 50) -> Dict:
        """Get maintenance history."""
        return {
            "maintenance_history": self.maintenance_history[-limit:],
            "total_events": len(self.maintenance_history),
            "timestamp": datetime.now().isoformat()
        }

# Initialize the maintenance service
venv_maintenance_service = VenvMaintenanceService()

# Auto-start maintenance service
try:
    venv_maintenance_service.start_maintenance()
except Exception as e:
    logger.error(f"Failed to start maintenance service: {e}")
