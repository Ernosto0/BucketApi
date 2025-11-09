"""
API endpoints for managing the venv system.
Provides endpoints for monitoring, testing, and maintaining the 2-venv architecture.
"""
import logging
from typing import Dict, List, Optional
from datetime import datetime

from .venv_manager import venv_manager
from .dependency_detector import dependency_detector
from .package_installer import package_installer
from .venv_execution_service import venv_execution_service
from .sandbox_service import sandbox_service

logger = logging.getLogger(__name__)

class VenvManagementAPI:
    """API for managing the venv system."""
    
    def __init__(self):
        self.venv_manager = venv_manager
        self.dependency_detector = dependency_detector
        self.package_installer = package_installer
        self.venv_execution_service = venv_execution_service
        self.sandbox_service = sandbox_service
    
    async def get_system_status(self) -> Dict:
        """Get comprehensive system status."""
        try:
            return {
                "success": True,
                "system_status": {
                    "venv_info": self.venv_manager.get_venv_info(),
                    "execution_stats": self.venv_execution_service.get_execution_stats(),
                    "installation_status": self.package_installer.get_installation_status(),
                    "sandbox_info": self.sandbox_service.get_execution_info(),
                    "available_packages": self.package_installer.get_available_packages()
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def analyze_code_dependencies(self, code: str) -> Dict:
        """Analyze code dependencies without installing."""
        try:
            analysis = self.dependency_detector.analyze_code_dependencies(code)
            
            return {
                "success": True,
                "analysis": analysis,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error analyzing dependencies: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def install_package(self, package_name: str) -> Dict:
        """Install a specific package."""
        try:
            result = await self.package_installer.test_package_installation(package_name)
            return result
        except Exception as e:
            logger.error(f"Error installing package {package_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": package_name,
                "timestamp": datetime.now().isoformat()
            }
    
    async def prepare_environment(self, code: str) -> Dict:
        """Prepare execution environment for code."""
        try:
            result = await self.package_installer.prepare_execution_environment(code)
            return result
        except Exception as e:
            logger.error(f"Error preparing environment: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def test_execution(self, code: str = None, input_data: Dict = None) -> Dict:
        """Test the execution system."""
        try:
            if code:
                # Test with provided code
                result = await self.venv_execution_service.execute_api_in_venv(
                    code=code,
                    input_data=input_data or {"test": True},
                    timeout_seconds=30,
                    auto_install_dependencies=True
                )
                
                return {
                    "success": True,
                    "test_type": "custom_code",
                    "result": result,
                    "timestamp": datetime.now().isoformat()
                }
            else:
                # Test with built-in test
                result = await self.sandbox_service.test_execution_system()
                return result
                
        except Exception as e:
            logger.error(f"Error testing execution: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def reset_api_environment(self) -> Dict:
        """Reset the API environment."""
        try:
            result = self.package_installer.reset_api_environment()
            return result
        except Exception as e:
            logger.error(f"Error resetting environment: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def cleanup_system(self) -> Dict:
        """Perform system cleanup."""
        try:
            cleanup_result = await self.venv_execution_service.cleanup_and_maintenance()
            return cleanup_result
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def toggle_venv_execution(self, enabled: bool) -> Dict:
        """Toggle venv execution on/off."""
        try:
            self.sandbox_service.toggle_venv_execution(enabled)
            
            return {
                "success": True,
                "venv_execution_enabled": enabled,
                "message": f"Venv execution {'enabled' if enabled else 'disabled'}",
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error toggling venv execution: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def get_package_info(self, package_name: str) -> Dict:
        """Get information about a specific package."""
        try:
            package_info = self.dependency_detector.get_package_info(package_name)
            
            # Check if already installed
            installed_packages = self.venv_manager.get_installed_packages()
            is_installed = package_name in installed_packages
            
            return {
                "success": True,
                "package_info": package_info,
                "is_installed": is_installed,
                "installation_details": installed_packages.get(package_name) if is_installed else None,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting package info for {package_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": package_name,
                "timestamp": datetime.now().isoformat()
            }
    
    def get_execution_statistics(self) -> Dict:
        """Get detailed execution statistics."""
        try:
            return {
                "success": True,
                "statistics": {
                    "execution_stats": self.venv_execution_service._execution_stats,
                    "installation_stats": self.package_installer._stats,
                    "venv_info": self.venv_manager.get_venv_info(),
                    "system_info": self.sandbox_service.get_execution_info()
                },
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            logger.error(f"Error getting statistics: {e}")
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    async def health_check(self) -> Dict:
        """Comprehensive health check of the venv system."""
        try:
            health_status = {
                "overall_health": "healthy",
                "issues": [],
                "warnings": []
            }
            
            # Check venv existence
            venv_info = self.venv_manager.get_venv_info()
            if not venv_info.get("main_venv", {}).get("exists"):
                health_status["issues"].append("main_venv does not exist")
                health_status["overall_health"] = "unhealthy"
            
            if not venv_info.get("api_venv", {}).get("exists"):
                health_status["issues"].append("api_venv does not exist")
                health_status["overall_health"] = "unhealthy"
            
            # Check venv size
            api_venv_size_mb = venv_info.get("api_venv", {}).get("size_mb", 0)
            if api_venv_size_mb > 2500:  # 2.5 GB warning
                health_status["warnings"].append(f"api_venv size is large: {api_venv_size_mb} MB")
            
            if api_venv_size_mb > 3500:  # 3.5 GB critical
                health_status["issues"].append(f"api_venv size is critical: {api_venv_size_mb} MB")
                health_status["overall_health"] = "critical"
            
            # Test basic execution
            try:
                test_result = await self.venv_execution_service.test_venv_execution()
                if not test_result.get("success"):
                    health_status["issues"].append("Venv execution test failed")
                    health_status["overall_health"] = "unhealthy"
            except Exception as e:
                health_status["issues"].append(f"Venv execution test error: {str(e)}")
                health_status["overall_health"] = "unhealthy"
            
            # Check execution statistics
            exec_stats = self.venv_execution_service._execution_stats
            total_execs = exec_stats.get("total_executions", 0)
            failed_execs = exec_stats.get("failed_executions", 0)
            
            if total_execs > 0:
                failure_rate = failed_execs / total_execs
                if failure_rate > 0.1:  # 10% failure rate warning
                    health_status["warnings"].append(f"High failure rate: {failure_rate:.1%}")
                if failure_rate > 0.3:  # 30% failure rate critical
                    health_status["issues"].append(f"Critical failure rate: {failure_rate:.1%}")
                    health_status["overall_health"] = "critical"
            
            return {
                "success": True,
                "health_check": health_status,
                "system_info": {
                    "venv_info": venv_info,
                    "execution_stats": exec_stats,
                    "installation_stats": self.package_installer._stats
                },
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error during health check: {e}")
            return {
                "success": False,
                "error": str(e),
                "health_check": {
                    "overall_health": "error",
                    "issues": [f"Health check failed: {str(e)}"]
                },
                "timestamp": datetime.now().isoformat()
            }

# Initialize the API
venv_management_api = VenvManagementAPI()


