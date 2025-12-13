"""
Virtual Environment Manager for 2-venv architecture.
Manages main_venv (application) and api_venv (generated APIs).
"""
import os
import sys
import subprocess
import logging
import json
import shutil
import contextlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import venv
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    import fcntl  # type: ignore
except Exception:  # pragma: no cover - not available on Windows
    fcntl = None

class VenvManager:
    """Manages two virtual environments: main_venv and api_venv"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent.parent.parent
        self.venv_dir = self.project_root / "venvs"
        self.main_venv_path = self.venv_dir / "main_venv"
        self.api_venv_path = self.venv_dir / "api_venv"
        
        # Track installed packages in api_venv
        self.packages_file = self.api_venv_path / "installed_packages.json"
        
        # Ensure venv directory exists
        self.venv_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize venvs if they don't exist
        self._ensure_venvs_exist()

    @contextlib.contextmanager
    def _venv_create_lock(self):
        """
        Prevent concurrent venv creation across multiple processes (e.g. Gunicorn workers).
        Without this, two workers can race and crash with FileExistsError.
        """
        lock_path = self.venv_dir / ".venv_create.lock"
        self.venv_dir.mkdir(parents=True, exist_ok=True)
        with open(lock_path, "w", encoding="utf-8") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    
    def _ensure_venvs_exist(self):
        """Ensure both virtual environments exist and are properly set up."""
        try:
            # Creating venvs during import can race under multi-worker servers.
            # Use a filesystem lock so only one process does the creation.
            with self._venv_create_lock():
                # Check if we're already in a venv (main_venv)
                if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
                    logger.info("Already running in main_venv, skipping main_venv creation")
                else:
                    # Create main_venv if it doesn't exist
                    if not self._venv_is_valid(self.main_venv_path):
                        logger.info("Creating main_venv...")
                        self._create_main_venv()
                
                # Always ensure api_venv exists
                if not self._venv_is_valid(self.api_venv_path):
                    logger.info("Creating api_venv...")
                    self._create_api_venv()
                else:
                    logger.info("api_venv already exists")
                
        except Exception as e:
            logger.error(f"Error ensuring venvs exist: {e}")
            raise

    def _venv_is_valid(self, venv_path: Path) -> bool:
        """A venv is considered valid if it has a pyvenv.cfg file."""
        try:
            return venv_path.exists() and (venv_path / "pyvenv.cfg").exists()
        except Exception:
            return False
    
    def _create_main_venv(self):
        """Create main virtual environment for the application."""
        try:
            # If something already created it (or partially exists), clean up safely.
            if self.main_venv_path.exists() and not self._venv_is_valid(self.main_venv_path):
                shutil.rmtree(self.main_venv_path, ignore_errors=True)

            # Create the venv
            venv.create(self.main_venv_path, with_pip=True, clear=True)
            
            # Install from requirements.txt if it exists
            requirements_file = self.project_root / "requirements.txt"
            
            if requirements_file.exists():
                logger.info("Installing dependencies from requirements.txt...")
                pip_path = self._get_pip_path(self.main_venv_path)
                
                result = subprocess.run(
                    [str(pip_path), "install", "-r", str(requirements_file)],
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout for full installation
                )
                
                if result.returncode != 0:
                    logger.error(f"Failed to install from requirements.txt: {result.stderr}")
                    raise Exception("Failed to install main app requirements")
                else:
                    logger.info("Successfully installed all requirements from requirements.txt")
            else:
                logger.warning("requirements.txt not found, skipping main_venv package installation")
            
            logger.info("main_venv created successfully")
            
        except Exception as e:
            logger.error(f"Error creating main_venv: {e}")
            raise
    
    def _create_api_venv(self):
        """Create API virtual environment for generated APIs."""
        try:
            # If something already created it (or partially exists), clean up safely.
            if self.api_venv_path.exists() and not self._venv_is_valid(self.api_venv_path):
                shutil.rmtree(self.api_venv_path, ignore_errors=True)

            # Create the venv
            venv.create(self.api_venv_path, with_pip=True, clear=True)
            
            # Install minimal base packages for API execution
            base_packages = [
                "requests>=2.31.0",  # HTTP requests
                "openai>=1.12.0",    # AI API calls
                "anthropic>=0.7.0",  # Claude API
            ]
            
            self._install_packages_in_venv(self.api_venv_path, base_packages)
            
            # Initialize package tracking
            self._init_package_tracking()
            
            logger.info("api_venv created successfully")
            
        except Exception as e:
            logger.error(f"Error creating api_venv: {e}")
            raise
    
    def _install_packages_in_venv(self, venv_path: Path, packages: List[str]):
        """Install packages in a specific virtual environment."""
        pip_path = self._get_pip_path(venv_path)
        
        for package in packages:
            try:
                logger.info(f"Installing {package} in {venv_path.name}...")
                result = subprocess.run(
                    [str(pip_path), "install", package],
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout per package
                )
                
                if result.returncode != 0:
                    logger.error(f"Failed to install {package}: {result.stderr}")
                    raise Exception(f"Package installation failed: {package}")
                else:
                    logger.info(f"Successfully installed {package}")
                    
            except subprocess.TimeoutExpired:
                logger.error(f"Timeout installing {package}")
                raise Exception(f"Package installation timeout: {package}")
            except Exception as e:
                logger.error(f"Error installing {package}: {e}")
                raise
    
    def _get_python_path(self, venv_path: Path) -> Path:
        """Get Python executable path for a venv."""
        if os.name == 'nt':  # Windows
            return venv_path / "Scripts" / "python.exe"
        else:  # Unix/Linux/Mac
            return venv_path / "bin" / "python"
    
    def _get_pip_path(self, venv_path: Path) -> Path:
        """Get pip executable path for a venv."""
        if os.name == 'nt':  # Windows
            return venv_path / "Scripts" / "pip.exe"
        else:  # Unix/Linux/Mac
            return venv_path / "bin" / "pip"
    
    def _init_package_tracking(self):
        """Initialize package tracking file for api_venv."""
        tracking_data = {
            "created_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "installed_packages": {},
            "installation_history": []
        }
        
        with open(self.packages_file, 'w') as f:
            json.dump(tracking_data, f, indent=2)
    
    def get_api_venv_python_path(self) -> str:
        """Get the Python executable path for api_venv."""
        return str(self._get_python_path(self.api_venv_path))
    
    def get_api_venv_pip_path(self) -> str:
        """Get the pip executable path for api_venv."""
        return str(self._get_pip_path(self.api_venv_path))
    
    def install_packages_in_api_venv(self, packages: List[str]) -> Dict[str, bool]:
        """
        Install packages in api_venv.
        
        Args:
            packages: List of package names/specs to install
            
        Returns:
            Dict mapping package names to success status
        """
        results = {}
        
        try:
            # Load current package tracking
            tracking_data = self._load_package_tracking()
            
            for package in packages:
                try:
                    # Check if already installed
                    if self._is_package_installed(package, tracking_data):
                        logger.info(f"Package {package} already installed, skipping")
                        results[package] = True
                        continue
                    
                    # Install the package
                    logger.info(f"Installing {package} in api_venv...")
                    pip_path = self.get_api_venv_pip_path()
                    
                    result = subprocess.run(
                        [pip_path, "install", package],
                        capture_output=True,
                        text=True,
                        timeout=600  # 10 minute timeout for complex packages
                    )
                    
                    if result.returncode == 0:
                        logger.info(f"Successfully installed {package}")
                        results[package] = True
                        
                        # Update tracking
                        self._track_package_installation(package, True, tracking_data)
                        
                    else:
                        logger.error(f"Failed to install {package}: {result.stderr}")
                        results[package] = False
                        
                        # Track failed installation
                        self._track_package_installation(package, False, tracking_data)
                        
                except subprocess.TimeoutExpired:
                    logger.error(f"Timeout installing {package}")
                    results[package] = False
                    self._track_package_installation(package, False, tracking_data)
                    
                except Exception as e:
                    logger.error(f"Error installing {package}: {e}")
                    results[package] = False
                    self._track_package_installation(package, False, tracking_data)
            
            # Save updated tracking data
            self._save_package_tracking(tracking_data)
            
        except Exception as e:
            logger.error(f"Error in install_packages_in_api_venv: {e}")
            # Return failure for all packages
            results = {pkg: False for pkg in packages}
        
        return results
    
    def _load_package_tracking(self) -> Dict:
        """Load package tracking data."""
        try:
            if self.packages_file.exists():
                with open(self.packages_file, 'r') as f:
                    return json.load(f)
            else:
                # Create new tracking file
                self._init_package_tracking()
                with open(self.packages_file, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Error loading package tracking: {e}")
            # Return default structure
            return {
                "created_at": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat(),
                "installed_packages": {},
                "installation_history": []
            }
    
    def _save_package_tracking(self, tracking_data: Dict):
        """Save package tracking data."""
        try:
            tracking_data["last_updated"] = datetime.now().isoformat()
            with open(self.packages_file, 'w') as f:
                json.dump(tracking_data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving package tracking: {e}")
    
    def _is_package_installed(self, package: str, tracking_data: Dict) -> bool:
        """Check if a package is already installed."""
        # Extract package name (remove version specs)
        package_name = package.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0]
        return package_name in tracking_data.get("installed_packages", {})
    
    def _track_package_installation(self, package: str, success: bool, tracking_data: Dict):
        """Track package installation in the tracking data."""
        package_name = package.split('==')[0].split('>=')[0].split('<=')[0].split('>')[0].split('<')[0]
        
        if success:
            tracking_data["installed_packages"][package_name] = {
                "package_spec": package,
                "installed_at": datetime.now().isoformat(),
                "success": True
            }
        
        # Add to history
        tracking_data["installation_history"].append({
            "package": package,
            "success": success,
            "timestamp": datetime.now().isoformat()
        })
        
        # Keep only last 100 history entries
        if len(tracking_data["installation_history"]) > 100:
            tracking_data["installation_history"] = tracking_data["installation_history"][-100:]
    
    def get_installed_packages(self) -> Dict[str, Dict]:
        """Get list of installed packages in api_venv."""
        tracking_data = self._load_package_tracking()
        return tracking_data.get("installed_packages", {})
    
    def get_api_venv_size(self) -> int:
        """Get size of api_venv in bytes."""
        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(self.api_venv_path):
                for filename in filenames:
                    filepath = os.path.join(dirpath, filename)
                    try:
                        total_size += os.path.getsize(filepath)
                    except (OSError, IOError):
                        pass
            return total_size
        except Exception as e:
            logger.error(f"Error calculating api_venv size: {e}")
            return 0
    
    def reset_api_venv(self):
        """Reset api_venv by deleting and recreating it."""
        try:
            logger.info("Resetting api_venv...")
            
            # Remove existing api_venv
            if self.api_venv_path.exists():
                shutil.rmtree(self.api_venv_path)
            
            # Recreate api_venv
            self._create_api_venv()
            
            logger.info("api_venv reset successfully")
            
        except Exception as e:
            logger.error(f"Error resetting api_venv: {e}")
            raise
    
    def cleanup_if_needed(self, max_size_gb: float = 3.0):
        """Reset api_venv if it exceeds maximum size."""
        try:
            current_size = self.get_api_venv_size()
            max_size_bytes = max_size_gb * 1024 * 1024 * 1024  # Convert GB to bytes
            
            if current_size > max_size_bytes:
                logger.warning(f"api_venv size ({current_size / 1024 / 1024 / 1024:.2f} GB) exceeds limit ({max_size_gb} GB)")
                self.reset_api_venv()
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error in cleanup_if_needed: {e}")
            return False
    
    def get_venv_info(self) -> Dict:
        """Get information about both virtual environments."""
        try:
            api_venv_size = self.get_api_venv_size()
            installed_packages = self.get_installed_packages()
            
            return {
                "main_venv": {
                    "path": str(self.main_venv_path),
                    "exists": self.main_venv_path.exists(),
                    "python_path": str(self._get_python_path(self.main_venv_path))
                },
                "api_venv": {
                    "path": str(self.api_venv_path),
                    "exists": self.api_venv_path.exists(),
                    "python_path": str(self._get_python_path(self.api_venv_path)),
                    "pip_path": str(self._get_pip_path(self.api_venv_path)),
                    "size_bytes": api_venv_size,
                    "size_mb": round(api_venv_size / 1024 / 1024, 2),
                    "installed_packages": len(installed_packages),
                    "packages": installed_packages
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting venv info: {e}")
            return {}

# Initialize the service
venv_manager = VenvManager()
