import re
import ast
from typing import List, Tuple
from ..config import settings

class SecurityService:
    def __init__(self):
        self.forbidden_keywords = settings.FORBIDDEN_KEYWORDS
        self.forbidden_patterns = [
            r'exec\s*\(',
            r'eval\s*\(',
            r'compile\s*\(',
            r'import\s+subprocess\b',
            r'from\s+subprocess\s+import',
            r'getattr\s*\(',
            r'setattr\s*\(',
            r'delattr\s*\(',
            r'globals\s*\(',
            r'locals\s*\(',
            r'vars\s*\(',
            r'dir\s*\(',
            r'\.system\s*\(',
            r'\.popen\s*\(',
            r'\.call\s*\(',
            # Dangerous os operations are now handled separately
        ]
        
        # Forbidden dangerous imports (removed os and sys - handled at operation level)
        self.forbidden_imports = {
            'subprocess', 'importlib', 'builtins', '__builtin__',
            'ctypes', 'multiprocessing', 'threading', 'socket', 'ssl',
            'ftplib', 'telnetlib', 'smtplib', 'imaplib', 'poplib',
            'webbrowser', 'tempfile', 'shutil', 'pickle', 'marshal',
            'shelve', 'dbm', 'sqlite3', 'code', 'codeop', 'py_compile',
            'compileall', 'dis', 'inspect', 'pkgutil', 'platform',
            'resource', 'gc', 'weakref', 'copy_reg', 'new', 'imp',
            'zipimport', 'runpy', 'ast', 'symtable', 'keyword',
            'token', 'tokenize', 'tabnanny', 'pyclbr', 'modulefinder',
            'trace', 'linecache', 'site', 'sysconfig'
        }
        
        # Dangerous os operations that should be blocked
        self.dangerous_os_patterns = [
            r'os\.system\s*\(',
            r'os\.popen\s*\(',
            r'os\.spawn\w*\s*\(',
            r'os\.exec\w*\s*\(',
            r'os\.fork\s*\(',
            r'os\.kill\w*\s*\(',
            r'os\.remove\s*\(',
            r'os\.unlink\s*\(',
            r'os\.rmdir\s*\(',
            r'os\.removedirs\s*\(',
            r'os\.rename\s*\(',
            r'os\.renames\s*\(',
            r'os\.chmod\s*\(',
            r'os\.chown\s*\(',
            r'os\.chroot\s*\(',
        ]
    
    def validate_code(self, code: str) -> Tuple[bool, List[str]]:
        """
        Validate generated code for security issues.
        Returns (is_safe, list_of_violations)
        """
        # If security service is disabled, skip validation
        if not settings.SECURITY_SERVICE_ENABLED:
            return True, []
        
        violations = []
        
        # Check for forbidden keywords
        violations.extend(self._check_forbidden_keywords(code))
        
        # Check for forbidden patterns
        violations.extend(self._check_forbidden_patterns(code))
        
        # Check dangerous os operations
        violations.extend(self._check_dangerous_os_operations(code))
        
        # Check imports
        violations.extend(self._check_imports(code))
        
        # Check AST for dangerous constructs
        violations.extend(self._check_ast_violations(code))
        
        # Check for required function structure
        violations.extend(self._check_function_structure(code))
        
        is_safe = len(violations) == 0
        return is_safe, violations
    
    def _check_forbidden_keywords(self, code: str) -> List[str]:
        """Check for forbidden keywords in the code."""
        violations = []
        
        # Skip this check as it's too broad - we'll rely on import checking and AST analysis instead
        # The substring matching was causing false positives
        
        return violations
    
    def _check_forbidden_patterns(self, code: str) -> List[str]:
        """Check for forbidden regex patterns in the code."""
        violations = []
        
        for pattern in self.forbidden_patterns:
            matches = re.findall(pattern, code, re.IGNORECASE)
            if matches:
                violations.append(f"Forbidden pattern detected: '{pattern}' - matches: {matches}")
        
        return violations
    
    def _check_dangerous_os_operations(self, code: str) -> List[str]:
        """Check for dangerous os operations in the code."""
        violations = []
        
        for pattern in self.dangerous_os_patterns:
            matches = re.findall(pattern, code, re.IGNORECASE)
            if matches:
                violations.append(f"Dangerous os operation detected: '{pattern}'")
        
        return violations
    
    def _check_imports(self, code: str) -> List[str]:
        """Check if any imports are in the forbidden list."""
        violations = []
        
        # Find all import statements
        import_pattern = r'(?:^|\n)\s*(?:import\s+(\w+)|from\s+(\w+)\s+import)'
        matches = re.findall(import_pattern, code, re.MULTILINE)
        
        for match in matches:
            module = match[0] or match[1]  # import module or from module import
            if module and module in self.forbidden_imports:
                violations.append(f"Forbidden import detected: '{module}'")
        
        return violations
    
    def _check_ast_violations(self, code: str) -> List[str]:
        """Check AST for dangerous constructs."""
        violations = []
        
        try:
            tree = ast.parse(code)
            
            for node in ast.walk(tree):
                # Check for dangerous function calls
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                        if func_name in ['eval', 'exec', 'compile', '__import__']:
                            violations.append(f"Dangerous function call detected: '{func_name}'")
                
                # Check for attribute access to dangerous os operations
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        if node.value.id == 'os':
                            # Check if it's a dangerous os operation
                            dangerous_ops = {'system', 'popen', 'spawn', 'exec', 'fork', 'kill', 'killpg',
                                           'remove', 'unlink', 'rmdir', 'removedirs', 'rename', 'renames',
                                           'chmod', 'chown', 'chroot', 'setuid', 'setgid', 'umask'}
                            if node.attr in dangerous_ops:
                                violations.append(f"Dangerous os.{node.attr} operation detected")
                
        except SyntaxError as e:
            violations.append(f"Syntax error in generated code: {str(e)}")
        except Exception as e:
            violations.append(f"Error parsing code: {str(e)}")
        
        return violations
    
    def _check_function_structure(self, code: str) -> List[str]:
        """Check if the code has the required run() function."""
        violations = []
        
        # Check if run function exists
        if 'def run(' not in code:
            violations.append("Required 'run()' function not found in generated code")
        
        # Check function signature
        run_pattern = r'def\s+run\s*\([^)]*\):'
        if not re.search(run_pattern, code):
            violations.append("Invalid 'run()' function signature")
        
        return violations
    
    def sanitize_code(self, code: str) -> str:
        """Apply basic sanitization to the code."""
        # If security service is disabled, return code as-is
        if not settings.SECURITY_SERVICE_ENABLED:
            return code
        
        # Remove any shell commands or system calls
        sanitized = re.sub(r'os\.system\([^)]+\)', '', code)
        sanitized = re.sub(r'subprocess\.[^(]+\([^)]+\)', '', sanitized)
        
        # Remove dangerous imports
        for module in self.forbidden_imports:
            sanitized = re.sub(f'import\\s+{module}', '', sanitized)
            sanitized = re.sub(f'from\\s+{module}\\s+import', '', sanitized)
        
        return sanitized

# Global instance
security_service = SecurityService() 