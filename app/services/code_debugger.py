import ast
import re
import logging
import time
import asyncio
import uuid
from typing import Tuple, List, Dict, Any, Optional
from ..config import settings
from .claude_service import claude_service
from .usage_service import usage_service
from datetime import datetime
import json

logger = logging.getLogger(__name__)

class CodeDebugger:
    def __init__(self):
        self.claude_service = claude_service
        
        # Circuit breaker configuration
        self.circuit_breaker_config = {
            "max_failures": 3,  # Max consecutive failures before circuit opens
            "reset_timeout": 300,  # 5 minutes before attempting reset
            "failure_threshold": 0.5  # 50% failure rate threshold
        }
        
        # Circuit breaker state tracking
        self.circuit_breaker_state = {
            "is_open": False,
            "failure_count": 0,
            "last_failure_time": None,
            "total_attempts": 0,
            "total_failures": 0
        }
        
        # Rate limiting configuration
        self.rate_limit_config = {
            "max_debug_sessions_per_hour": 10,
            "max_iterations_per_session": 5,
            "min_interval_between_sessions": 30  # seconds
        }
        
        # Session tracking for rate limiting
        self.session_history = []
    
    async def analyze_and_fix_code(self, generated_code: str, original_prompt: str, 
                                  user_id: Optional[str] = None, api_key_id: Optional[str] = None) -> Tuple[str, List[str], List[str]]:
        """
        Analyze generated code for issues and fix them using AI.
        
        Returns:
            - fixed_code: The corrected code
            - issues_found: List of issues that were detected
            - fixes_applied: List of fixes that were applied
        """
        logger.info("Starting code analysis and debugging...")
        
        # SYNTAX CHECK: Log if code has syntax errors, but always continue with AI review
        try:
            import ast
            ast.parse(generated_code)
            logger.info("Generated code is syntactically valid, but will still run AI review")
        except SyntaxError as e:
            logger.info(f"Generated code has syntax errors: {e}, will attempt fixes...")
        
        # Step 1: Static analysis to find obvious issues
        issues_found = await self._static_analysis(generated_code)
        
        # Step 2: Try SIMPLE fixes first (no AI) - only if we found obvious issues
        simple_fixes_applied = []
        code_to_review = generated_code
        
        if issues_found:
            logger.info(f"Found {len(issues_found)} issues, trying simple fixes first...")
            try:
                simple_fixed = self._attempt_syntax_fixes(generated_code)
                ast.parse(simple_fixed)
                logger.info("Simple syntax fixes worked!")
                code_to_review = simple_fixed
                simple_fixes_applied = ["Applied simple syntax fixes"]
            except Exception as e:
                logger.info(f"Simple fixes failed: {e}, will try AI fixes...")
                code_to_review = generated_code
        
        # Step 3: ALWAYS use AI review - even if no issues found
        # The AI might catch issues our static analysis missed
        logger.info("Running AI code review (regardless of static analysis results)...")
        
        # Prepare issues list - include static issues + general review request
        all_issues = issues_found.copy() if issues_found else []
        if not all_issues:
            all_issues = ["General code review and validation requested"]
        
        fixed_code, ai_fixes_applied = await self._ai_code_review_and_fix(
            code_to_review, all_issues, original_prompt, user_id, api_key_id
        )
        
        # Combine all fixes applied
        fixes_applied = simple_fixes_applied + ai_fixes_applied
        
        # Step 4: Final validation - but don't try to fix again if it fails
        final_issues = await self._validate_fixed_code(fixed_code)
        
        if final_issues:
            logger.warning(f"Still has {len(final_issues)} issues after fixing")
            logger.warning("Not attempting additional fixes to avoid making it worse")
        
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
        
        # Check for dangerous os operations
        os_issues = self._check_dangerous_os_operations(code)
        issues.extend(os_issues)
        
        # Check for hardcoded API keys
        if '"your-api-key-here"' in code or "'your-api-key-here'" in code:
            issues.append("Hardcoded API key placeholder found")
        
        # Check for required function signature
        if 'def run(' not in code:
            issues.append("Missing required 'run()' function")
        
        # Check for unterminated triple quotes
        triple_quote_issues = self._check_triple_quotes(code)
        issues.extend(triple_quote_issues)
        
        # Check for proper error handling structure
        if 'except Exception as e:' in code:
            except_blocks = self._analyze_exception_handling(code)
            issues.extend(except_blocks)
        
        return issues
    
    def _check_triple_quotes(self, code: str) -> List[str]:
        """Check for unterminated triple quotes."""
        issues = []
        lines = code.split('\n')
        
        in_triple_quote = False
        triple_quote_start_line = 0
        
        for i, line in enumerate(lines):
            triple_quote_count = line.count('"""')
            
            # Handle multiple triple quotes on the same line
            for _ in range(triple_quote_count):
                if not in_triple_quote:
                    in_triple_quote = True
                    triple_quote_start_line = i + 1
                else:
                    in_triple_quote = False
        
        if in_triple_quote:
            issues.append(f"Unterminated triple-quoted string starting at line {triple_quote_start_line}")
        
        # Also check for specific malformed patterns
        for i, line in enumerate(lines):
            if 'f"""' in line and not line.rstrip().endswith('"""'):
                # Check if this is a malformed f-string
                if '"{' in line and '}"' in line:
                    issues.append(f"Malformed f-string with mixed quotes at line {i+1}")
        
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
            'os.path.': 'import os',
            'os.environ': 'import os',
            'os.getcwd': 'import os',
            'os.listdir': 'import os',
            'io.BytesIO': 'import io',
            'PyPDF2.': 'import PyPDF2',
            're.': 'import re'
        }
        
        for pattern, required_import in import_patterns.items():
            if pattern in code and required_import not in code:
                issues.append(f"Missing import: {required_import}")
        
        # Check for serialization issues
        if 'BaseModel(' in code or 'NameResult(' in code:
            issues.append("Using non-serializable Pydantic models in return data")
        
        if 'response_format={"type": "json_object"}' in code and 'raw_entities = json.loads' in code:
            if 'if not isinstance(raw_entities, list)' in code:
                issues.append("Incorrect assumption about OpenAI JSON object format")
        
        return issues
    
    def _check_dangerous_os_operations(self, code: str) -> List[str]:
        """Check for dangerous os operations and suggest safer alternatives."""
        issues = []
        
        # Dangerous os operations and their safer alternatives
        dangerous_patterns = {
            'os.system(': 'Use subprocess.run() with shell=False for safer command execution',
            'os.popen(': 'Use subprocess.Popen() for better control over process execution',
            'os.remove(': 'Consider using pathlib.Path.unlink() or add proper error handling',
            'os.rmdir(': 'Consider using pathlib.Path.rmdir() or shutil.rmtree() with proper checks',
            'os.unlink(': 'Consider using pathlib.Path.unlink() with proper error handling'
        }
        
        for pattern, suggestion in dangerous_patterns.items():
            if pattern in code:
                issues.append(f"Dangerous operation detected: {pattern} - {suggestion}")
        
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
    
    async def _ai_code_review_and_fix(self, code: str, issues: List[str], original_prompt: str,
                                      user_id: Optional[str] = None, api_key_id: Optional[str] = None) -> Tuple[str, List[str]]:
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
10. CRITICAL: Return only plain dictionaries/lists, never Pydantic model instances
11. Convert any Pydantic models to .model_dump() or dict() before returning
12. Handle OpenAI JSON object responses correctly (expect objects, not arrays)

COMMON FIXES:
- Remove duplicate return statements
- Fix syntax errors (missing colons, parentheses, etc.)
- Add missing imports
- Fix indentation issues
- Replace hardcoded API keys with os.getenv()
- Ensure proper exception handling
- Convert Pydantic models to plain dicts: NameResult(...) → {...}
- Fix OpenAI JSON parsing: expect {"entities": [...]} not [...]
- Ensure all return values are JSON-serializable (no class instances)
- Fix unterminated triple quotes: f\"\"\"text\"\"\" not f\"\"\"text\")
- Fix malformed f-strings: use {variable} not \"{variable}\""""

        # Adjust prompt based on whether we have specific issues or general review
        if "General code review and validation requested" in issues:
            user_prompt = f"""Please review and improve the following Python code:

ORIGINAL PROMPT: {original_prompt}

REVIEW REQUEST: Analyze this code for any issues including:
- Syntax errors or malformed statements
- Missing imports or dependencies
- Incorrect API usage patterns
- Logic errors or potential bugs
- Code structure and best practices

CODE TO REVIEW:
```python
{code}
```

If you find any issues, return the corrected code. If the code is already correct, return it unchanged.
Maintain the same functionality and structure."""
        else:
            user_prompt = f"""Please fix the following Python code issues:

ORIGINAL PROMPT: {original_prompt}

ISSUES FOUND:
{chr(10).join(f"- {issue}" for issue in issues)}

CODE TO FIX:
```python
{code}
```

Return the corrected code with all issues fixed. Maintain the same functionality and structure."""

        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self.claude_service._make_claude_request(system_prompt, user_prompt)
            fixed_code = self._extract_code_from_response(response)
            
            # Determine what fixes were applied
            fixes_applied = self._determine_fixes_applied(code, fixed_code, issues)
            
            # If no fixes were applied and this was a general review, note that
            if not fixes_applied and "General code review and validation requested" in issues:
                fixes_applied = ["Code reviewed by AI - no issues found"]
            
            success = True
            response_length = len(fixed_code)
            
            return fixed_code, fixes_applied
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to fix code with AI: {str(e)}")
            # Try to apply our own syntax fixes as fallback
            try:
                fallback_fixed = self._attempt_syntax_fixes(code)
                # Validate the fallback fix
                import ast
                ast.parse(fallback_fixed)
                logger.info("Applied fallback syntax fixes successfully")
                return fallback_fixed, ["Applied fallback syntax fixes"]
            except Exception as fallback_error:
                logger.error(f"Fallback fixes also failed: {fallback_error}")
                # CIRCUIT BREAKER: Don't return broken code, return original
                logger.warning("All fixing attempts failed, returning original code")
                return code, []
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="code_debugging",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "issues_count": len(issues),
                            "original_prompt_preview": original_prompt[:100] + "..." if len(original_prompt) > 100 else original_prompt,
                            "issues_found": issues[:3]  # First 3 issues for context
                        },
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")
    
    async def fix_unvalid_test_result(self, code: str, test_result: str, 
                                      user_id: Optional[str] = None, api_key_id: Optional[str] = None,
                                      api_slug: Optional[str] = None) -> Tuple[str, List[str]]:
        """
        Fix code based on invalid test results.
        
        Args:
            code: The original API code that produced invalid results
            test_result: The test result that was deemed invalid (JSON string or error message)
            
        Returns:
            Tuple of (fixed_code, list_of_fixes_applied)
        """
        logger.info("Starting test result-based code debugging...")
        
        system_prompt = """You are an expert Python code debugger specializing in fixing API code based on test result analysis.

        Your job is to analyze failed or invalid test results and fix the underlying code issues while maintaining the original functionality.

        CRITICAL RULES:
        1. Maintain the original function signature: def run(file_bytes=None, input_data=None)
        2. Keep the same return format: {"result": data, "message": "success"} or {"error": str, "message": "failed"}
        3. Fix ONLY the specific issues causing the invalid test results
        4. Do NOT change the core logic unless it's clearly broken
        5. Ensure proper Python syntax and indentation
        6. Use os.getenv() for API keys, never hardcode them
        7. Add proper error handling if missing
        8. Return ONLY the corrected Python code, no explanations
        9. CRITICAL: Return only plain dictionaries/lists, never Pydantic model instances
        10. Convert any Pydantic models to .model_dump() or dict() before returning
        11. Handle OpenAI JSON object responses correctly (expect objects, not arrays)

        COMMON TEST FAILURE PATTERNS TO FIX:
        - Syntax errors (missing colons, parentheses, indentation)
        - Missing imports for used libraries
        - Incorrect API call patterns (deprecated OpenAI methods)
        - Missing error handling causing crashes
        - Wrong data types being returned
        - API key configuration issues
        - File handling errors (not using io.BytesIO for binary data)
        - JSON parsing errors
        - Network timeout issues
        - Incorrect response formatting
        - PICKLING ERRORS: Returning Pydantic model instances instead of plain dicts
        - STRING INDEXING ERRORS: Treating OpenAI JSON objects as arrays
        - SERIALIZATION ERRORS: Non-JSON-serializable objects in return data"""

        user_prompt = f"""Please analyze this test failure and fix the code:

        TEST RESULT ANALYSIS:
        {test_result}

        CODE TO FIX:
        ```python
        {code}
        ```

        Based on the test result, identify and fix the specific issues causing the failure. Return the corrected code that should pass the test."""

        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self.claude_service._make_claude_request(system_prompt, user_prompt)
            fixed_code = self._extract_code_from_response(response)
            
            # Determine what fixes were applied by comparing the codes
            fixes_applied = self._determine_test_fixes_applied(code, fixed_code, test_result)
            
            success = True
            response_length = len(fixed_code)
            
            logger.info(f"Test result debugging completed. Applied {len(fixes_applied)} fixes.")
            return fixed_code, fixes_applied
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to fix code based on test result: {str(e)}")
            return code, []
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="test_result_debugging",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "test_result_preview": test_result[:200] + "..." if len(test_result) > 200 else test_result,
                            "code_length": len(code)
                        },
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")

    def _determine_test_fixes_applied(self, original_code: str, fixed_code: str, test_result: str) -> List[str]:
        """Determine what fixes were applied based on test results."""
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
        
        # Check for import additions
        original_imports = len(re.findall(r'^import |^from .* import', original_code, re.MULTILINE))
        fixed_imports = len(re.findall(r'^import |^from .* import', fixed_code, re.MULTILINE))
        if fixed_imports > original_imports:
            fixes_applied.append("Added missing imports")
        
        # Check for API key fixes
        if '"your-api-key-here"' in original_code and '"your-api-key-here"' not in fixed_code:
            fixes_applied.append("Fixed hardcoded API key")
        
        # Check for deprecated OpenAI patterns
        if 'openai.Completion.create' in original_code and 'openai.Completion.create' not in fixed_code:
            fixes_applied.append("Fixed deprecated OpenAI API calls")
        
        # Check for error handling improvements
        original_try_blocks = len(re.findall(r'try:', original_code))
        fixed_try_blocks = len(re.findall(r'try:', fixed_code))
        if fixed_try_blocks > original_try_blocks:
            fixes_applied.append("Added error handling")
        
        # Check for io.BytesIO fixes
        if 'io.BytesIO' not in original_code and 'io.BytesIO' in fixed_code:
            fixes_applied.append("Fixed file handling with io.BytesIO")
        
        # Analyze test result for specific issues
        if 'error' in test_result.lower():
            if 'timeout' in test_result.lower() and 'timeout' in fixed_code:
                fixes_applied.append("Added timeout handling")
            if 'json' in test_result.lower() and 'json.loads' in fixed_code and 'json.loads' not in original_code:
                fixes_applied.append("Fixed JSON parsing")
            if 'api key' in test_result.lower():
                fixes_applied.append("Fixed API key configuration")
        
        return fixes_applied

    async def debug_test_failure(self, code: str, test_request: dict, test_response: dict,
                                 user_id: Optional[str] = None, api_key_id: Optional[str] = None,
                                 api_slug: Optional[str] = None) -> Tuple[str, List[str], Dict[str, Any]]:
        """
        Comprehensive test failure debugging with detailed analysis.
        
        Args:
            code: The API code that failed
            test_request: The test request data
            test_response: The test response data
            
        Returns:
            Tuple of (fixed_code, fixes_applied, debug_info)
        """
        logger.info("Starting comprehensive test failure debugging...")
        
        # Extract error information
        error_info = self._extract_error_info(test_response)
        
        # Perform static analysis on the code
        static_issues = await self._static_analysis(code)
        
        # Analyze test patterns
        test_analysis = self._analyze_test_patterns(test_request, test_response)
        
        # Create comprehensive debug prompt
        system_prompt = """You are an expert Python debugger specializing in API testing and failure analysis.

Analyze the test failure and fix the code while maintaining the original functionality.

CRITICAL REQUIREMENTS:
1. Keep function signature: def run(file_bytes=None, input_data=None)
2. Maintain return format: {"result": data, "message": "success"} or {"error": str, "message": "failed"}
3. Fix specific issues causing test failures
4. Add proper error handling
5. Use modern API patterns
6. Return only corrected Python code

ANALYSIS APPROACH:
1. Identify the root cause of the test failure
2. Fix syntax, import, and runtime errors
3. Improve error handling and robustness
4. Ensure proper data type handling
5. Fix API integration issues"""

        user_prompt = f"""COMPREHENSIVE TEST FAILURE ANALYSIS:

ERROR INFORMATION:
{error_info}

STATIC CODE ISSUES:
{static_issues}

TEST PATTERN ANALYSIS:
{test_analysis}

TEST REQUEST:
{test_request}

TEST RESPONSE:
{test_response}

CODE TO DEBUG:
```python
{code}
```

Please analyze all the information above and provide a fixed version of the code that addresses the identified issues."""

        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self.claude_service._make_claude_request(system_prompt, user_prompt)
            fixed_code = self._extract_code_from_response(response)
            
            # Determine fixes applied
            fixes_applied = self._determine_comprehensive_fixes(code, fixed_code, error_info, static_issues)
            
            # Create debug info
            debug_info = {
                "error_info": error_info,
                "static_issues": static_issues,
                "test_analysis": test_analysis,
                "fixes_applied": fixes_applied,
                "debug_timestamp": datetime.now().isoformat()
            }
            
            success = True
            response_length = len(fixed_code)
            
            logger.info(f"Comprehensive debugging completed. Applied {len(fixes_applied)} fixes.")
            return fixed_code, fixes_applied, debug_info
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed comprehensive test debugging: {str(e)}")
            return code, [], {"error": str(e)}
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="comprehensive_debugging",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "error_type": error_info.get("error_type"),
                            "static_issues_count": len(static_issues),
                            "test_analysis": test_analysis
                        },
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")

    def _extract_code_from_response(self, response: str) -> str:
        """Extract Python code from AI response and validate it."""
        code = ""
        
        # Extract code from markdown blocks
        if "```python" in response:
            start = response.find("```python") + 9
            end = response.find("```", start)
            if end != -1:
                code = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                code = response[start:end].strip()
        else:
            code = response.strip()
        
        # Clean up common issues in extracted code
        code = self._clean_extracted_code(code)
        
        # Validate code syntax
        try:
            import ast
            ast.parse(code)
        except SyntaxError as e:
            logger.error(f"Syntax error in extracted code: {e}")
            # Try to fix common issues
            fixed_code = self._attempt_syntax_fixes(code)
            try:
                ast.parse(fixed_code)
                code = fixed_code
                logger.info("Successfully fixed syntax error in extracted code")
            except SyntaxError as e2:
                logger.error(f"Failed to fix syntax error: {e2}")
                raise Exception(f"Generated code has syntax errors: {str(e2)}")
        
        # Ensure code is not empty and has proper structure
        if not code or 'def run(' not in code:
            raise Exception("Invalid code: missing run() function")
        
        return code
    
    def _clean_extracted_code(self, code: str) -> str:
        """Clean up common issues in extracted code."""
        # Remove trailing markdown blocks
        if code.endswith('```'):
            code = code[:-3].strip()
        
        # Remove leading/trailing whitespace
        code = code.strip()
        
        # Fix common encoding issues
        code = code.replace('\u201c', '"').replace('\u201d', '"')  # Smart quotes
        code = code.replace('\u2018', "'").replace('\u2019', "'")  # Smart apostrophes
        
        return code
    
    def _attempt_syntax_fixes(self, code: str) -> str:
        """Attempt to fix common syntax errors in code - CONSERVATIVE approach."""
        lines = code.split('\n')
        fixed_lines = []
        
        # Track what we're fixing to avoid conflicts
        bracket_stack = []
        in_triple_quote = False
        
        for i, line in enumerate(lines):
            original_line = line
            
            # Only fix OBVIOUS single-line issues
            
            # 1. Fix simple unclosed triple quotes (only if clearly on same line)
            if line.count('"""') == 1 and ('f"""' in line or 'prompt = """' in line):
                if not line.rstrip().endswith('"""'):
                    line = line.rstrip() + '"""'
                    logger.info(f"Fixed unclosed triple quote on line {i+1}")
            
            # 2. Fix simple bracket issues (only if clearly a single statement)
            if line.strip().startswith('messages=[') and not ']' in line:
                # This is the specific pattern from your error
                line = line.rstrip() + ']'
                logger.info(f"Fixed unclosed bracket on line {i+1}")
            
            # 3. Fix simple parenthesis issues (only for function calls)
            if ('(' in line and ')' not in line and 
                ('create(' in line or 'OpenAI(' in line or 'client.' in line)):
                # Only fix if it's clearly a single function call
                open_count = line.count('(')
                if open_count == 1:
                    line = line.rstrip() + ')'
                    logger.info(f"Fixed unclosed parenthesis on line {i+1}")
            
            # 4. Don't fix anything else - too risky
            
            fixed_lines.append(line)
        
        return '\n'.join(fixed_lines)
    
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

    async def validate_and_fix_test_result(self, code: str, test_request: dict, test_response: dict, 
                                          original_prompt: str = "", user_id: Optional[str] = None,
                                          api_key_id: Optional[str] = None, api_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Validate test results and automatically fix code if invalid.
        
        Args:
            code: The API code that was tested
            test_request: The test request data
            test_response: The test response data
            original_prompt: The original prompt used to generate the API
            
        Returns:
            Dict containing validation results, fixed code (if needed), and debug info
        """
        logger.info("Starting comprehensive test result validation and fixing...")
        
        # First, determine if the test result is valid
        validation_result = await self._validate_test_result_logic(test_request, test_response, user_id, api_key_id, api_slug)
        
        result = {
            "is_valid": validation_result["is_valid"],
            "validation_confidence": validation_result["confidence"],
            "validation_message": validation_result["message"],
            "issues_found": validation_result["issues"],
            "original_code": code,
            "fixed_code": None,
            "fixes_applied": [],
            "debug_info": None,
            "needs_code_fix": False
        }
        
        # If test result is invalid, attempt to fix the code
        if not validation_result["is_valid"]:
            logger.info("Test result is invalid, attempting to fix the code...")
            result["needs_code_fix"] = True
            
            try:
                # Use comprehensive debugging
                fixed_code, fixes_applied, debug_info = await self.debug_test_failure(
                    code, test_request, test_response, user_id, api_key_id, api_slug
                )
                
                result.update({
                    "fixed_code": fixed_code,
                    "fixes_applied": fixes_applied,
                    "debug_info": debug_info
                })
                
                logger.info(f"Code fixing completed. Applied {len(fixes_applied)} fixes.")
                
            except Exception as e:
                logger.error(f"Failed to fix invalid test result: {str(e)}")
                result["debug_info"] = {"error": str(e)}
        
        return result

    async def _validate_test_result_logic(self, test_request: dict, test_response: dict,
                                          user_id: Optional[str] = None, api_key_id: Optional[str] = None,
                                          api_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Use AI to validate if a test result makes logical sense.
        
        Returns:
            Dict with validation results
        """
        system_prompt = """You are an expert API testing analyst. Your job is to determine if an API test result is logically valid.

VALIDATION CRITERIA:
1. LOGICAL CONSISTENCY: Does the output logically follow from the input?
2. DATA COHERENCE: Are the response values reasonable and properly formatted?
3. COMPLETENESS: Does the response address what was requested?
4. CORRECTNESS: Are there obvious errors or inconsistencies?
5. FORMAT VALIDITY: Is the response structure appropriate?

RETURN FORMAT (JSON):
{
    "is_valid": true/false,
    "confidence": 0.0-1.0,
    "message": "Clear explanation",
    "issues": ["list", "of", "specific", "issues"],
    "reasoning": "Brief reasoning focusing on input-output logic"
}"""

        user_prompt = f"""VALIDATE THIS API TEST RESULT:

TEST INPUT:
{test_request.get('test_data', 'No input data')}

TEST OUTPUT:
{test_response.get('response_data', 'No output data')}

EXECUTION DETAILS:
- Success: {test_response.get('success', False)}
- Status Code: {test_response.get('status_code', 'N/A')}
- Execution Time: {test_response.get('execution_time', 0)}s
- Error: {test_response.get('error', 'None')}

Analyze if this test result is logically valid and return your assessment as JSON."""

        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self.claude_service._make_claude_request(system_prompt, user_prompt)
            
            success = True
            response_length = len(response)
            
            # Parse AI response
            try:
                # Clean up the response and extract JSON more robustly
                cleaned_response = response.strip()
                
                # Remove markdown code blocks if present
                if cleaned_response.startswith("```json"):
                    start = cleaned_response.find("{")
                    end = cleaned_response.rfind("}") + 1
                    if start != -1 and end != 0:
                        cleaned_response = cleaned_response[start:end]
                elif cleaned_response.startswith("```"):
                    lines = cleaned_response.split('\n')
                    cleaned_response = '\n'.join(lines[1:-1])
                
                # Extract just the JSON object if there's extra content
                if '{' in cleaned_response:
                    start = cleaned_response.find('{')
                    # Find the matching closing brace
                    brace_count = 0
                    end = start
                    for i in range(start, len(cleaned_response)):
                        if cleaned_response[i] == '{':
                            brace_count += 1
                        elif cleaned_response[i] == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end = i + 1
                                break
                    cleaned_response = cleaned_response[start:end]
                
                validation_result = json.loads(cleaned_response)
                
                # Ensure required fields
                validation_result.setdefault("is_valid", False)
                validation_result.setdefault("confidence", 0.0)
                validation_result.setdefault("message", "Validation completed")
                validation_result.setdefault("issues", [])
                validation_result.setdefault("reasoning", "No reasoning provided")
                
                return validation_result
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse validation response: {str(e)}")
                return {
                    "is_valid": False,
                    "confidence": 0.0,
                    "message": "Failed to validate test result",
                    "issues": ["Validation service error"],
                    "reasoning": f"JSON parsing error: {str(e)}"
                }
                
        except Exception as e:
            error_message = str(e)
            logger.error(f"Error during test result validation: {str(e)}")
            return {
                "is_valid": False,
                "confidence": 0.0,
                "message": f"Validation failed: {str(e)}",
                "issues": [f"Validation error: {str(e)}"],
                "reasoning": "Validation process encountered an error"
            }
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="test_validation",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "test_request_type": type(test_request.get('test_data', {})).__name__,
                            "test_success": test_response.get('success', False),
                            "has_error": bool(test_response.get('error'))
                        },
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")

    async def auto_fix_api_code(self, api_slug: str, user_id: str, test_failure_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Automatically fix API code based on test failure information.
        
        Args:
            api_slug: The API slug to fix
            user_id: The user ID
            test_failure_info: Information about the test failure
            
        Returns:
            Dict containing fix results
        """
        logger.info(f"Auto-fixing API code for {user_id}/{api_slug}")
        
        try:
            from .file_service import file_service
            
            # Load the current API code
            current_code = file_service.load_api_code(user_id, api_slug)
            
            # Extract test information
            test_request = test_failure_info.get("test_request", {})
            test_response = test_failure_info.get("test_response", {})
            
            # Fix the code
            fixed_code, fixes_applied, debug_info = await self.debug_test_failure(
                current_code, test_request, test_response
            )
            
            # Save the fixed code with a backup
            import datetime
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_slug = f"{api_slug}_backup_{timestamp}"
            
            # Save backup
            file_service.save_api_code(f"{user_id}_{backup_slug}", current_code)
            
            # Save fixed code
            file_service.save_api_code(f"{user_id}_{api_slug}", fixed_code)
            
            return {
                "success": True,
                "message": "API code fixed successfully",
                "fixes_applied": fixes_applied,
                "debug_info": debug_info,
                "backup_slug": backup_slug,
                "fixed_at": datetime.datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to auto-fix API code: {str(e)}")
            return {
                "success": False,
                "message": f"Auto-fix failed: {str(e)}",
                "error": str(e)
            }

    def _extract_error_info(self, test_response: dict) -> Dict[str, Any]:
        """Extract and categorize error information from test response."""
        error_info = {
            "has_error": False,
            "error_type": None,
            "error_message": None,
            "status_code": test_response.get("status_code", 200),
            "execution_time": test_response.get("execution_time", 0),
            "response_data": test_response.get("response_data")
        }
        
        if test_response.get("error"):
            error_info["has_error"] = True
            error_info["error_message"] = test_response["error"]
            
            # Categorize error types
            error_msg = str(test_response["error"]).lower()
            if "syntax" in error_msg:
                error_info["error_type"] = "syntax_error"
            elif "import" in error_msg or "module" in error_msg:
                error_info["error_type"] = "import_error"
            elif "api key" in error_msg:
                error_info["error_type"] = "api_key_error"
            elif "timeout" in error_msg:
                error_info["error_type"] = "timeout_error"
            elif "json" in error_msg:
                error_info["error_type"] = "json_error"
            elif "file" in error_msg or "bytes" in error_msg:
                error_info["error_type"] = "file_handling_error"
            else:
                error_info["error_type"] = "runtime_error"
        
        return error_info

    def _analyze_test_patterns(self, test_request: dict, test_response: dict) -> Dict[str, Any]:
        """Analyze test patterns to identify common issues."""
        analysis = {
            "has_file_input": bool(test_request.get("file_data")),
            "has_json_input": bool(test_request.get("test_data")),
            "response_format_issues": False,
            "performance_issues": False,
            "api_call_issues": False
        }
        
        # Check execution time
        execution_time = test_response.get("execution_time", 0)
        if execution_time > 30:  # More than 30 seconds
            analysis["performance_issues"] = True
        
        # Check response format
        response_data = test_response.get("response_data")
        if response_data:
            if not isinstance(response_data, dict):
                analysis["response_format_issues"] = True
            elif "result" not in response_data and "error" not in response_data:
                analysis["response_format_issues"] = True
        
        # Check for API call issues
        if test_response.get("error"):
            error_msg = str(test_response["error"]).lower()
            if "api" in error_msg or "openai" in error_msg or "request" in error_msg:
                analysis["api_call_issues"] = True
        
        return analysis

    def _determine_comprehensive_fixes(self, original_code: str, fixed_code: str, error_info: Dict, static_issues: List[str]) -> List[str]:
        """Determine comprehensive fixes applied during debugging."""
        fixes = []
        
        # Static analysis fixes
        if static_issues:
            if any("syntax" in issue.lower() for issue in static_issues):
                try:
                    ast.parse(fixed_code)
                    fixes.append("Fixed syntax errors")
                except SyntaxError:
                    pass
        
        # Error-specific fixes
        if error_info["has_error"]:
            error_type = error_info["error_type"]
            if error_type == "import_error":
                original_imports = len(re.findall(r'^import |^from .* import', original_code, re.MULTILINE))
                fixed_imports = len(re.findall(r'^import |^from .* import', fixed_code, re.MULTILINE))
                if fixed_imports > original_imports:
                    fixes.append("Added missing imports")
            
            elif error_type == "api_key_error":
                if 'os.getenv' in fixed_code and 'os.getenv' not in original_code:
                    fixes.append("Fixed API key configuration")
            
            elif error_type == "file_handling_error":
                if 'io.BytesIO' in fixed_code and 'io.BytesIO' not in original_code:
                    fixes.append("Fixed file handling")
            
            elif error_type == "json_error":
                if 'json.loads' in fixed_code or 'json.dumps' in fixed_code:
                    fixes.append("Fixed JSON handling")
            
            elif error_type == "timeout_error":
                if 'timeout' in fixed_code.lower():
                    fixes.append("Added timeout handling")
        
        # General improvements
        original_try_blocks = len(re.findall(r'try:', original_code))
        fixed_try_blocks = len(re.findall(r'try:', fixed_code))
        if fixed_try_blocks > original_try_blocks:
            fixes.append("Enhanced error handling")
        
        return fixes

    async def auto_debug_loop(self, user_id: str, api_slug: str, test_request: dict,
                              max_iterations: int = 3, user_api_key_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Automatic debug loop that retries API execution with fixes until results are valid.
        
        Args:
            user_id: The user ID
            api_slug: The API slug to debug
            test_request: The test request data (includes test_data, file_data, etc.)
            max_iterations: Maximum number of debug iterations (default: 3)
            user_api_key_id: Optional API key ID for usage tracking
            
        Returns:
            Dict containing the final results, debug history, and success status
        """
        logger.info(f"Starting auto-debug loop for {user_id}/{api_slug} (max iterations: {max_iterations})")
        
        debug_history = []
        iteration = 0
        current_code = None
        final_result = None
        
        # Load initial API code
        try:
            from .file_service import file_service
            current_code = file_service.load_api_code(user_id, api_slug)
        except Exception as e:
            logger.error(f"Failed to load API code: {str(e)}")
            return {
                "success": False,
                "error": f"Failed to load API code: {str(e)}",
                "iterations": 0,
                "debug_history": [],
                "final_code": None,
                "final_result": None
            }
        
        while iteration < max_iterations:
            iteration += 1
            iteration_start_time = time.time()
            
            logger.info(f"Debug loop iteration {iteration}/{max_iterations}")
            
            # Execute the API with current code
            test_result = await self._execute_api_test(
                user_id=user_id,
                api_slug=api_slug,
                code=current_code,
                test_request=test_request,
                iteration=iteration
            )
            
            # Validate the test result
            validation_result = await self._validate_test_result_logic(
                test_request, test_result, user_id, user_api_key_id, api_slug
            )
            
            iteration_time = time.time() - iteration_start_time
            
            # Record this iteration
            iteration_record = {
                "iteration": iteration,
                "execution_time": iteration_time,
                "test_result": test_result,
                "validation": validation_result,
                "code_length": len(current_code),
                "timestamp": datetime.now().isoformat()
            }
            
            # Check if result is valid
            if validation_result["is_valid"] and validation_result["confidence"] >= 0.7:
                logger.info(f"Valid result achieved in iteration {iteration}!")
                iteration_record["status"] = "success"
                iteration_record["fixes_applied"] = []
                debug_history.append(iteration_record)
                
                final_result = {
                    "success": True,
                    "message": f"API debugged successfully in {iteration} iteration(s)",
                    "iterations": iteration,
                    "debug_history": debug_history,
                    "final_code": current_code,
                    "final_result": test_result,
                    "validation": validation_result
                }
                break
            
            # If this is the last iteration and we still don't have valid results
            if iteration >= max_iterations:
                logger.warning(f"Max iterations ({max_iterations}) reached without valid result")
                iteration_record["status"] = "max_iterations_reached"
                iteration_record["fixes_applied"] = []
                debug_history.append(iteration_record)
                
                final_result = {
                    "success": False,
                    "message": f"Failed to achieve valid results after {max_iterations} iterations",
                    "iterations": iteration,
                    "debug_history": debug_history,
                    "final_code": current_code,
                    "final_result": test_result,
                    "validation": validation_result,
                    "reason": "max_iterations_exceeded"
                }
                break
            
            # Attempt to fix the code
            logger.info(f"Invalid result in iteration {iteration}, attempting to fix code...")
            
            try:
                # Use comprehensive debugging to fix the code
                fixed_code, fixes_applied, debug_info = await self.debug_test_failure(
                    code=current_code,
                    test_request=test_request,
                    test_response=test_result,
                    user_id=user_id,
                    api_key_id=user_api_key_id,
                    api_slug=api_slug
                )
                
                # Check if the code actually changed
                if fixed_code == current_code:
                    logger.warning(f"No code changes made in iteration {iteration}, stopping debug loop")
                    iteration_record["status"] = "no_changes_made"
                    iteration_record["fixes_applied"] = fixes_applied
                    iteration_record["debug_info"] = debug_info
                    debug_history.append(iteration_record)
                    
                    final_result = {
                        "success": False,
                        "message": "Debug loop stopped - no code changes could be made",
                        "iterations": iteration,
                        "debug_history": debug_history,
                        "final_code": current_code,
                        "final_result": test_result,
                        "validation": validation_result,
                        "reason": "no_code_changes"
                    }
                    break
                
                # Update the code for next iteration
                current_code = fixed_code
                
                # Save the fixed code back to file for next iteration
                file_service.save_api_code(f"{user_id}_{api_slug}", fixed_code)
                
                iteration_record["status"] = "code_fixed"
                iteration_record["fixes_applied"] = fixes_applied
                iteration_record["debug_info"] = debug_info
                iteration_record["code_changed"] = True
                
                logger.info(f"Applied {len(fixes_applied)} fixes in iteration {iteration}")
                
            except Exception as fix_error:
                logger.error(f"Failed to fix code in iteration {iteration}: {str(fix_error)}")
                iteration_record["status"] = "fix_failed"
                iteration_record["fixes_applied"] = []
                iteration_record["fix_error"] = str(fix_error)
                debug_history.append(iteration_record)
                
                final_result = {
                    "success": False,
                    "message": f"Debug loop failed in iteration {iteration}: {str(fix_error)}",
                    "iterations": iteration,
                    "debug_history": debug_history,
                    "final_code": current_code,
                    "final_result": test_result,
                    "validation": validation_result,
                    "reason": "fix_error",
                    "error": str(fix_error)
                }
                break
            
            debug_history.append(iteration_record)
            
            # Small delay between iterations to prevent overwhelming the system
            await asyncio.sleep(0.5)
        
        # Log final results
        total_time = sum(record.get("execution_time", 0) for record in debug_history)
        logger.info(f"Auto-debug loop completed: {final_result['success']} in {iteration} iterations, total time: {total_time:.2f}s")
        
        return final_result

    async def _execute_api_test(self, user_id: str, api_slug: str, code: str, 
                               test_request: dict, iteration: int) -> Dict[str, Any]:
        """
        Execute an API test with the given code and return structured results.
        
        Args:
            user_id: The user ID
            api_slug: The API slug
            code: The API code to execute
            test_request: The test request data
            iteration: Current iteration number for logging
            
        Returns:
            Dict containing test execution results
        """
        logger.info(f"Executing API test (iteration {iteration})")
        start_time = time.time()
        
        try:
            from .api_execution_usage_service import api_execution_usage_service
            
            # Prepare input data
            file_bytes = None
            if test_request.get('file_data'):
                try:
                    import base64
                    file_bytes = base64.b64decode(test_request['file_data'])
                except Exception as e:
                    logger.error(f"Failed to decode file data: {str(e)}")
                    return {
                        "success": False,
                        "error": f"Invalid file data: {str(e)}",
                        "execution_time": time.time() - start_time,
                        "status_code": 400,
                        "response_data": None
                    }
            
            # Execute the API with limits (this is a test execution)
            result, execution_time_ms, success, error_message = await api_execution_usage_service.execute_api_with_limits(
                code=code,
                input_data=test_request.get('test_data', {}),
                file_bytes=file_bytes,
                is_test_execution=True
            )
            
            execution_time = time.time() - start_time
            
            if success:
                return {
                    "success": True,
                    "response_data": result,
                    "execution_time": execution_time,
                    "status_code": 200,
                    "error": None
                }
            else:
                return {
                    "success": False,
                    "response_data": None,
                    "execution_time": execution_time,
                    "status_code": 500,
                    "error": error_message or "API execution failed"
                }
                
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"API test execution failed: {str(e)}")
            return {
                "success": False,
                "response_data": None,
                "execution_time": execution_time,
                "status_code": 500,
                "error": str(e)
            }

    async def smart_debug_with_retry(self, user_id: str, api_slug: str, test_request: dict,
                                    max_iterations: int = 3, confidence_threshold: float = 0.8,
                                    user_api_key_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Enhanced debug loop with smart retry logic and configurable confidence threshold.
        
        Args:
            user_id: The user ID
            api_slug: The API slug to debug
            test_request: The test request data
            max_iterations: Maximum number of debug iterations
            confidence_threshold: Minimum confidence score to consider result valid (0.0-1.0)
            user_api_key_id: Optional API key ID for usage tracking
            
        Returns:
            Dict containing comprehensive debug results
        """
        logger.info(f"Starting smart debug with retry for {user_id}/{api_slug}")
        logger.info(f"Config: max_iterations={max_iterations}, confidence_threshold={confidence_threshold}")
        
        # Initialize tracking
        debug_session = {
            "session_id": str(uuid.uuid4()),
            "user_id": user_id,
            "api_slug": api_slug,
            "start_time": datetime.now().isoformat(),
            "config": {
                "max_iterations": max_iterations,
                "confidence_threshold": confidence_threshold
            },
            "iterations": [],
            "final_status": None,
            "total_execution_time": 0,
            "code_changes_made": 0,
            "validation_improvements": []
        }
        
        session_start_time = time.time()
        current_code = None
        best_result = None
        best_confidence = 0.0
        
        try:
            # Load initial code
            from .file_service import file_service
            current_code = file_service.load_api_code(user_id, api_slug)
            original_code = current_code  # Keep original for comparison
            
        except Exception as e:
            logger.error(f"Failed to load initial API code: {str(e)}")
            debug_session["final_status"] = "failed_to_load_code"
            debug_session["error"] = str(e)
            return debug_session
        
        # Main debug loop
        for iteration in range(1, max_iterations + 1):
            iteration_start = time.time()
            
            logger.info(f"Smart debug iteration {iteration}/{max_iterations}")
            
            # Execute test
            test_result = await self._execute_api_test(
                user_id=user_id,
                api_slug=api_slug,
                code=current_code,
                test_request=test_request,
                iteration=iteration
            )
            
            # Validate result
            validation = await self._validate_test_result_logic(
                test_request, test_result, user_id, user_api_key_id, api_slug
            )
            
            iteration_time = time.time() - iteration_start
            confidence = validation.get("confidence", 0.0)
            
            # Track this iteration
            iteration_record = {
                "iteration": iteration,
                "execution_time": iteration_time,
                "test_success": test_result.get("success", False),
                "validation_confidence": confidence,
                "validation_valid": validation.get("is_valid", False),
                "validation_message": validation.get("message", ""),
                "validation_issues": validation.get("issues", []),
                "code_length": len(current_code),
                "timestamp": datetime.now().isoformat()
            }
            
            # Update best result if this is better
            if confidence > best_confidence:
                best_confidence = confidence
                best_result = {
                    "iteration": iteration,
                    "test_result": test_result,
                    "validation": validation,
                    "code": current_code
                }
                debug_session["validation_improvements"].append({
                    "iteration": iteration,
                    "confidence": confidence,
                    "improvement": confidence - best_confidence if iteration > 1 else confidence
                })
            
            # Check if we've achieved success
            if validation.get("is_valid", False) and confidence >= confidence_threshold:
                logger.info(f"Success achieved in iteration {iteration}! Confidence: {confidence:.2f}")
                iteration_record["status"] = "success"
                iteration_record["final_iteration"] = True
                debug_session["iterations"].append(iteration_record)
                debug_session["final_status"] = "success"
                debug_session["success_iteration"] = iteration
                break
            
            # If this is the last iteration
            if iteration >= max_iterations:
                logger.info(f"Max iterations reached. Best confidence: {best_confidence:.2f}")
                iteration_record["status"] = "max_iterations_reached"
                iteration_record["final_iteration"] = True
                debug_session["iterations"].append(iteration_record)
                debug_session["final_status"] = "max_iterations_reached"
                break
            
            # Attempt to fix the code
            logger.info(f"Attempting to improve code (current confidence: {confidence:.2f})")
            
            try:
                # Create enhanced prompt with iteration context
                enhanced_test_result = {
                    **test_result,
                    "iteration_context": {
                        "iteration": iteration,
                        "previous_confidence": confidence,
                        "target_confidence": confidence_threshold,
                        "validation_issues": validation.get("issues", [])
                    }
                }
                
                fixed_code, fixes_applied, debug_info = await self.debug_test_failure(
                    code=current_code,
                    test_request=test_request,
                    test_response=enhanced_test_result,
                    user_id=user_id,
                    api_key_id=user_api_key_id,
                    api_slug=api_slug
                )
                
                # Check for meaningful changes
                code_similarity = self._calculate_code_similarity(current_code, fixed_code)
                
                if code_similarity > 0.95:  # Less than 5% change
                    logger.warning(f"Minimal code changes detected (similarity: {code_similarity:.2f})")
                    iteration_record["status"] = "minimal_changes"
                    iteration_record["code_similarity"] = code_similarity
                    iteration_record["fixes_applied"] = fixes_applied
                    debug_session["iterations"].append(iteration_record)
                    
                    # If we have a decent result, use it
                    if best_confidence >= 0.5:
                        debug_session["final_status"] = "acceptable_result_found"
                        break
                    else:
                        debug_session["final_status"] = "insufficient_improvement"
                        break
                
                # Apply the fixes
                current_code = fixed_code
                file_service.save_api_code(f"{user_id}_{api_slug}", fixed_code)
                debug_session["code_changes_made"] += 1
                
                iteration_record["status"] = "code_improved"
                iteration_record["fixes_applied"] = fixes_applied
                iteration_record["code_similarity"] = code_similarity
                iteration_record["debug_info"] = debug_info
                
                logger.info(f"Applied {len(fixes_applied)} fixes, code similarity: {code_similarity:.2f}")
                
            except Exception as fix_error:
                logger.error(f"Failed to fix code in iteration {iteration}: {str(fix_error)}")
                iteration_record["status"] = "fix_failed"
                iteration_record["fix_error"] = str(fix_error)
                debug_session["iterations"].append(iteration_record)
                debug_session["final_status"] = "fix_error"
                debug_session["error"] = str(fix_error)
                break
            
            debug_session["iterations"].append(iteration_record)
            
            # Brief pause between iterations
            await asyncio.sleep(0.3)
        
        # Finalize session
        debug_session["total_execution_time"] = time.time() - session_start_time
        debug_session["end_time"] = datetime.now().isoformat()
        debug_session["best_confidence"] = best_confidence
        debug_session["final_code"] = current_code
        debug_session["original_code_length"] = len(original_code)
        debug_session["final_code_length"] = len(current_code)
        
        if best_result:
            debug_session["best_result"] = {
                "iteration": best_result["iteration"],
                "confidence": best_confidence,
                "test_result": best_result["test_result"],
                "validation": best_result["validation"]
            }
        
        # Determine overall success
        debug_session["overall_success"] = (
            debug_session["final_status"] == "success" or
            (debug_session["final_status"] == "acceptable_result_found" and best_confidence >= 0.6)
        )
        
        logger.info(f"Smart debug completed: {debug_session['final_status']} "
                   f"(best confidence: {best_confidence:.2f}, "
                   f"total time: {debug_session['total_execution_time']:.2f}s)")
        
        return debug_session

    def _calculate_code_similarity(self, code1: str, code2: str) -> float:
        """
        Calculate similarity between two code strings.
        Returns a value between 0.0 (completely different) and 1.0 (identical).
        """
        if code1 == code2:
            return 1.0
        
        # Simple line-based similarity
        lines1 = set(line.strip() for line in code1.split('\n') if line.strip())
        lines2 = set(line.strip() for line in code2.split('\n') if line.strip())
        
        if not lines1 and not lines2:
            return 1.0
        if not lines1 or not lines2:
            return 0.0
        
        intersection = len(lines1.intersection(lines2))
        union = len(lines1.union(lines2))
        
        return intersection / union if union > 0 else 0.0

    def _check_circuit_breaker(self) -> Dict[str, Any]:
        """
        Check circuit breaker state and determine if operations should be allowed.
        
        Returns:
            Dict with circuit breaker status and decision
        """
        current_time = time.time()
        
        # Check if circuit should be reset (after timeout)
        if (self.circuit_breaker_state["is_open"] and 
            self.circuit_breaker_state["last_failure_time"] and
            current_time - self.circuit_breaker_state["last_failure_time"] > self.circuit_breaker_config["reset_timeout"]):
            
            logger.info("Circuit breaker reset timeout reached, attempting to close circuit")
            self.circuit_breaker_state["is_open"] = False
            self.circuit_breaker_state["failure_count"] = 0
        
        # Calculate failure rate
        failure_rate = 0.0
        if self.circuit_breaker_state["total_attempts"] > 0:
            failure_rate = self.circuit_breaker_state["total_failures"] / self.circuit_breaker_state["total_attempts"]
        
        # Determine if circuit should be opened
        should_open = (
            self.circuit_breaker_state["failure_count"] >= self.circuit_breaker_config["max_failures"] or
            (self.circuit_breaker_state["total_attempts"] >= 10 and 
             failure_rate >= self.circuit_breaker_config["failure_threshold"])
        )
        
        if should_open and not self.circuit_breaker_state["is_open"]:
            logger.warning("Circuit breaker opened due to high failure rate")
            self.circuit_breaker_state["is_open"] = True
            self.circuit_breaker_state["last_failure_time"] = current_time
        
        return {
            "is_open": self.circuit_breaker_state["is_open"],
            "failure_count": self.circuit_breaker_state["failure_count"],
            "failure_rate": failure_rate,
            "total_attempts": self.circuit_breaker_state["total_attempts"],
            "total_failures": self.circuit_breaker_state["total_failures"],
            "can_proceed": not self.circuit_breaker_state["is_open"]
        }

    def _record_circuit_breaker_attempt(self, success: bool):
        """Record an attempt for circuit breaker tracking."""
        self.circuit_breaker_state["total_attempts"] += 1
        
        if success:
            # Reset consecutive failure count on success
            self.circuit_breaker_state["failure_count"] = 0
        else:
            self.circuit_breaker_state["failure_count"] += 1
            self.circuit_breaker_state["total_failures"] += 1
            self.circuit_breaker_state["last_failure_time"] = time.time()

    def _check_rate_limits(self, user_id: str) -> Dict[str, Any]:
        """
        Check rate limits for debug sessions.
        
        Args:
            user_id: The user ID to check limits for
            
        Returns:
            Dict with rate limit status
        """
        current_time = time.time()
        one_hour_ago = current_time - 3600
        
        # Clean old session history
        self.session_history = [
            session for session in self.session_history 
            if session["timestamp"] > one_hour_ago
        ]
        
        # Count sessions for this user in the last hour
        user_sessions = [
            session for session in self.session_history 
            if session["user_id"] == user_id
        ]
        
        # Check if user has exceeded session limit
        sessions_in_hour = len(user_sessions)
        can_start_session = sessions_in_hour < self.rate_limit_config["max_debug_sessions_per_hour"]
        
        # Check minimum interval between sessions
        last_session_time = None
        if user_sessions:
            last_session_time = max(session["timestamp"] for session in user_sessions)
            time_since_last = current_time - last_session_time
            min_interval_met = time_since_last >= self.rate_limit_config["min_interval_between_sessions"]
        else:
            min_interval_met = True
            time_since_last = None
        
        can_proceed = can_start_session and min_interval_met
        
        return {
            "can_proceed": can_proceed,
            "sessions_in_hour": sessions_in_hour,
            "max_sessions_per_hour": self.rate_limit_config["max_debug_sessions_per_hour"],
            "last_session_time": last_session_time,
            "time_since_last": time_since_last,
            "min_interval_required": self.rate_limit_config["min_interval_between_sessions"],
            "min_interval_met": min_interval_met
        }

    def _record_debug_session(self, user_id: str, session_id: str, success: bool):
        """Record a debug session for rate limiting."""
        self.session_history.append({
            "user_id": user_id,
            "session_id": session_id,
            "timestamp": time.time(),
            "success": success
        })

    async def protected_smart_debug_with_retry(self, user_id: str, api_slug: str, test_request: dict,
                                             max_iterations: int = 3, confidence_threshold: float = 0.8,
                                             user_api_key_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Enhanced debug loop with circuit breaker and rate limiting protection.
        
        Args:
            user_id: The user ID
            api_slug: The API slug to debug
            test_request: The test request data
            max_iterations: Maximum number of debug iterations
            confidence_threshold: Minimum confidence score to consider result valid
            user_api_key_id: Optional API key ID for usage tracking
            
        Returns:
            Dict containing comprehensive debug results with protection status
        """
        logger.info(f"Starting protected smart debug for {user_id}/{api_slug}")
        
        # Check circuit breaker
        circuit_status = self._check_circuit_breaker()
        if not circuit_status["can_proceed"]:
            logger.warning(f"Circuit breaker is open, rejecting debug request")
            return {
                "success": False,
                "error": "Debug service temporarily unavailable due to high failure rate",
                "circuit_breaker_status": circuit_status,
                "protection_triggered": "circuit_breaker"
            }
        
        # Check rate limits
        rate_limit_status = self._check_rate_limits(user_id)
        if not rate_limit_status["can_proceed"]:
            logger.warning(f"Rate limit exceeded for user {user_id}")
            return {
                "success": False,
                "error": "Debug session rate limit exceeded",
                "rate_limit_status": rate_limit_status,
                "protection_triggered": "rate_limit"
            }
        
        # Enforce maximum iterations limit
        max_iterations = min(max_iterations, self.rate_limit_config["max_iterations_per_session"])
        
        session_id = str(uuid.uuid4())
        session_success = False
        
        try:
            # Record the attempt
            self._record_circuit_breaker_attempt(True)  # Optimistic recording
            
            # Execute the debug session
            debug_result = await self.smart_debug_with_retry(
                user_id=user_id,
                api_slug=api_slug,
                test_request=test_request,
                max_iterations=max_iterations,
                confidence_threshold=confidence_threshold,
                user_api_key_id=user_api_key_id
            )
            
            session_success = debug_result.get("overall_success", False)
            
            # Update circuit breaker based on actual result
            self._record_circuit_breaker_attempt(session_success)
            
            # Record session for rate limiting
            self._record_debug_session(user_id, session_id, session_success)
            
            # Add protection metadata
            debug_result["protection_status"] = {
                "circuit_breaker": circuit_status,
                "rate_limits": rate_limit_status,
                "max_iterations_enforced": max_iterations,
                "session_id": session_id
            }
            
            return debug_result
            
        except Exception as e:
            logger.error(f"Protected debug session failed: {str(e)}")
            
            # Record failure
            self._record_circuit_breaker_attempt(False)
            self._record_debug_session(user_id, session_id, False)
            
            return {
                "success": False,
                "error": str(e),
                "session_id": session_id,
                "protection_status": {
                    "circuit_breaker": circuit_status,
                    "rate_limits": rate_limit_status,
                    "error_recorded": True
                }
            }

    def get_debug_service_status(self) -> Dict[str, Any]:
        """
        Get current status of the debug service including circuit breaker and rate limits.
        
        Returns:
            Dict with service status information
        """
        circuit_status = self._check_circuit_breaker()
        
        # Calculate recent session statistics
        current_time = time.time()
        one_hour_ago = current_time - 3600
        recent_sessions = [
            session for session in self.session_history 
            if session["timestamp"] > one_hour_ago
        ]
        
        successful_sessions = sum(1 for session in recent_sessions if session["success"])
        total_recent_sessions = len(recent_sessions)
        recent_success_rate = successful_sessions / total_recent_sessions if total_recent_sessions > 0 else 1.0
        
        return {
            "service_available": not circuit_status["is_open"],
            "circuit_breaker": {
                "is_open": circuit_status["is_open"],
                "failure_count": circuit_status["failure_count"],
                "failure_rate": circuit_status["failure_rate"],
                "total_attempts": circuit_status["total_attempts"],
                "total_failures": circuit_status["total_failures"]
            },
            "rate_limits": {
                "max_sessions_per_hour": self.rate_limit_config["max_debug_sessions_per_hour"],
                "max_iterations_per_session": self.rate_limit_config["max_iterations_per_session"],
                "min_interval_between_sessions": self.rate_limit_config["min_interval_between_sessions"]
            },
            "recent_activity": {
                "sessions_last_hour": total_recent_sessions,
                "successful_sessions": successful_sessions,
                "success_rate": recent_success_rate
            },
            "timestamp": datetime.now().isoformat()
        }

# Global instance
code_debugger = CodeDebugger() 





