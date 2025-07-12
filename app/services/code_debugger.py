import ast
import re
import logging
from typing import Tuple, List, Dict, Any
from ..config import settings
from .claude_service import claude_service

logger = logging.getLogger(__name__)

class CodeDebugger:
    def __init__(self):
        self.claude_service = claude_service
    
    async def analyze_and_fix_code(self, generated_code: str, original_prompt: str) -> Tuple[str, List[str], List[str]]:
        """
        Analyze generated code for issues and fix them using AI.
        
        Returns:
            - fixed_code: The corrected code
            - issues_found: List of issues that were detected
            - fixes_applied: List of fixes that were applied
        """
        logger.info("Starting code analysis and debugging...")
        
        # Step 1: Static analysis to find obvious issues
        issues_found = await self._static_analysis(generated_code)
        
        # Step 2: Use AI to analyze and fix the code
        if issues_found:
            logger.info(f"Found {len(issues_found)} issues, applying AI fixes...")
            fixed_code, fixes_applied = await self._ai_code_review_and_fix(
                generated_code, issues_found, original_prompt
            )
        else:
            logger.info("No obvious issues found in static analysis")
            fixed_code = generated_code
            fixes_applied = []
        
        # Step 3: Final validation
        final_issues = await self._validate_fixed_code(fixed_code)
        
        if final_issues:
            logger.warning(f"Still has {len(final_issues)} issues after fixing")
            # Try one more AI fix round
            fixed_code, additional_fixes = await self._ai_code_review_and_fix(
                fixed_code, final_issues, original_prompt
            )
            fixes_applied.extend(additional_fixes)
        
        logger.info(f"Code debugging completed. Applied {len(fixes_applied)} fixes.")
        return fixed_code, issues_found, fixes_applied
    
    async def _static_analysis(self, code: str) -> List[str]:
        """Perform static analysis to find common issues."""
        issues = []
        
        # Check for syntax errors
        try:
            ast.parse(code)
        except SyntaxError as e:
            issues.append(f"Syntax Error: {str(e)} at line {e.lineno}")
        
        # Check for duplicate return statements
        lines = code.split('\n')
        return_lines = []
        for i, line in enumerate(lines):
            if line.strip().startswith('return ') and line.strip() != 'return':
                return_lines.append(i + 1)
        
        if len(return_lines) > 1:
            # Check if they're in different blocks (acceptable) or same block (issue)
            return_blocks = self._analyze_return_blocks(code, return_lines)
            if return_blocks['duplicates']:
                issues.append(f"Duplicate return statements found at lines: {return_blocks['duplicates']}")
        
        # Check for missing imports
        import_issues = self._check_missing_imports(code)
        issues.extend(import_issues)
        
        # Check for hardcoded API keys
        if '"your-api-key-here"' in code or "'your-api-key-here'" in code:
            issues.append("Hardcoded API key placeholder found")
        
        # Check for required function signature
        if 'def run(' not in code:
            issues.append("Missing required 'run()' function")
        
        # Check for proper error handling structure
        if 'except Exception as e:' in code:
            except_blocks = self._analyze_exception_handling(code)
            issues.extend(except_blocks)
        
        return issues
    
    def _analyze_return_blocks(self, code: str, return_lines: List[int]) -> Dict[str, List[int]]:
        """Analyze return statements to find duplicates in same block."""
        lines = code.split('\n')
        duplicates = []
        
        # Simple heuristic: if return statements are close together (within 5 lines)
        # and not separated by except/try blocks, they're likely duplicates
        for i in range(len(return_lines) - 1):
            current_line = return_lines[i]
            next_line = return_lines[i + 1]
            
            if next_line - current_line <= 5:
                # Check if there's a try/except block between them
                between_lines = lines[current_line:next_line]
                has_block_separator = any(
                    'except' in line or 'try:' in line or 'if ' in line 
                    for line in between_lines
                )
                
                if not has_block_separator:
                    duplicates.extend([current_line, next_line])
        
        return {'duplicates': list(set(duplicates))}
    
    def _check_missing_imports(self, code: str) -> List[str]:
        """Check for missing imports based on usage."""
        issues = []
        
        # Common patterns
        import_patterns = {
            'json.': 'import json',
            'datetime.': 'from datetime import datetime',
            'os.getenv': 'import os',
            'io.BytesIO': 'import io',
            'PyPDF2.': 'import PyPDF2',
            're.': 'import re'
        }
        
        for pattern, required_import in import_patterns.items():
            if pattern in code and required_import not in code:
                issues.append(f"Missing import: {required_import}")
        
        return issues
    
    def _analyze_exception_handling(self, code: str) -> List[str]:
        """Analyze exception handling for issues."""
        issues = []
        
        # Check for empty except blocks
        if 'except Exception as e:\n        pass' in code:
            issues.append("Empty exception handler found")
        
        # Check for missing return in except blocks
        except_blocks = re.findall(r'except Exception as e:(.*?)(?=\n    [a-zA-Z]|\n[a-zA-Z]|\Z)', code, re.DOTALL)
        for block in except_blocks:
            if 'return' not in block:
                issues.append("Exception handler missing return statement")
        
        return issues
    
    async def _ai_code_review_and_fix(self, code: str, issues: List[str], original_prompt: str) -> Tuple[str, List[str]]:
        """Use AI to review and fix the code issues."""
        
        system_prompt = """You are an expert Python code reviewer and debugger. Your job is to fix code issues while maintaining the original functionality.

CRITICAL RULES:
1. Fix ONLY the specific issues mentioned
2. Maintain the original function signature: def run(file_bytes=None, input_data=None)
3. Keep the same return format: {"result": data, "message": "success"} or {"error": str, "message": "failed"}
4. Do NOT change the core logic or functionality
5. Do NOT add new features or requirements
6. Fix syntax errors, remove duplicates, add missing imports
7. Ensure proper Python syntax and indentation
8. Use os.getenv() for API keys, never hardcode them
9. Return ONLY the corrected Python code, no explanations

COMMON FIXES:
- Remove duplicate return statements
- Fix syntax errors (missing colons, parentheses, etc.)
- Add missing imports
- Fix indentation issues
- Replace hardcoded API keys with os.getenv()
- Ensure proper exception handling"""

        user_prompt = f"""Please fix the following Python code issues:

ORIGINAL PROMPT: {original_prompt}

ISSUES FOUND:
{chr(10).join(f"- {issue}" for issue in issues)}

CODE TO FIX:
```python
{code}
```

Return the corrected code with all issues fixed. Maintain the same functionality and structure."""

        try:
            response = await self.claude_service._make_claude_request(system_prompt, user_prompt)
            fixed_code = self._extract_code_from_response(response)
            
            # Determine what fixes were applied
            fixes_applied = self._determine_fixes_applied(code, fixed_code, issues)
            
            return fixed_code, fixes_applied
            
        except Exception as e:
            logger.error(f"Failed to fix code with AI: {str(e)}")
            return code, []
    
    def _extract_code_from_response(self, response: str) -> str:
        """Extract Python code from AI response."""
        if "```python" in response:
            start = response.find("```python") + 9
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        
        return response.strip()
    
    def _determine_fixes_applied(self, original_code: str, fixed_code: str, issues: List[str]) -> List[str]:
        """Determine what fixes were actually applied."""
        fixes_applied = []
        
        # Check for syntax fixes
        try:
            ast.parse(original_code)
        except SyntaxError:
            try:
                ast.parse(fixed_code)
                fixes_applied.append("Fixed syntax errors")
            except SyntaxError:
                pass
        
        # Check for duplicate return removal
        original_returns = len(re.findall(r'return \{', original_code))
        fixed_returns = len(re.findall(r'return \{', fixed_code))
        if original_returns > fixed_returns:
            fixes_applied.append("Removed duplicate return statements")
        
        # Check for import additions
        original_imports = len(re.findall(r'^import |^from .* import', original_code, re.MULTILINE))
        fixed_imports = len(re.findall(r'^import |^from .* import', fixed_code, re.MULTILINE))
        if fixed_imports > original_imports:
            fixes_applied.append("Added missing imports")
        
        # Check for API key fixes
        if '"your-api-key-here"' in original_code and '"your-api-key-here"' not in fixed_code:
            fixes_applied.append("Fixed hardcoded API key")
        
        return fixes_applied
    
    async def _validate_fixed_code(self, code: str) -> List[str]:
        """Validate the fixed code for remaining issues."""
        remaining_issues = []
        
        # Check syntax
        try:
            ast.parse(code)
        except SyntaxError as e:
            remaining_issues.append(f"Syntax Error: {str(e)}")
        
        # Check for required function
        if 'def run(' not in code:
            remaining_issues.append("Missing required 'run()' function")
        
        # Check for duplicate returns (simple check)
        return_count = len(re.findall(r'return \{.*?"result":', code))
        if return_count > 1:
            remaining_issues.append("Still has duplicate return statements")
        
        return remaining_issues

# Global instance
code_debugger = CodeDebugger() 