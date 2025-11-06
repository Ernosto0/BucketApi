"""
Post-installation handler for packages that need additional setup.
Handles NLTK data downloads, spaCy model downloads, etc.
"""
import logging
import subprocess
import sys
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)

class PackagePostInstaller:
    """Handles post-installation setup for packages with additional requirements."""
    
    def __init__(self):
        # Map packages to their post-install requirements
        self.POST_INSTALL_HANDLERS = {
            'nltk': self._setup_nltk,
            'spacy': self._setup_spacy,
            'textblob': self._setup_textblob,
        }
        
        # NLTK data packages to download (commonly needed)
        self.NLTK_DATA_PACKAGES = [
            'punkt',
            'punkt_tab',
            'stopwords',
            'averaged_perceptron_tagger',
            'maxent_ne_chunker',
            'words',
            'wordnet',
            'omw-1.4'
        ]
        
        # spaCy models (download only if needed)
        self.SPACY_MODELS = {
            'en': 'en_core_web_sm',  # English small model
            'es': 'es_core_news_sm',  # Spanish
            'fr': 'fr_core_news_sm',  # French
            'de': 'de_core_news_sm',  # German
        }
    
    def needs_post_install(self, package_name: str) -> bool:
        """Check if a package needs post-installation setup."""
        return package_name in self.POST_INSTALL_HANDLERS
    
    def run_post_install(self, package_name: str, python_path: str, pip_path: str) -> Dict:
        """
        Run post-installation setup for a package.
        
        Args:
            package_name: Name of the package
            python_path: Path to Python executable in venv
            pip_path: Path to pip executable in venv
            
        Returns:
            Dict with success status and details
        """
        if package_name not in self.POST_INSTALL_HANDLERS:
            return {
                "success": True,
                "message": f"No post-install needed for {package_name}",
                "package": package_name
            }
        
        try:
            logger.info(f"Running post-installation setup for {package_name}...")
            handler = self.POST_INSTALL_HANDLERS[package_name]
            result = handler(python_path, pip_path)
            logger.info(f"Post-installation for {package_name} completed: {result['success']}")
            return result
            
        except Exception as e:
            logger.error(f"Post-installation failed for {package_name}: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": package_name
            }
    
    def _setup_nltk(self, python_path: str, pip_path: str) -> Dict:
        """Setup NLTK by downloading required data packages."""
        try:
            logger.info("Setting up NLTK data packages...")
            
            # Create a Python script to download NLTK data
            download_script = f'''
import nltk
import ssl

# Handle SSL certificate issues
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Download common NLTK data packages
data_packages = {self.NLTK_DATA_PACKAGES}
successful = []
failed = []

for package in data_packages:
    try:
        nltk.download(package, quiet=True)
        successful.append(package)
        print(f"Downloaded: {{package}}")
    except Exception as e:
        failed.append(package)
        print(f"Failed to download {{package}}: {{e}}")

print(f"\\nNLTK Setup Complete:")
print(f"  Successful: {{len(successful)}} packages")
print(f"  Failed: {{len(failed)}} packages")
'''
            
            # Run the download script
            result = subprocess.run(
                [python_path, "-c", download_script],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "message": "NLTK data packages downloaded successfully",
                    "package": "nltk",
                    "output": result.stdout
                }
            else:
                # Even if some downloads failed, NLTK might still work
                # Don't fail completely, just warn
                logger.warning(f"NLTK data download had issues: {result.stderr}")
                return {
                    "success": True,  # Don't block - partial success is OK
                    "warning": "Some NLTK data packages may not have downloaded",
                    "package": "nltk",
                    "output": result.stdout,
                    "stderr": result.stderr
                }
                
        except Exception as e:
            logger.error(f"NLTK setup failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": "nltk"
            }
    
    def _setup_spacy(self, python_path: str, pip_path: str) -> Dict:
        """Setup spaCy by downloading the English model."""
        try:
            logger.info("Setting up spaCy models...")
            
            # Download the small English model by default
            model_name = self.SPACY_MODELS['en']
            
            result = subprocess.run(
                [python_path, "-m", "spacy", "download", model_name],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout for model download
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "message": f"spaCy model '{model_name}' downloaded successfully",
                    "package": "spacy",
                    "model": model_name
                }
            else:
                logger.warning(f"spaCy model download had issues: {result.stderr}")
                return {
                    "success": False,
                    "error": result.stderr,
                    "package": "spacy",
                    "message": "spaCy model download failed, but package is installed"
                }
                
        except Exception as e:
            logger.error(f"spaCy setup failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": "spacy"
            }
    
    def _setup_textblob(self, python_path: str, pip_path: str) -> Dict:
        """Setup TextBlob by downloading corpora."""
        try:
            logger.info("Setting up TextBlob corpora...")
            
            # Download TextBlob corpora
            download_script = '''
import textblob
try:
    textblob.download_corpora()
    print("TextBlob corpora downloaded successfully")
except Exception as e:
    print(f"TextBlob download error: {e}")
'''
            
            result = subprocess.run(
                [python_path, "-c", download_script],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                return {
                    "success": True,
                    "message": "TextBlob corpora downloaded successfully",
                    "package": "textblob"
                }
            else:
                return {
                    "success": True,  # Don't block - partial success is OK
                    "warning": "TextBlob corpora download may have failed",
                    "package": "textblob",
                    "stderr": result.stderr
                }
                
        except Exception as e:
            logger.error(f"TextBlob setup failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "package": "textblob"
            }
    
    def get_post_install_packages(self, packages: List[str]) -> List[str]:
        """Get list of packages that need post-installation."""
        return [pkg for pkg in packages if self.needs_post_install(pkg)]
    
    def run_all_post_installs(self, packages: List[str], python_path: str, pip_path: str) -> Dict:
        """Run post-installation for all packages that need it."""
        post_install_packages = self.get_post_install_packages(packages)
        
        if not post_install_packages:
            return {
                "success": True,
                "message": "No packages need post-installation",
                "packages_processed": []
            }
        
        results = {}
        all_success = True
        
        for package in post_install_packages:
            result = self.run_post_install(package, python_path, pip_path)
            results[package] = result
            if not result["success"]:
                all_success = False
        
        return {
            "success": all_success,
            "packages_processed": post_install_packages,
            "results": results,
            "message": f"Post-installation completed for {len(post_install_packages)} packages"
        }

# Initialize the service
package_post_installer = PackagePostInstaller()
