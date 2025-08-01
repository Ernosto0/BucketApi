import ast
import re
import logging
import time
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
        
        # Step 1: Static analysis to find obvious issues
        issues_found = await self._static_analysis(generated_code)
        
        # Step 2: Use AI to analyze and fix the code
        if issues_found:
            logger.info(f"Found {len(issues_found)} issues, applying AI fixes...")
            fixed_code, fixes_applied = await self._ai_code_review_and_fix(
                generated_code, issues_found, original_prompt, user_id, api_key_id
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
                fixed_code, final_issues, original_prompt, user_id, api_key_id
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
            
            success = True
            response_length = len(fixed_code)
            
            return fixed_code, fixes_applied
            
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to fix code with AI: {str(e)}")
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
        - Incorrect response formatting"""

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
        
        # Validate code syntax
        try:
            import ast
            ast.parse(code)
        except SyntaxError as e:
            logger.error(f"Syntax error in extracted code: {e}")
            # Try to fix common issues
            if code.endswith('```'):
                code = code[:-3].strip()
            try:
                ast.parse(code)
            except SyntaxError as e2:
                logger.error(f"Failed to fix syntax error: {e2}")
                raise Exception(f"Generated code has syntax errors: {str(e2)}")
        
        # Ensure code is not empty and has proper structure
        if not code or 'def run(' not in code:
            raise Exception("Invalid code: missing run() function")
        
        return code
    
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
                # Clean up the response
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    start = cleaned_response.find("{")
                    end = cleaned_response.rfind("}") + 1
                    if start != -1 and end != 0:
                        cleaned_response = cleaned_response[start:end]
                elif cleaned_response.startswith("```"):
                    lines = cleaned_response.split('\n')
                    cleaned_response = '\n'.join(lines[1:-1])
                
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

# Global instance
code_debugger = CodeDebugger() 





