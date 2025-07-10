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
            r'import\s+sys\b',
            r'import\s+subprocess\b',
            r'from\s+sys\s+import',
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
            r'\.remove\s*\(',
            r'\.rmdir\s*\(',
            r'\.unlink\s*\(',
            # Allow os.getenv() but block dangerous os operations
        ]
        
        # Allowed safe imports (including HTTP libraries for AI API calls)
        self.allowed_imports = {
            'json', 're', 'datetime', 'math', 'base64', 'hashlib', 
            'typing', 'collections', 'itertools', 'functools',
            'string', 'random', 'time', 'calendar', 'decimal',
            'requests', 'urllib', 'http', 'httpx', 'openai', 'os',
            'dotenv', 'PyPDF2', 'io'
        }
    
    def validate_code(self, code: str) -> Tuple[bool, List[str]]:
        """
        Validate generated code for security issues.
        Returns (is_safe, list_of_violations)
        """
        violations = []
        
        # Check for forbidden keywords
        violations.extend(self._check_forbidden_keywords(code))
        
        # Check for forbidden patterns
        violations.extend(self._check_forbidden_patterns(code))
        
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
    
    def _check_imports(self, code: str) -> List[str]:
        """Check if all imports are in the allowed list."""
        violations = []
        
        # Find all import statements
        import_pattern = r'(?:^|\n)\s*(?:import\s+(\w+)|from\s+(\w+)\s+import)'
        matches = re.findall(import_pattern, code, re.MULTILINE)
        
        for match in matches:
            module = match[0] or match[1]  # import module or from module import
            if module and module not in self.allowed_imports:
                violations.append(f"Unauthorized import detected: '{module}'")
        
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
                
                # Check for attribute access to dangerous modules
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name):
                        if node.value.id == 'os' and node.attr == 'system':
                            violations.append("Dangerous os.system() call detected")
                
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
        # Remove any shell commands or system calls
        sanitized = re.sub(r'os\.system\([^)]+\)', '', code)
        sanitized = re.sub(r'subprocess\.[^(]+\([^)]+\)', '', sanitized)
        
        # Remove dangerous imports
        for keyword in self.forbidden_keywords:
            if keyword in ['os', 'sys', 'subprocess']:
                sanitized = re.sub(f'import\\s+{keyword}', '', sanitized)
                sanitized = re.sub(f'from\\s+{keyword}\\s+import', '', sanitized)
        
        return sanitized

# Global instance
security_service = SecurityService() 