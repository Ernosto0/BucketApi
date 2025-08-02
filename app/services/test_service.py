import time
import uuid
import json
import asyncio
import logging
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from ..models import TestRequest, TestResponse, TestHistoryEntry, TestHistoryResponse, PerformanceTestRequest, PerformanceTestResponse
from .file_service import file_service
from .openai_service import openai_service
import base64
from fastapi import HTTPException

logger = logging.getLogger(__name__)

def load_test_validator_prompt() -> Dict[str, str]:
    """Load the test validator prompts from JSON file."""
    try:
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                 'prompts', 'openai', 'test_validator.json')
        with open(prompt_path, 'r') as f:
            prompts = json.load(f)
        return prompts
    except Exception as e:
        logger.error(f"Failed to load test validator prompts: {str(e)}")
        raise HTTPException(status_code=500, 
                          detail="Failed to load validation prompts")

class TestService:
    """Service for handling API testing functionality."""
    
    def __init__(self):
        self.test_history = []  # In-memory storage for test history
        
    async def execute_test(self, request: TestRequest) -> TestResponse:
        """Execute a single test against an API."""
        test_id = str(uuid.uuid4())
        start_time = time.time()
        result = None  # Initialize result variable
        
        try:
            # Check if API exists
            if not file_service.api_exists(request.user_id, request.api_slug):
                raise FileNotFoundError(f"API not found: {request.user_id}/{request.api_slug}")
            
            # Prepare test data
            file_bytes = None
            if request.file_data:
                try:
                    file_bytes = base64.b64decode(request.file_data)
                except Exception as e:
                    raise ValueError(f"Invalid file data: {str(e)}")
            
            # Execute the API
            try:
                # Execute API and await the result
                result = await file_service.load_and_execute_api(
                    user_id=request.user_id,
                    api_slug=request.api_slug,
                    file_bytes=file_bytes,
                    input_data=request.test_data
                )
                
                # Ensure result is JSON serializable
                if result is not None:
                    try:
                        # Try to serialize to detect any non-serializable objects
                        json.dumps(result, default=str)
                    except (TypeError, ValueError) as e:
                        logger.error(f"API result is not JSON serializable: {str(e)}")
                        raise ValueError(f"API returned non-serializable result: {str(e)}")
                
                execution_time = time.time() - start_time
                status_code = 200
                success = True
                error = None
                
            except HTTPException as e:
                execution_time = time.time() - start_time
                status_code = e.status_code
                success = False
                error = e.detail
                result = None
            except Exception as api_error:
                execution_time = time.time() - start_time
                status_code = 500
                success = False
                error = str(api_error)
                result = None
            
            # Create response headers
            response_headers = {
                "content-type": "application/json",
                "x-execution-time": str(execution_time),
                "x-test-id": test_id
            }
            
            # Create test response
            test_response = TestResponse(
                success=success,
                test_id=test_id,
                api_slug=request.api_slug,
                user_id=request.user_id,
                request_data=request.test_data,
                response_data=result,  # Use the awaited result
                error=error,
                execution_time=execution_time,
                status_code=status_code,
                response_headers=response_headers,
                timestamp=datetime.now(),
                test_type=request.test_type or "manual",
                validation=None
            )
            
            # Validate test result if successful
            if success and result is not None:
                try:
                    validation = await self.validate_test_result(request, test_response)
                    test_response.validation = validation
                except Exception as e:
                    logger.error(f"Test validation failed: {str(e)}")
                    # Don't fail the test if validation fails
                    test_response.validation = {
                        "is_valid": False,
                        "confidence": 0.0,
                        "validation_message": f"Validation failed: {str(e)}",
                        "issues_found": ["Validation error"],
                        "suggestions": ["Check API response format"],
                        "reasoning": str(e)
                    }
            
            return test_response
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"Test execution failed: {str(e)}")
            
            return TestResponse(
                success=False,
                test_id=test_id,
                api_slug=request.api_slug,
                user_id=request.user_id,
                request_data=request.test_data,
                response_data=None,
                error=str(e),
                execution_time=execution_time,
                status_code=500,
                response_headers={"x-test-id": test_id},
                timestamp=datetime.now(),
                test_type=request.test_type or "manual"
            )
    
    async def execute_performance_test(self, request: PerformanceTestRequest) -> PerformanceTestResponse:
        """Execute performance tests with multiple iterations."""
        test_id = str(uuid.uuid4())
        start_time = time.time()
        
        try:
            # Check if API exists
            if not file_service.api_exists(request.user_id, request.api_slug):
                raise FileNotFoundError(f"API not found: {request.user_id}/{request.api_slug}")
            
            # Prepare test requests
            test_requests = []
            for i in range(request.iterations):
                test_req = TestRequest(
                    user_id=request.user_id,
                    api_slug=request.api_slug,
                    test_data=request.test_data,
                    test_type="performance"
                )
                test_requests.append(test_req)
            
            # Execute tests
            if request.concurrent:
                # Run tests concurrently
                tasks = [self._execute_single_performance_test(req) for req in test_requests]
                results = await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # Run tests sequentially
                results = []
                for req in test_requests:
                    result = await self._execute_single_performance_test(req)
                    results.append(result)
            
            total_time = time.time() - start_time
            
            # Process results
            successful_results = [r for r in results if isinstance(r, dict) and r.get('success', False)]
            failed_results = [r for r in results if not (isinstance(r, dict) and r.get('success', False))]
            
            execution_times = [r['execution_time'] for r in successful_results]
            
            if execution_times:
                average_time = sum(execution_times) / len(execution_times)
                min_time = min(execution_times)
                max_time = max(execution_times)
            else:
                average_time = min_time = max_time = 0.0
            
            success_rate = len(successful_results) / len(results) if results else 0.0
            
            # Create detailed results
            detailed_results = []
            for i, result in enumerate(results):
                if isinstance(result, dict):
                    detailed_results.append({
                        "iteration": i + 1,
                        "success": result.get('success', False),
                        "execution_time": result.get('execution_time', 0.0),
                        "error": result.get('error')
                    })
                else:
                    detailed_results.append({
                        "iteration": i + 1,
                        "success": False,
                        "execution_time": 0.0,
                        "error": str(result)
                    })
            
            return PerformanceTestResponse(
                success=True,
                test_id=test_id,
                api_slug=request.api_slug,
                user_id=request.user_id,
                iterations=request.iterations,
                concurrent=request.concurrent,
                total_time=total_time,
                average_time=average_time,
                min_time=min_time,
                max_time=max_time,
                success_rate=success_rate,
                failed_tests=len(failed_results),
                timestamp=datetime.now(),
                detailed_results=detailed_results
            )
            
        except Exception as e:
            logger.error(f"Performance test failed: {str(e)}")
            return PerformanceTestResponse(
                success=False,
                test_id=test_id,
                api_slug=request.api_slug,
                user_id=request.user_id,
                iterations=0,
                concurrent=request.concurrent,
                total_time=time.time() - start_time,
                average_time=0.0,
                min_time=0.0,
                max_time=0.0,
                success_rate=0.0,
                failed_tests=request.iterations,
                timestamp=datetime.now(),
                detailed_results=[]
            )
    
    async def _execute_single_performance_test(self, request: TestRequest) -> Dict[str, Any]:
        """Execute a single performance test iteration."""
        start_time = time.time()
        
        try:
            result = await file_service.load_and_execute_api(
                user_id=request.user_id,
                api_slug=request.api_slug,
                file_bytes=None,
                input_data=request.test_data
            )
            
            execution_time = time.time() - start_time
            
            return {
                "success": True,
                "execution_time": execution_time,
                "result": result,
                "error": None
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            return {
                "success": False,
                "execution_time": execution_time,
                "result": None,
                "error": str(e)
            }
    
    async def get_test_history(self, user_id: str, api_slug: Optional[str] = None, limit: int = 50) -> TestHistoryResponse:
        """Get test history for a user or specific API."""
        try:
            # Filter tests
            filtered_tests = [
                test for test in self.test_history 
                if test.user_id == user_id and (api_slug is None or test.api_slug == api_slug)
            ]
            
            # Sort by timestamp (newest first)
            filtered_tests.sort(key=lambda x: x.timestamp, reverse=True)
            
            # Limit results
            limited_tests = filtered_tests[:limit]
            
            # Calculate statistics
            if filtered_tests:
                successful_tests = [t for t in filtered_tests if t.success]
                success_rate = len(successful_tests) / len(filtered_tests)
                avg_execution_time = sum(t.execution_time for t in filtered_tests) / len(filtered_tests)
            else:
                success_rate = 0.0
                avg_execution_time = 0.0
            
            return TestHistoryResponse(
                success=True,
                user_id=user_id,
                api_slug=api_slug,
                tests=limited_tests,
                total_tests=len(filtered_tests),
                success_rate=success_rate,
                average_execution_time=avg_execution_time
            )
            
        except Exception as e:
            logger.error(f"Failed to get test history: {str(e)}")
            return TestHistoryResponse(
                success=False,
                user_id=user_id,
                api_slug=api_slug,
                tests=[],
                total_tests=0,
                success_rate=0.0,
                average_execution_time=0.0
            )
    
    async def _save_test_to_history(self, test_response: TestResponse):
        """Save test result to history."""
        try:
            # Create history entry
            history_entry = TestHistoryEntry(
                test_id=test_response.test_id,
                api_slug=test_response.api_slug,
                user_id=test_response.user_id,
                test_type=test_response.test_type,
                success=test_response.success,
                execution_time=test_response.execution_time,
                status_code=test_response.status_code,
                timestamp=test_response.timestamp,
                request_summary=self._create_request_summary(test_response.request_data),
                response_summary=self._create_response_summary(test_response.response_data, test_response.error)
            )
            
            # Add to in-memory storage
            self.test_history.append(history_entry)
            
            # Keep only last 1000 tests to prevent memory issues
            if len(self.test_history) > 1000:
                self.test_history = self.test_history[-1000:]
            
            # TODO: In the future, save to database
            # await self._save_to_database(history_entry)
            
        except Exception as e:
            logger.error(f"Failed to save test to history: {str(e)}")
    
    def _create_request_summary(self, request_data: Optional[Dict[str, Any]]) -> Optional[str]:
        """Create a brief summary of request data."""
        if not request_data:
            return "No request data"
        
        try:
            # Truncate large data
            summary = str(request_data)
            if len(summary) > 100:
                summary = summary[:97] + "..."
            return summary
        except Exception:
            return "Invalid request data"
    
    def _create_response_summary(self, response_data: Any, error: Optional[str]) -> Optional[str]:
        """Create a brief summary of response data."""
        if error:
            return f"Error: {error[:100]}..."
        
        if response_data is None:
            return "No response data"
        
        try:
            summary = str(response_data)
            if len(summary) > 100:
                summary = summary[:97] + "..."
            return summary
        except Exception:
            return "Invalid response data"
    
    async def generate_test_data(self, user_id: str, api_slug: str) -> Dict[str, Any]:
        """Generate smart test data for an API based on its documentation."""
        try:
            # Load API details if available
            api_details = await file_service.get_api_details(user_id, api_slug)
            
            # Try to extract example data from documentation or curl example
            if 'curl_example' in api_details:
                curl_example = api_details['curl_example']
                extracted_data = self._extract_data_from_curl(curl_example)
                if extracted_data:
                    return extracted_data
            
            # Generate generic test data
            return {
                "message": "Test message",
                "data": "sample test data",
                "timestamp": datetime.now().isoformat(),
                "test": True
            }
            
        except Exception as e:
            logger.error(f"Failed to generate test data: {str(e)}")
            return {"test": "data"}
    
    def _extract_data_from_curl(self, curl_example: str) -> Optional[Dict[str, Any]]:
        """Extract JSON data from curl example."""
        try:
            import re
            
            # Look for -d or --data flag in curl command
            data_match = re.search(r'-d\s+\'([^\']+)\'|--data\s+\'([^\']+)\'|-d\s+"([^"]+)"|--data\s+"([^"]+)"', curl_example)
            if data_match:
                data = data_match.group(1) or data_match.group(2) or data_match.group(3) or data_match.group(4)
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    return None
            
            # Look for JSON-like content
            json_match = re.search(r'\{[^}]+\}', curl_example)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    return None
                    
        except Exception as e:
            logger.error(f"Error extracting data from curl: {str(e)}")
        
        return None

    async def validate_test_result(self, test_request: TestRequest, test_response: TestResponse) -> Dict[str, Any]:
        """
        Validate if a test result is valid using OpenAI.
        
        Args:
            test_request: The original test request
            test_response: The test response to validate
            
        Returns:
            Dict containing validation results with:
            - is_valid: bool
            - confidence: float (0.0 to 1.0)
            - validation_message: str
            - issues_found: List[str]
            - suggestions: List[str]
        """
        try:
            logger.info(f"Validating test result for API {test_request.api_slug}")
            
            # Load validation prompts
            prompts = load_test_validator_prompt()
            system_prompt = prompts["system_prompt"]
            
            # Format the user prompt template with actual values
            user_prompt = prompts["user_prompt_template"].format(
                input_data=json.dumps(test_request.test_data, indent=2, default=str) if test_request.test_data else "No input data",
                output_data=json.dumps(test_response.response_data, indent=2, default=str) if test_response.response_data else "No output data",
                api_slug=test_request.api_slug,
                test_type=test_request.test_type,
                has_file_input=bool(test_request.file_data),
                execution_time=test_response.execution_time,
                status_code=test_response.status_code
            )

            # Make request to OpenAI
            response = await openai_service._make_openai_request(system_prompt, user_prompt)
            # Log the raw response for debugging
            logger.info(f"Raw OpenAI response for validation: {response[:500]}...")
            
            # Check if response is empty or None
            if not response or response.strip() == "":
                logger.error("OpenAI returned empty response")
                return {
                    "is_valid": False,
                    "confidence": 0.0,
                    "validation_message": "OpenAI returned empty response",
                    "issues_found": ["Empty response from validation service"],
                    "suggestions": ["Check OpenAI service status and retry"],
                    "reasoning": "Validation service returned no data",
                    "validated_at": datetime.now().isoformat(),
                    "validator": "openai",
                    "test_id": test_response.test_id,
                    "error": "Empty response"
                }
            
            # Parse the response
            try:
                # Try to extract JSON from response if it's wrapped in markdown
                cleaned_response = response.strip()
                if cleaned_response.startswith("```json"):
                    start = cleaned_response.find("{")
                    end = cleaned_response.rfind("}") + 1
                    if start != -1 and end != 0:
                        cleaned_response = cleaned_response[start:end]
                elif cleaned_response.startswith("```"):
                    # Remove markdown code blocks
                    lines = cleaned_response.split('\n')
                    cleaned_response = '\n'.join(lines[1:-1])
                
                validation_result = json.loads(cleaned_response)
                
                # Ensure all required fields are present
                validation_result.setdefault("is_valid", False)
                validation_result.setdefault("confidence", 0.0)
                validation_result.setdefault("validation_message", "Validation completed")
                validation_result.setdefault("issues_found", [])
                validation_result.setdefault("suggestions", [])
                validation_result.setdefault("reasoning", "No reasoning provided")
                
                # Add metadata
                validation_result["validated_at"] = datetime.now().isoformat()
                validation_result["validator"] = "openai"
                validation_result["test_id"] = test_response.test_id
                
                logger.info(f"Test validation completed. Valid: {validation_result['is_valid']}, Confidence: {validation_result['confidence']}")
                return validation_result
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse OpenAI validation response: {str(e)}")
                logger.error(f"Raw response that failed to parse: '{response}'")
                
                # Return a fallback response if JSON parsing fails
                return {
                    "is_valid": False,
                    "confidence": 0.0,
                    "validation_message": "Failed to parse validation response",
                    "issues_found": ["Invalid validation response format"],
                    "suggestions": ["Retry validation or check manually"],
                    "reasoning": f"JSON parsing error: {str(e)}",
                    "validated_at": datetime.now().isoformat(),
                    "validator": "openai",
                    "test_id": test_response.test_id,
                    "raw_response": response[:1000],  # Limit raw response length
                    "parse_error": str(e)
                }
                
        except Exception as e:
            logger.error(f"Error validating test result: {str(e)}")
            return {
                "is_valid": False,
                "confidence": 0.0,
                "validation_message": f"Validation failed due to error: {str(e)}",
                "issues_found": [f"Validation error: {str(e)}"],
                "suggestions": ["Check API connection and retry"],
                "reasoning": "Validation process encountered an error",
                "validated_at": datetime.now().isoformat(),
                "validator": "openai",
                "test_id": getattr(test_response, 'test_id', 'unknown'),
                "error": str(e)
            }

# Global instance
test_service = TestService()