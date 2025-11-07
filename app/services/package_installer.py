"""
Package Installer service that orchestrates automatic library installation.
Combines dependency detection with venv management for seamless package installation.
"""
import logging
import asyncio
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import json

from .venv_manager import venv_manager
from .dependency_detector import dependency_detector
from .package_post_installer import package_post_installer

logger = logging.getLogger(__name__)

class PackageInstaller:
    """Orchestrates automatic package installation for generated APIs."""
    
    def __init__(self):
        self.venv_manager = venv_manager
        self.dependency_detector = dependency_detector
        self.post_installer = package_post_installer
        
        # Installation cache to avoid re-analyzing same code
        self._analysis_cache = {}
        
        # Installation statistics
        self._stats = {
            "total_installations": 0,
            "successful_installations": 0,
            "failed_installations": 0,
            "cache_hits": 0,
            "total_packages_installed": 0,
            "post_install_count": 0,
            "last_reset": datetime.now().isoformat()
        }
    
    async def analyze_and_install_dependencies(self, code: str, force_reinstall: bool = False) -> Dict:
        """
        Analyze code dependencies and install required packages.
        
        Args:
            code: Python source code to analyze
            force_reinstall: Whether to force reinstallation of packages
            
        Returns:
            Dictionary with installation results and analysis
        """
        try:
            logger.info("Starting dependency analysis and installation...")
            
            # Step 1: Analyze code dependencies
            analysis = self.dependency_detector.analyze_code_dependencies(code)
            
            if analysis.get("error"):
                logger.error(f"Dependency analysis failed: {analysis['error']}")
                return {
                    "success": False,
                    "error": f"Dependency analysis failed: {analysis['error']}",
                    "analysis": analysis,
                    "installation_results": {}
                }
            
            # Step 2: Check for dangerous imports
            if analysis["has_dangerous_imports"]:
                dangerous_modules = analysis["dangerous_modules"]
                logger.warning(f"Code contains dangerous imports: {dangerous_modules}")
                return {
                    "success": False,
                    "error": f"Code contains dangerous imports: {', '.join(dangerous_modules)}",
                    "analysis": analysis,
                    "installation_results": {},
                    "security_warning": True
                }
            
            # Step 3: Validate packages
            packages_to_install = analysis["packages_to_install"]
            allowed_packages, blocked_packages = self.dependency_detector.validate_packages(packages_to_install)
            
            if blocked_packages:
                logger.warning(f"Some packages are blocked: {blocked_packages}")
                # Continue with allowed packages only
                packages_to_install = allowed_packages
            
            # Step 4: Install packages
            installation_results = {}
            if packages_to_install:
                logger.info(f"Installing {len(packages_to_install)} packages: {packages_to_install}")
                
                # Check venv size before installation
                venv_info = self.venv_manager.get_venv_info()
                current_size_mb = venv_info.get("api_venv", {}).get("size_mb", 0)
                estimated_size_mb = analysis["estimated_size_mb"]
                
                # Warn if installation might exceed reasonable size
                if current_size_mb + estimated_size_mb > 2500:  # 2.5 GB warning
                    logger.warning(f"Installation might exceed size limits: {current_size_mb + estimated_size_mb} MB")
                
                # Perform installation
                installation_results = self.venv_manager.install_packages_in_api_venv(packages_to_install)
                
                # Update statistics
                self._update_installation_stats(installation_results)
                
                # Step 4.5: Run post-installation setup for packages that need it
                successfully_installed = [pkg for pkg, success in installation_results.items() if success]
                if successfully_installed:
                    post_install_result = self._run_post_installation(successfully_installed)
                    if post_install_result.get("packages_processed"):
                        logger.info(f"Post-installation completed for: {post_install_result['packages_processed']}")
                        self._stats["post_install_count"] += 1
                
            else:
                logger.info("No external packages to install")
                installation_results = {}
            
            # Step 5: Prepare final result
            success = all(installation_results.values()) if installation_results else True
            failed_packages = [pkg for pkg, success in installation_results.items() if not success]
            
            result = {
                "success": success,
                "analysis": analysis,
                "installation_results": installation_results,
                "allowed_packages": allowed_packages,
                "blocked_packages": blocked_packages,
                "failed_packages": failed_packages,
                "venv_info": self.venv_manager.get_venv_info(),
                "installation_stats": self._stats.copy(),
                "timestamp": datetime.now().isoformat()
            }
            
            if not success:
                result["error"] = f"Failed to install packages: {', '.join(failed_packages)}"
            
            logger.info(f"Dependency installation completed. Success: {success}")
            return result
            
        except Exception as e:
            logger.error(f"Error in analyze_and_install_dependencies: {e}")
            return {
                "success": False,
                "error": f"Installation process failed: {str(e)}",
                "analysis": {},
                "installation_results": {},
                "timestamp": datetime.now().isoformat()
            }
    
    def _update_installation_stats(self, installation_results: Dict[str, bool]):
        """Update installation statistics."""
        self._stats["total_installations"] += 1
        
        successful = sum(1 for success in installation_results.values() if success)
        failed = len(installation_results) - successful
        
        self._stats["successful_installations"] += successful
        self._stats["failed_installations"] += failed
        self._stats["total_packages_installed"] += successful
    
    def _run_post_installation(self, packages: List[str]) -> Dict:
        """Run post-installation setup for packages that need it (e.g., NLTK data download)."""
        try:
            python_path = self.venv_manager.get_api_venv_python_path()
            pip_path = self.venv_manager.get_api_venv_pip_path()
            
            result = self.post_installer.run_all_post_installs(packages, python_path, pip_path)
            
            return result
            
        except Exception as e:
            logger.error(f"Post-installation failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "packages_processed": []
            }
    
    async def prepare_execution_environment(self, code: str) -> Dict:
        """
        Prepare execution environment by analyzing and installing dependencies.
        This is the main entry point for the API execution pipeline.
        
        Args:
            code: Generated API code to prepare environment for
            
        Returns:
            Dictionary with preparation results
        """
        try:
            logger.info("Preparing execution environment...")
            
            # Analyze and install dependencies
            result = await self.analyze_and_install_dependencies(code)
            
            if not result["success"]:
                logger.error(f"Failed to prepare environment: {result.get('error')}")
                return result
            
            # Get execution info
            python_path = self.venv_manager.get_api_venv_python_path()
            venv_info = self.venv_manager.get_venv_info()
            
            # Add execution information
            result.update({
                "execution_ready": True,
                "python_path": python_path,
                "api_venv_path": str(self.venv_manager.api_venv_path),
                "environment_info": {
                    "packages_available": len(venv_info.get("api_venv", {}).get("packages", {})),
                    "venv_size_mb": venv_info.get("api_venv", {}).get("size_mb", 0),
                    "python_executable": python_path
                }
            })
            
            logger.info("Execution environment prepared successfully")
            return result
            
        except Exception as e:
            logger.error(f"Error preparing execution environment: {e}")
            return {
                "success": False,
                "error": f"Failed to prepare execution environment: {str(e)}",
                "execution_ready": False,
                "timestamp": datetime.now().isoformat()
            }
    
    def get_installation_status(self) -> Dict:
        """Get current installation status and statistics."""
        try:
            venv_info = self.venv_manager.get_venv_info()
            
            return {
                "venv_status": {
                    "main_venv_exists": venv_info.get("main_venv", {}).get("exists", False),
                    "api_venv_exists": venv_info.get("api_venv", {}).get("exists", False),
                    "api_venv_size_mb": venv_info.get("api_venv", {}).get("size_mb", 0),
                    "installed_packages": venv_info.get("api_venv", {}).get("installed_packages", 0)
                },
                "installation_stats": self._stats.copy(),
                "system_info": {
                    "python_path": self.venv_manager.get_api_venv_python_path(),
                    "pip_path": self.venv_manager.get_api_venv_pip_path(),
                    "venv_paths": {
                        "main": str(self.venv_manager.main_venv_path),
                        "api": str(self.venv_manager.api_venv_path)
                    }
                },
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting installation status: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
    
    def reset_api_environment(self) -> Dict:
        """Reset the API environment (api_venv) and clear statistics."""
        try:
            logger.info("Resetting API environment...")
            
            # Reset the api_venv
            self.venv_manager.reset_api_venv()
            
            # Reset statistics
            self._stats = {
                "total_installations": 0,
                "successful_installations": 0,
                "failed_installations": 0,
                "cache_hits": 0,
                "total_packages_installed": 0,
                "last_reset": datetime.now().isoformat()
            }
            
            # Clear analysis cache
            self._analysis_cache.clear()
            
            logger.info("API environment reset successfully")
            
            return {
                "success": True,
                "message": "API environment reset successfully",
                "venv_info": self.venv_manager.get_venv_info(),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error resetting API environment: {e}")
            return {
                "success": False,
                "error": f"Failed to reset API environment: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    def cleanup_if_needed(self) -> Dict:
        """Perform cleanup if api_venv exceeds size limits."""
        try:
            logger.info("Checking if cleanup is needed...")
            
            # Check if cleanup is needed (3 GB limit)
            cleanup_performed = self.venv_manager.cleanup_if_needed(max_size_gb=3.0)
            
            if cleanup_performed:
                logger.info("Cleanup performed - api_venv was reset")
                # Reset our statistics too
                self._stats["last_reset"] = datetime.now().isoformat()
                self._analysis_cache.clear()
                
                return {
                    "cleanup_performed": True,
                    "message": "api_venv exceeded size limit and was reset",
                    "venv_info": self.venv_manager.get_venv_info(),
                    "timestamp": datetime.now().isoformat()
                }
            else:
                logger.info("No cleanup needed")
                return {
                    "cleanup_performed": False,
                    "message": "api_venv size is within limits",
                    "venv_info": self.venv_manager.get_venv_info(),
                    "timestamp": datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"Error in cleanup check: {e}")
            return {
                "cleanup_performed": False,
                "error": f"Cleanup check failed: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }
    
    async def test_package_installation(self, package_name: str) -> Dict:
        """Test installation of a specific package."""
        try:
            logger.info(f"Testing installation of package: {package_name}")
            
            # Validate package
            allowed, blocked = self.dependency_detector.validate_packages([package_name])
            
            if package_name in blocked:
                return {
                    "success": False,
                    "error": f"Package '{package_name}' is blocked for security reasons",
                    "package": package_name,
                    "timestamp": datetime.now().isoformat()
                }
            
            # Get package info
            package_info = self.dependency_detector.get_package_info(package_name)
            
            # Install package
            installation_results = self.venv_manager.install_packages_in_api_venv([package_name])
            
            success = installation_results.get(package_name, False)
            
            return {
                "success": success,
                "package": package_name,
                "package_info": package_info,
                "installation_result": installation_results,
                "venv_info": self.venv_manager.get_venv_info(),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error testing package installation: {e}")
            return {
                "success": False,
                "error": f"Package installation test failed: {str(e)}",
                "package": package_name,
                "timestamp": datetime.now().isoformat()
            }
    
    def get_available_packages(self) -> Dict:
        """Get list of currently installed packages in api_venv."""
        try:
            installed_packages = self.venv_manager.get_installed_packages()
            venv_info = self.venv_manager.get_venv_info()
            
            return {
                "installed_packages": installed_packages,
                "package_count": len(installed_packages),
                "venv_size_mb": venv_info.get("api_venv", {}).get("size_mb", 0),
                "common_packages": list(self.dependency_detector.COMMON_PACKAGES),
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting available packages: {e}")
            return {
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }

# Initialize the service
package_installer = PackageInstaller()
