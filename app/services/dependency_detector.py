"""
Dependency Detector for automatically extracting required packages from generated API code.
Analyzes Python code to determine which packages need to be installed.
"""
import ast
import re
import logging
from typing import Set, List, Dict, Optional, Tuple
from pathlib import Path

logger = logging.getLogger(__name__)

class DependencyDetector:
    """Detects and resolves Python package dependencies from code."""
    
    def __init__(self):
        # Map import names to pip package names
        self.IMPORT_TO_PACKAGE = {
            # Standard mappings where import name != package name
            'cv2': 'opencv-python',
            'PIL': 'Pillow',
            'sklearn': 'scikit-learn',
            'bs4': 'beautifulsoup4',
            'dateutil': 'python-dateutil',
            'yaml': 'PyYAML',
            'jwt': 'PyJWT',
            'psycopg2': 'psycopg2-binary',
            'MySQLdb': 'mysqlclient',
            'pymysql': 'PyMySQL',
            'redis': 'redis',
            'celery': 'celery',
            'flask': 'Flask',
            'django': 'Django',
            'tornado': 'tornado',
            'bottle': 'bottle',
            'cherrypy': 'CherryPy',
            'werkzeug': 'Werkzeug',
            'jinja2': 'Jinja2',
            'markupsafe': 'MarkupSafe',
            'itsdangerous': 'ItsDangerous',
            'click': 'Click',
            'colorama': 'colorama',
            'tqdm': 'tqdm',
            'progressbar': 'progressbar2',
            'tabulate': 'tabulate',
            'rich': 'rich',
            'typer': 'typer',
            'fire': 'fire',
            'argparse': None,  # Built-in, no package needed
            'configparser': None,  # Built-in
            'logging': None,  # Built-in
            'json': None,  # Built-in
            're': None,  # Built-in
            'os': None,  # Built-in
            'sys': None,  # Built-in
            'datetime': None,  # Built-in
            'time': None,  # Built-in
            'math': None,  # Built-in
            'random': None,  # Built-in
            'string': None,  # Built-in
            'collections': None,  # Built-in
            'itertools': None,  # Built-in
            'functools': None,  # Built-in
            'operator': None,  # Built-in
            'copy': None,  # Built-in
            'pickle': None,  # Built-in
            'base64': None,  # Built-in
            'hashlib': None,  # Built-in
            'hmac': None,  # Built-in
            'secrets': None,  # Built-in
            'uuid': None,  # Built-in
            'decimal': None,  # Built-in
            'fractions': None,  # Built-in
            'statistics': None,  # Built-in
            'pathlib': None,  # Built-in
            'glob': None,  # Built-in
            'fnmatch': None,  # Built-in
            'tempfile': None,  # Built-in (but we might restrict this)
            'shutil': None,  # Built-in (but we might restrict this)
            'io': None,  # Built-in
            'gzip': None,  # Built-in
            'zipfile': None,  # Built-in
            'tarfile': None,  # Built-in
            'csv': None,  # Built-in
            'xml': None,  # Built-in
            'html': None,  # Built-in
            'urllib': None,  # Built-in
            'http': None,  # Built-in
            'email': None,  # Built-in
            'mimetypes': None,  # Built-in
            'calendar': None,  # Built-in
            'locale': None,  # Built-in
            'gettext': None,  # Built-in
            'threading': None,  # Built-in (but we might restrict this)
            'multiprocessing': None,  # Built-in (but we might restrict this)
            'concurrent': None,  # Built-in
            'asyncio': None,  # Built-in
            'socket': None,  # Built-in (but we might restrict this)
            'ssl': None,  # Built-in
            'select': None,  # Built-in
            'signal': None,  # Built-in (but we might restrict this)
            'subprocess': None,  # Built-in (RESTRICTED)
            'ctypes': None,  # Built-in (RESTRICTED)
            'platform': None,  # Built-in
            'getpass': None,  # Built-in
            'pwd': None,  # Built-in (Unix only)
            'grp': None,  # Built-in (Unix only)
            'termios': None,  # Built-in (Unix only)
            'tty': None,  # Built-in (Unix only)
            'pty': None,  # Built-in (Unix only)
            'fcntl': None,  # Built-in (Unix only)
            'pipes': None,  # Built-in (Unix only)
            'resource': None,  # Built-in (Unix only)
            'syslog': None,  # Built-in (Unix only)
            'winreg': None,  # Built-in (Windows only)
            'winsound': None,  # Built-in (Windows only)
            'msvcrt': None,  # Built-in (Windows only)
        }
        
        # Packages that are dangerous and should be blocked
        self.DANGEROUS_PACKAGES = {
            'subprocess',
            # 'os' removed - we'll handle os operations at the function level
            # 'sys' removed - we'll handle sys operations at the function level  
            'ctypes',
            'importlib',
            'builtins',
            '__builtin__',
            'eval',
            'exec',
            'compile',
            'code',
            'codeop',
        }
        
        # Safe os operations that are allowed
        self.SAFE_OS_OPERATIONS = {
            'getenv', 'environ', 'path', 'getcwd', 'listdir', 'walk', 'stat',
            'access', 'exists', 'isfile', 'isdir', 'basename', 'dirname',
            'join', 'split', 'splitext', 'abspath', 'relpath', 'normpath',
            'expanduser', 'expandvars', 'getsize', 'getmtime', 'getctime'
        }
        
        # Dangerous os operations that should be blocked
        self.DANGEROUS_OS_OPERATIONS = {
            'system', 'popen', 'spawn', 'exec', 'fork', 'kill', 'killpg',
            'remove', 'unlink', 'rmdir', 'removedirs', 'rename', 'renames',
            'chmod', 'chown', 'chroot', 'setuid', 'setgid', 'umask'
        }
        
        # Common package patterns and their pip names
        self.COMMON_PACKAGES = {
            'requests', 'httpx', 'aiohttp', 'urllib3',
            'numpy', 'pandas', 'scipy', 'matplotlib', 'seaborn', 'plotly',
            'scikit-learn', 'sklearn', 'xgboost', 'lightgbm', 'catboost',
            'tensorflow', 'torch', 'keras', 'transformers', 'datasets',
            'nltk', 'spacy', 'textblob', 'gensim', 'wordcloud',
            'opencv-python', 'Pillow', 'imageio', 'scikit-image',
            'beautifulsoup4', 'lxml', 'scrapy', 'selenium',
            'fastapi', 'flask', 'django', 'starlette', 'uvicorn',
            'pydantic', 'marshmallow', 'cerberus', 'schema',
            'sqlalchemy', 'alembic', 'peewee', 'tortoise-orm',
            'psycopg2-binary', 'PyMySQL', 'redis', 'motor',
            'celery', 'rq', 'dramatiq', 'huey',
            'pytest', 'unittest2', 'nose2', 'coverage',
            'black', 'flake8', 'mypy', 'isort', 'autopep8',
            'click', 'typer', 'fire', 'argparse',
            'python-dotenv', 'configparser', 'toml', 'PyYAML',
            'tqdm', 'rich', 'colorama', 'termcolor',
            'python-dateutil', 'pytz', 'arrow', 'pendulum',
            'cryptography', 'bcrypt', 'passlib', 'PyJWT',
            'openai', 'anthropic', 'cohere', 'langchain',
        }
    
    def extract_imports_from_code(self, code: str) -> Set[str]:
        """
        Extract all import statements from Python code.
        
        Args:
            code: Python source code as string
            
        Returns:
            Set of imported module names
        """
        imports = set()
        
        try:
            # Try AST parsing first (most reliable)
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    # Handle: import module, import module.submodule
                    for alias in node.names:
                        module_name = alias.name.split('.')[0]
                        imports.add(module_name)
                        
                elif isinstance(node, ast.ImportFrom):
                    # Handle: from module import something
                    if node.module:
                        module_name = node.module.split('.')[0]
                        imports.add(module_name)
                        
        except SyntaxError as e:
            logger.warning(f"Syntax error in code, falling back to regex: {e}")
            # Fallback to regex if AST parsing fails
            imports.update(self._extract_imports_regex(code))
            
        except Exception as e:
            logger.error(f"Error parsing imports with AST: {e}")
            # Fallback to regex
            imports.update(self._extract_imports_regex(code))
        
        return imports
    
    def _extract_imports_regex(self, code: str) -> Set[str]:
        """Fallback method to extract imports using regex."""
        imports = set()
        
        # Pattern for: import module
        import_pattern = r'^\s*import\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)'
        matches = re.finditer(import_pattern, code, re.MULTILINE)
        for match in matches:
            module_name = match.group(1).split('.')[0]
            imports.add(module_name)
        
        # Pattern for: from module import something
        from_import_pattern = r'^\s*from\s+([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s+import'
        matches = re.finditer(from_import_pattern, code, re.MULTILINE)
        for match in matches:
            module_name = match.group(1).split('.')[0]
            imports.add(module_name)
        
        return imports
    
    def resolve_package_names(self, imports: Set[str]) -> Tuple[List[str], List[str], List[str]]:
        """
        Resolve import names to pip package names.
        
        Args:
            imports: Set of imported module names
            
        Returns:
            Tuple of (packages_to_install, builtin_modules, dangerous_modules)
        """
        packages_to_install = []
        builtin_modules = []
        dangerous_modules = []
        
        for import_name in imports:
            # Check if it's a dangerous import
            if import_name in self.DANGEROUS_PACKAGES:
                dangerous_modules.append(import_name)
                continue
            
            # Check if it's a built-in module (no package needed)
            if import_name in self.IMPORT_TO_PACKAGE:
                package_name = self.IMPORT_TO_PACKAGE[import_name]
                if package_name is None:
                    builtin_modules.append(import_name)
                else:
                    packages_to_install.append(package_name)
            else:
                # Assume import name == package name for unknown packages
                packages_to_install.append(import_name)
        
        # Remove duplicates while preserving order
        packages_to_install = list(dict.fromkeys(packages_to_install))
        
        return packages_to_install, builtin_modules, dangerous_modules
    
    def analyze_os_operations(self, code: str) -> Tuple[bool, List[str]]:
        """
        Analyze os operations in code to determine if they're safe.
        
        Returns:
            Tuple of (has_dangerous_os_ops, list_of_dangerous_operations)
        """
        dangerous_operations = []
        
        try:
            # Parse the code into AST
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute):
                    # Check for os.operation patterns
                    if isinstance(node.value, ast.Name) and node.value.id == 'os':
                        operation = node.attr
                        if operation in self.DANGEROUS_OS_OPERATIONS:
                            dangerous_operations.append(f"os.{operation}")
                
                elif isinstance(node, ast.Call):
                    # Check for os.operation() calls
                    if isinstance(node.func, ast.Attribute):
                        if isinstance(node.func.value, ast.Name) and node.func.value.id == 'os':
                            operation = node.func.attr
                            if operation in self.DANGEROUS_OS_OPERATIONS:
                                dangerous_operations.append(f"os.{operation}()")
        
        except SyntaxError:
            # If we can't parse the code, be conservative and flag it
            if 'import os' in code or 'from os import' in code:
                # Check for dangerous patterns with regex as fallback
                for op in self.DANGEROUS_OS_OPERATIONS:
                    if f'os.{op}' in code:
                        dangerous_operations.append(f"os.{op}")
        
        return len(dangerous_operations) > 0, dangerous_operations
    
    def analyze_code_dependencies(self, code: str) -> Dict:
        """
        Comprehensive analysis of code dependencies.
        
        Args:
            code: Python source code as string
            
        Returns:
            Dictionary with analysis results
        """
        try:
            # Extract imports
            imports = self.extract_imports_from_code(code)
            
            # Resolve package names
            packages, builtins, dangerous = self.resolve_package_names(imports)
            
            # Analyze os operations specifically
            has_dangerous_os_ops, dangerous_os_ops = self.analyze_os_operations(code)
            
            # If we have dangerous os operations, add them to dangerous modules
            if has_dangerous_os_ops:
                dangerous.extend(dangerous_os_ops)
            
            # Additional analysis
            analysis = {
                "imports_found": list(imports),
                "packages_to_install": packages,
                "builtin_modules": builtins,
                "dangerous_modules": dangerous,
                "dangerous_os_operations": dangerous_os_ops,
                "total_imports": len(imports),
                "external_packages": len(packages),
                "has_dangerous_imports": len(dangerous) > 0,
                "has_dangerous_os_operations": has_dangerous_os_ops,
                "estimated_install_time": self._estimate_install_time(packages),
                "estimated_size_mb": self._estimate_package_size(packages),
                "analysis_timestamp": None
            }
            
            # Add timestamp
            from datetime import datetime
            analysis["analysis_timestamp"] = datetime.now().isoformat()
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing code dependencies: {e}")
            return {
                "error": str(e),
                "imports_found": [],
                "packages_to_install": [],
                "builtin_modules": [],
                "dangerous_modules": [],
                "total_imports": 0,
                "external_packages": 0,
                "has_dangerous_imports": False,
                "estimated_install_time": 0,
                "estimated_size_mb": 0,
                "analysis_timestamp": datetime.now().isoformat()
            }
    
    def _estimate_install_time(self, packages: List[str]) -> int:
        """Estimate installation time in seconds for packages."""
        # Time estimates based on package complexity
        time_estimates = {
            # Fast packages (< 10 seconds)
            'requests': 5, 'httpx': 5, 'aiohttp': 8,
            'click': 3, 'typer': 5, 'rich': 8,
            'python-dateutil': 3, 'pytz': 2,
            'PyYAML': 5, 'toml': 3,
            'colorama': 2, 'tqdm': 3,
            'openai': 8, 'anthropic': 8,
            
            # Medium packages (10-30 seconds)
            'pandas': 25, 'numpy': 15, 'scipy': 30,
            'Pillow': 15, 'opencv-python': 45,
            'beautifulsoup4': 8, 'lxml': 20,
            'scikit-learn': 40, 'matplotlib': 35,
            'fastapi': 12, 'uvicorn': 8,
            'pydantic': 10, 'sqlalchemy': 15,
            'psycopg2-binary': 10, 'PyMySQL': 5,
            'redis': 8, 'celery': 15,
            'nltk': 20, 'spacy': 30, 'textblob': 15,
            
            # Slow packages (30+ seconds)
            'tensorflow': 180, 'torch': 240,
            'transformers': 120, 'datasets': 60,
            'xgboost': 45, 'lightgbm': 30,
            'selenium': 25, 'scrapy': 20,
            'django': 20, 'flask': 8,
        }
        
        total_time = 0
        for package in packages:
            # Use specific estimate if available, otherwise default
            if package in time_estimates:
                total_time += time_estimates[package]
            else:
                # Default estimate based on package name patterns
                if any(ml_lib in package.lower() for ml_lib in ['torch', 'tensorflow', 'transform']):
                    total_time += 120  # ML packages are slow
                elif any(data_lib in package.lower() for data_lib in ['pandas', 'numpy', 'scipy']):
                    total_time += 20   # Data packages are medium
                else:
                    total_time += 10   # Default for unknown packages
        
        return total_time
    
    def _estimate_package_size(self, packages: List[str]) -> int:
        """Estimate total size in MB for packages."""
        # Size estimates in MB
        size_estimates = {
            # Small packages (< 10 MB)
            'requests': 2, 'httpx': 3, 'aiohttp': 5,
            'click': 1, 'typer': 2, 'rich': 8,
            'python-dateutil': 1, 'pytz': 1,
            'PyYAML': 2, 'toml': 1,
            'colorama': 1, 'tqdm': 2,
            'openai': 5, 'anthropic': 5,
            'beautifulsoup4': 2, 'fastapi': 5,
            'pydantic': 3, 'PyMySQL': 2,
            'redis': 3, 'textblob': 8,
            
            # Medium packages (10-100 MB)
            'pandas': 40, 'numpy': 25, 'Pillow': 15,
            'lxml': 20, 'matplotlib': 50, 'scipy': 80,
            'scikit-learn': 60, 'uvicorn': 5,
            'sqlalchemy': 15, 'psycopg2-binary': 8,
            'celery': 12, 'nltk': 30, 'spacy': 50,
            
            # Large packages (100+ MB)
            'opencv-python': 150, 'tensorflow': 500,
            'torch': 800, 'transformers': 200,
            'datasets': 100, 'xgboost': 80,
            'lightgbm': 40, 'selenium': 25,
        }
        
        total_size = 0
        for package in packages:
            if package in size_estimates:
                total_size += size_estimates[package]
            else:
                # Default estimate
                if any(ml_lib in package.lower() for ml_lib in ['torch', 'tensorflow', 'transform']):
                    total_size += 300  # ML packages are large
                elif any(data_lib in package.lower() for data_lib in ['pandas', 'numpy', 'scipy', 'opencv']):
                    total_size += 50   # Data packages are medium-large
                else:
                    total_size += 10   # Default for unknown packages
        
        return total_size
    
    def validate_packages(self, packages: List[str]) -> Tuple[List[str], List[str]]:
        """
        Validate packages against security and compatibility rules.
        
        Args:
            packages: List of package names to validate
            
        Returns:
            Tuple of (allowed_packages, blocked_packages)
        """
        allowed = []
        blocked = []
        
        # Security rules
        dangerous_patterns = [
            'subprocess', 'os', 'sys', 'ctypes', 'importlib',
            'eval', 'exec', 'compile', 'code'
        ]
        
        # Known problematic packages
        problematic_packages = {
            'tensorflow-gpu',  # GPU version might not work
            'torch-audio',     # Audio processing might have issues
            'pyautogui',       # GUI automation (security risk)
            'keyboard',        # Keyboard capture (security risk)
            'mouse',           # Mouse capture (security risk)
            'pynput',          # Input capture (security risk)
            'win32api',        # Windows-specific (compatibility)
            'pywin32',         # Windows-specific (compatibility)
        }
        
        for package in packages:
            package_lower = package.lower()
            
            # Check for dangerous patterns
            if any(pattern in package_lower for pattern in dangerous_patterns):
                blocked.append(package)
                continue
            
            # Check for problematic packages
            if package in problematic_packages:
                blocked.append(package)
                continue
            
            # Package is allowed
            allowed.append(package)
        
        return allowed, blocked
    
    def get_package_info(self, package_name: str) -> Dict:
        """Get information about a specific package."""
        return {
            "name": package_name,
            "estimated_install_time": self._estimate_install_time([package_name]),
            "estimated_size_mb": self._estimate_package_size([package_name]),
            "is_common": package_name in self.COMMON_PACKAGES,
            "pip_name": self.IMPORT_TO_PACKAGE.get(package_name, package_name)
        }

# Initialize the service
dependency_detector = DependencyDetector()
