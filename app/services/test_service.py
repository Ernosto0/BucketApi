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
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
        return prompts
    except Exception as e:
        logger.error(f"Failed to load test validator prompts: {str(e)}")
        raise HTTPException(status_code=500, 
                          detail="Failed to load validation prompts")

def load_test_data_generator_prompt() -> Dict[str, str]:
    """Load the test data generator prompts from JSON file."""
    try:
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                 'prompts', 'openai', 'generate_test_data.json')
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompts = json.load(f)
        return prompts
    except Exception as e:
        logger.error(f"Failed to load test data generator prompts: {str(e)}")
        raise HTTPException(status_code=500, 
                          detail="Failed to load test data generator prompts")

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
                    input_data=request.test_data,
                    is_test_execution=True  # This is a test execution
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
    
    async def generate_test_data(self, user_id: str, api_slug: str) -> List[Dict[str, Any]]:
        """Generate smart test data for an API using AI based on its documentation."""
        try:
            logger.info(f"Generating AI-powered test data for API {api_slug}")
            
            # Try to load API details, but continue even if not available
            api_details = {}
            try:
                api_details = file_service.get_api_details(user_id, api_slug)
                logger.info(f"Loaded API details for {api_slug}: {list(api_details.keys())}")
            except Exception as e:
                logger.warning(f"Could not load API details for {api_slug}: {str(e)}, trying to load code directly")
                # Try to load the code directly from file
                try:
                    code = file_service.load_api_code(user_id, api_slug)
                    api_details = {
                        'description': f'API endpoint {api_slug}',
                        'functionality': 'Data processing and response generation',
                        'expected_output': 'JSON response with processed data',
                        'documentation': f'API {api_slug} for data processing',
                        'curl_example': '',
                        'code': code if code else ''  # Ensure code is not None
                    }
                    logger.info(f"Loaded API code directly for {api_slug}")
                except Exception as code_error:
                    logger.warning(f"Could not load API code either: {code_error}, using minimal defaults")
                    api_details = {
                        'description': f'API endpoint {api_slug}',
                        'functionality': 'Data processing and response generation',
                        'expected_output': 'JSON response with processed data',
                        'documentation': f'API {api_slug} for data processing',
                        'curl_example': '',
                        'code': ''
                    }
            
            # Enhanced extraction of API context
            context = self._extract_api_context(api_details)
            
            api_description = context['description']
            api_functionality = context['functionality'] 
            expected_output = context['expected_output']
            sample_input = context['sample_input']
            expected_fields = context['expected_fields']
            input_type = context['input_type']
            processing_type = context['processing_type']
            api_purpose = context['api_purpose']
            
            logger.info(f"API Context for {api_slug}: purpose='{api_purpose}', fields='{expected_fields}', processing='{processing_type}'")
            logger.info(f"API details keys: {list(api_details.keys())}")
            
            # Debug specific API
            if "api-175828" in api_slug:  # Match both API IDs
                logger.info(f"DEBUGGING {api_slug} - Raw API details: {api_details}")
                if 'code' in api_details:
                    logger.info(f"DEBUGGING {api_slug} - Code contains 'text': {'text' in api_details['code']}")
                    logger.info(f"DEBUGGING {api_slug} - Code contains 'sentiment': {'sentiment' in api_details['code'].lower()}")
                    logger.info(f"DEBUGGING {api_slug} - First 300 chars of code: {api_details['code'][:300]}")
                else:
                    logger.info(f"DEBUGGING {api_slug} - No code in API details")
            
            # Load the test data generator prompt
            prompt_config = load_test_data_generator_prompt()
            system_prompt = prompt_config["system_prompt"]
            
            # Format the user prompt with API details
            user_prompt = prompt_config["user_prompt_template"].format(
                api_description=api_description,
                api_functionality=api_functionality,
                expected_fields=expected_fields,
                sample_input=sample_input or "No sample input provided",
                expected_output=expected_output,
                api_purpose=api_purpose,
                input_type=input_type,
                processing_type=processing_type
            )
            
            # Try OpenAI first, fallback to enhanced test data if it fails
            logger.info(f"Making OpenAI request for test data generation using model: {prompt_config.get('model', 'gpt-4o-mini')}")
            logger.info(f"Context being sent to AI - Expected fields: {expected_fields}, API purpose: {api_purpose}")
            logger.info(f"Full user prompt being sent to AI: {user_prompt}")
            
            try:
                response = await openai_service.make_openai_request(
                    system_prompt=system_prompt, 
                    user_prompt=user_prompt, 
                    prompt_config=prompt_config, 
                    user_id=user_id, 
                    operation_type="test_data_generation", 
                    api_slug=api_slug
                )
                
                logger.info(f"Raw AI response: {response[:500]}...")
                
                # Parse the AI response
                try:
                    test_data_array = json.loads(response)
                    
                    # Convert direct input data to scenario format
                    if isinstance(test_data_array, list) and len(test_data_array) > 0:
                        # Convert direct input objects to scenario format
                        test_scenarios = []
                        scenario_names = ["Normal case", "Simple case", "Complex case"]
                        
                        for i, input_data in enumerate(test_data_array[:3]):  # Limit to 3 scenarios
                            if isinstance(input_data, dict):
                                # Validate that the input data is not empty or just spaces
                                if input_data and any(str(v).strip() for v in input_data.values()):
                                    scenario_name = scenario_names[i] if i < len(scenario_names) else f"Test scenario {i+1}"
                                    test_scenarios.append({
                                        "scenario": scenario_name,
                                        "data": input_data
                                    })
                                else:
                                    # Skip completely empty or whitespace-only data
                                    logger.warning(f"Skipping empty test scenario {i+1}")
                        
                        if test_scenarios:
                            logger.info(f"Generated {len(test_scenarios)} test scenarios using AI")
                            return test_scenarios
                    
                    logger.warning("AI response was not in expected format, falling back to enhanced test data")
                    return self._generate_enhanced_fallback_test_data(api_details)
                        
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse AI response as JSON: {e}, falling back to enhanced test data")
                    return self._generate_enhanced_fallback_test_data(api_details)
                    
            except Exception as openai_error:
                logger.warning(f"OpenAI request failed: {str(openai_error)}, falling back to enhanced test data")
                return self._generate_enhanced_fallback_test_data(api_details)
            
        except Exception as e:
            logger.error(f"Failed to generate AI test data: {str(e)}, falling back to basic test data")
            return self._generate_enhanced_fallback_test_data(api_details if 'api_details' in locals() else {})
    
    def _generate_fallback_test_data(self, api_details: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate basic fallback test data when AI generation fails."""
        try:
            # Try to extract example data from curl if available
            if 'curl_example' in api_details:
                curl_example = api_details['curl_example']
                extracted_data = self._extract_data_from_curl(curl_example)
                if extracted_data:
                    return [
                        {
                            "scenario": "Basic test from API example",
                            "data": extracted_data
                        }
                    ]
            
            # Generate basic test scenarios
            basic_scenarios = [
                {
                    "scenario": "Normal case",
                    "data": {
                        "message": "Test message",
                        "data": "sample test data",
                        "timestamp": datetime.now().isoformat(),
                        "test": True
                    }
                },
                {
                    "scenario": "Simple case",
                    "data": {
                        "test": "simple test data"
                    }
                },
                {
                    "scenario": "Complex case",
                    "data": {
                        "user": "Test User",
                        "email": "test@example.com",
                        "data": ["item1", "item2", "item3"],
                        "count": 42,
                        "active": True,
                        "metadata": {
                            "source": "test",
                            "version": "1.0"
                        }
                    }
                }
            ]
            
            return basic_scenarios
            
        except Exception as e:
            logger.error(f"Failed to generate fallback test data: {str(e)}")
            return [
                {
                    "scenario": "Emergency fallback",
                    "data": {"test": "data"}
                }
            ]
    
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

            # Make request to OpenAI with test validator configuration
            response = await openai_service.make_openai_request(
                system_prompt=system_prompt, 
                user_prompt=user_prompt, 
                prompt_config=prompts,
                user_id=test_request.user_id,
                operation_type="test_validation",
                api_slug=test_request.api_slug
            )
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
    
    def _generate_enhanced_fallback_test_data(self, api_details: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Generate enhanced fallback test data with more realistic scenarios."""
        try:
            # Extract API context using the same logic as the main generation
            context = self._extract_api_context(api_details)
            
            api_purpose = context['api_purpose']
            processing_type = context['processing_type']
            expected_fields = context['expected_fields']
            
            # Try to extract data from curl example if available
            sample_data = None
            if 'curl_example' in api_details:
                sample_data = self._extract_data_from_curl(api_details['curl_example'])
            
            # Generate context-aware test scenarios
            test_scenarios = []
            
            # Generate scenarios based on the actual API context
            test_scenarios = self._generate_context_aware_scenarios(context, sample_data)
            
            logger.info(f"Generated {len(test_scenarios)} enhanced fallback test scenarios")
            return test_scenarios
            
        except Exception as e:
            logger.error(f"Error generating enhanced fallback test data: {e}")
            # Fall back to the basic method if enhanced fails
            return self._generate_fallback_test_data(api_details)
    
    def _extract_api_context(self, api_details: Dict[str, Any]) -> Dict[str, str]:
        """Dynamically extract API context by analyzing the actual code and documentation."""
        try:
            # Get basic information
            api_description = api_details.get('description', 'API for data processing')
            api_functionality = api_details.get('functionality', api_description)
            expected_output = api_details.get('expected_output', 'JSON response with processed data')
            documentation = api_details.get('documentation', '')
            curl_example = api_details.get('curl_example', '')
            code = api_details.get('code', '')
            
            # Try to extract sample input from curl example
            sample_input = None
            if curl_example:
                extracted_data = self._extract_data_from_curl(curl_example)
                if extracted_data:
                    sample_input = json.dumps(extracted_data, indent=2)
            
            # Analyze the actual API code to extract parameters and functionality
            code_analysis = self._analyze_api_code(code if code else '')
            
            # Extract from documentation structure (if available)
            doc_analysis = self._analyze_documentation(documentation)
            
            # Combine all sources of information
            api_purpose = api_description
            processing_type = "data processing"
            expected_fields = "data"
            input_type = "JSON object"
            
            # Use code analysis as primary source
            if code_analysis['parameters']:
                expected_fields = ", ".join(code_analysis['parameters'])
                api_purpose = code_analysis['inferred_purpose'] or api_description
                processing_type = code_analysis['processing_type'] or processing_type
                input_type = code_analysis['input_structure'] or input_type
                
                # Enhance context with actual code content for better AI understanding
                if code:
                    # Extract meaningful context from the code itself
                    code_context = self._extract_code_context_for_ai(code, code_analysis['parameters'])
                    if code_context:
                        api_purpose = code_context.get('purpose', api_purpose)
                        processing_type = code_context.get('processing_type', processing_type)
                        api_description = code_context.get('description', api_description)
            # Enhance with documentation analysis
            if doc_analysis['parameters']:
                # Merge parameters from documentation
                doc_params = set(doc_analysis['parameters'])
                code_params = set(code_analysis['parameters'])
                all_params = doc_params.union(code_params)
                if all_params:
                    expected_fields = ", ".join(sorted(all_params))
            
            # Use curl example to validate and enhance
            if sample_input:
                try:
                    sample_data = json.loads(sample_input)
                    if isinstance(sample_data, dict):
                        sample_params = list(sample_data.keys())
                        if sample_params:
                            # This gives us the actual expected structure
                            expected_fields = ", ".join(sample_params)
                            # Infer input type from sample structure
                            input_type = self._infer_input_type_from_sample(sample_data)
                except:
                    pass
            
            return {
                'description': api_description,
                'functionality': api_functionality,
                'expected_output': expected_output,
                'sample_input': sample_input,
                'expected_fields': expected_fields,
                'input_type': input_type,
                'processing_type': processing_type,
                'api_purpose': api_purpose
            }
            
        except Exception as e:
            logger.error(f"Error extracting API context: {e}")
            # Return defaults if analysis fails
            return {
                'description': api_details.get('description', 'API for data processing'),
                'functionality': api_details.get('functionality', 'Data processing and response generation'),
                'expected_output': api_details.get('expected_output', 'JSON response with processed data'),
                'sample_input': None,
                'expected_fields': "data",
                'input_type': "JSON object",
                'processing_type': "data processing",
                'api_purpose': api_details.get('description', 'API for data processing')
            }
    
    def _analyze_api_code(self, code: str) -> Dict[str, Any]:
        """Analyze the actual API code to extract parameters, functionality, and structure."""
        try:
            import re
            import ast
            
            analysis = {
                'parameters': [],
                'inferred_purpose': None,
                'processing_type': None,
                'input_structure': None,
                'return_structure': None
            }
            
            if not code:
                return analysis
            
            # Extract function definition and parameters
            # Look for async def or def followed by function signature
            func_pattern = r'(?:async\s+)?def\s+(\w+)\s*\([^)]*request[^)]*\):'
            func_matches = re.findall(func_pattern, code)
            
            # Extract request body parsing patterns
            request_patterns = [
                r'request\.json\(\)',
                r'await\s+request\.json\(\)',
                r'request_data\s*=\s*request\.json\(\)',
                r'data\s*=\s*await\s+request\.json\(\)',
                r'body\s*=\s*request\.json\(\)'
            ]
            
            # Extract parameters from Pydantic model definitions
            pydantic_params = self._extract_pydantic_fields(code)
            parameters = set(pydantic_params)
            
            # Extract parameters from actual data access patterns
            data_access_patterns = [
                r'input_data\[[\'"]([\w_]+)[\'"]\]',
                r'input_data\.get\([\'\"]([\w_]+)[\'\"]',  # Match input_data.get('text', ...)
                r'input_data\.get\([\'\"]([\w_]+)[\'\"],',  # Match with comma after parameter
                r'request\.(\w+)',
                r'(\w+)\s*=\s*input_data\[[\'"]\w+[\'"]\]',
                r'(\w+)\s*=\s*input_data\.get\([\'\"]\w+[\'\"]',
                r'[\'\"]([\w_]+)[\'\"]\s*not\s+in\s+input_data',  # Check for 'text' not in input_data
                r'[\'\"]([\w_]+)[\'\"]\s*in\s+input_data',  # Check for 'text' in input_data
                r'if\s+not\s+input_data\s+or\s+[\'\"]([\w_]+)[\'\"]\s+not\s+in\s+input_data'  # Validation patterns
            ]
            
            for pattern in data_access_patterns:
                matches = re.findall(pattern, code)
                parameters.update(matches)
                # Debug logging - always log for debugging
                logger.info(f"Testing pattern '{pattern}': {matches}")
                if matches:
                    logger.info(f"✓ Found parameters using pattern '{pattern}': {matches}")
                
            # Also look for file processing patterns
            file_patterns = [
                r'file_bytes\.decode\([\'\"]([\w_-]+)[\'\"]\)',  # file encoding
                r'(\w+)\s*=\s*file_bytes',  # file assignment
            ]
            
            for pattern in file_patterns:
                matches = re.findall(pattern, code)
                # Don't add encoding names, only meaningful parameters
                if pattern == file_patterns[0]:  # encoding pattern
                    continue
                parameters.update(matches)
            
            analysis['parameters'] = list(parameters)
            
            # Debug logging to see what parameters we extracted
            logger.info(f"Extracted parameters from code analysis: {list(parameters)}")
            if code:
                logger.info(f"Code analysis for API - Code length: {len(code)} chars, first 200 chars: {code[:200]}")
            else:
                logger.info("No code available for analysis")
            
            # Infer purpose from function names, variable names, and operations
            code_lower = code.lower()
            
            # Extract purpose from function names, comments, and docstrings only
            analysis['inferred_purpose'] = self._extract_purpose_from_code_structure(code)
            analysis['processing_type'] = self._extract_processing_type_from_code_structure(code)
            
            # Infer input structure from parameter usage
            if parameters:
                if len(parameters) == 1 and 'data' in parameters:
                    analysis['input_structure'] = 'JSON object with "data" field containing the main input'
                else:
                    analysis['input_structure'] = f'JSON object with fields: {", ".join(sorted(parameters))}'
            
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing API code: {e}")
            return {
                'parameters': [],
                'inferred_purpose': None,
                'processing_type': None,
                'input_structure': None,
                'return_structure': None
            }
    
    def _analyze_documentation(self, documentation: str) -> Dict[str, Any]:
        """Extract parameter information from API documentation."""
        try:
            import re
            
            analysis = {
                'parameters': [],
                'descriptions': {}
            }
            
            if not documentation:
                return analysis
            
            # Look for parameter tables or lists in documentation
            # Common patterns: "Name | Type | Required | Description"
            param_patterns = [
                r'[\|]\s*(\w+)\s*[\|]\s*\w+\s*[\|]',  # Table format
                r'(\w+)\s*\([^)]+\):\s*[^.\n]+',      # Parameter(type): description
                r'[\'"]([\w_]+)[\'"]:\s*[^,\n}]+',    # JSON-like format
                r'- (\w+):',                          # List format
                r'`(\w+)`'                            # Code format
            ]
            
            parameters = set()
            for pattern in param_patterns:
                matches = re.findall(pattern, documentation)
                parameters.update(matches)
            
            # Filter out common non-parameter words
            excluded_words = {'api', 'endpoint', 'response', 'status', 'success', 'error', 'result', 'output'}
            parameters = {p for p in parameters if p.lower() not in excluded_words and len(p) > 1}
            
            analysis['parameters'] = list(parameters)
            return analysis
            
        except Exception as e:
            logger.error(f"Error analyzing documentation: {e}")
            return {'parameters': [], 'descriptions': {}}
    
    def _infer_input_type_from_sample(self, sample_data: Dict) -> str:
        """Infer the input type description from sample data structure."""
        try:
            if not isinstance(sample_data, dict):
                return "JSON object"
            
            field_descriptions = []
            for key, value in sample_data.items():
                if isinstance(value, str):
                    field_descriptions.append(f'"{key}" (text)')
                elif isinstance(value, (int, float)):
                    field_descriptions.append(f'"{key}" (number)')
                elif isinstance(value, bool):
                    field_descriptions.append(f'"{key}" (boolean)')
                elif isinstance(value, list):
                    field_descriptions.append(f'"{key}" (array)')
                elif isinstance(value, dict):
                    field_descriptions.append(f'"{key}" (object)')
                else:
                    field_descriptions.append(f'"{key}"')
            
            if field_descriptions:
                return f"JSON object with {', '.join(field_descriptions)}"
            else:
                return "JSON object"
                
        except Exception:
            return "JSON object"
    
    def _generate_context_aware_scenarios(self, context: Dict[str, str], sample_data: Dict = None) -> List[Dict[str, Any]]:
        """Generate test scenarios based on the actual API context and parameters using AI."""
        try:
            test_scenarios = []
            
            # Scenario 1: Use sample data if available
            if sample_data:
                test_scenarios.append({
                    "scenario": "Sample input test",
                    "data": sample_data
                })
            else:
                # Use the existing AI-powered generate_test_data method
                # This will be called from the main generate_test_data method
                # For now, return basic scenarios that will be enhanced by the main method
                test_scenarios.append({
                    "scenario": "AI-generated test",
                    "data": {"data": "test input"}
                })
            
            return test_scenarios
            
        except Exception as e:
            logger.error(f"Error generating context-aware scenarios: {e}")
            # Fallback to basic scenario
            return [{
                "scenario": "Basic input test",
                "data": {"data": "test input"}
            }]
    
  
    def _extract_purpose_from_code_structure(self, code: str) -> str:
        """Extract API purpose from function names, docstrings, and comments only."""
        try:
            import re
            
            # Extract function names
            func_pattern = r'(?:async\s+)?def\s+(\w+)\s*\('
            functions = re.findall(func_pattern, code)
            
            # Extract docstrings
            docstring_pattern = r'"""([^"]+)"""'
            docstrings = re.findall(docstring_pattern, code)
            
            # Extract comments
            comment_pattern = r'#\s*(.+)'
            comments = re.findall(comment_pattern, code)
            
            # Combine all extracted text
            all_text = ' '.join(functions + docstrings + comments)
            
            # Return the extracted text as purpose (no interpretation)
            return all_text.strip() if all_text.strip() else "API functionality"
            
        except Exception as e:
            logger.error(f"Error extracting purpose from code: {e}")
            return "API functionality"
    
    def _extract_processing_type_from_code_structure(self, code: str) -> str:
        """Extract processing type from return statements and variable assignments."""
        try:
            import re
            
            # Look for return patterns
            return_pattern = r'return\s+(.+)'
            returns = re.findall(return_pattern, code)
            
            # Look for variable assignments that might indicate processing
            assignment_pattern = r'(\w+)\s*=\s*(.+)'
            assignments = re.findall(assignment_pattern, code)
            
            # Return basic processing description based on what we find
            if returns or assignments:
                return "data processing and response generation"
            else:
                return "data processing"
                
        except Exception as e:
            logger.error(f"Error extracting processing type: {e}")
            return "data processing"
    
    def _extract_code_context_for_ai(self, code: str, parameters: List[str]) -> Dict[str, str]:
        """Dynamically extract context from code to help AI generate better test data."""
        try:
            import re
            
            context = {}
            
            # Extract docstrings and comments that describe functionality
            docstring_pattern = r'"""([^"]+)"""'
            docstrings = re.findall(docstring_pattern, code, re.DOTALL)
            
            comment_pattern = r'#\s*(.+)'
            comments = re.findall(comment_pattern, code)
            
            # Combine meaningful text from docstrings and comments
            meaningful_text = []
            for doc in docstrings:
                # Clean up docstring content
                cleaned = re.sub(r'\s+', ' ', doc.strip())
                if len(cleaned) > 10:  # Only meaningful content
                    meaningful_text.append(cleaned)
            
            for comment in comments:
                cleaned = comment.strip()
                if len(cleaned) > 5 and not cleaned.startswith('TODO'):  # Skip trivial comments
                    meaningful_text.append(cleaned)
            
            # Extract function and variable names that give clues about functionality
            func_pattern = r'(?:async\s+)?def\s+(\w+)\s*\('
            functions = re.findall(func_pattern, code)
            
            # Look for external API calls or library usage
            api_call_patterns = [
                r'(\w+)\.chat\.completions\.create',  # OpenAI calls
                r'client\.(\w+)',  # Generic client calls
                r'requests\.(\w+)',  # HTTP requests
                r'(\w+_\w+)\s*=.*\.create',  # API object creation
            ]
            
            api_calls = []
            for pattern in api_call_patterns:
                matches = re.findall(pattern, code)
                api_calls.extend(matches)
            
            # Extract model or service references
            model_pattern = r'model\s*=\s*[\'\"]([\w\-\.]+)[\'\"]'
            models = re.findall(model_pattern, code)
            
            # Build context description based on what we found
            if meaningful_text:
                # Use the most descriptive docstring/comment
                best_description = max(meaningful_text, key=len)
                context['purpose'] = best_description
                context['description'] = f"API that {best_description.lower()}"
            
            if api_calls:
                if 'chat' in api_calls or 'completions' in api_calls:
                    context['processing_type'] = "AI-powered text processing"
                elif 'requests' in api_calls or 'get' in api_calls or 'post' in api_calls:
                    context['processing_type'] = "external API integration and data processing"
                else:
                    context['processing_type'] = f"data processing using {', '.join(set(api_calls))}"
            
            if models:
                context['ai_model_used'] = models[0]
                if not context.get('processing_type'):
                    context['processing_type'] = f"AI processing using {models[0]}"
            
            # Infer from parameters and code structure
            if parameters:
                param_hints = []
                for param in parameters:
                    if param == 'text':
                        param_hints.append("text input for processing")
                    elif param == 'data':
                        param_hints.append("data input for analysis")
                    elif param == 'file':
                        param_hints.append("file content for processing")
                    elif param in ['email', 'message', 'content']:
                        param_hints.append(f"{param} for analysis")
                    else:
                        param_hints.append(f"{param} parameter")
                
                if param_hints and not context.get('purpose'):
                    context['purpose'] = f"Process {', '.join(param_hints)}"
            
            return context
            
        except Exception as e:
            logger.error(f"Error extracting code context for AI: {e}")
            return {}
    
    def _extract_pydantic_fields(self, code: str) -> set:
        """Extract field names from Pydantic model definitions in the code."""
        try:
            import re
            
            fields = set()
            
            # Look for Pydantic model class definitions
            class_pattern = r'class\s+(\w+)\(BaseModel\):(.*?)(?=class|\Z)'
            model_matches = re.findall(class_pattern, code, re.DOTALL)
            
            for model_name, model_body in model_matches:
                # Extract field definitions within the model
                field_patterns = [
                    r'(\w+):\s*(?:Optional\[)?[\w\[\], ]+(?:\])?\s*=',  # field: type = default
                    r'(\w+):\s*(?:Optional\[)?[\w\[\], ]+(?:\])?(?:\s*$|\s*\n)',  # field: type
                ]
                
                for pattern in field_patterns:
                    field_matches = re.findall(pattern, model_body)
                    fields.update(field_matches)
            
            # Also look for fields accessed as attributes in the main logic
            attr_pattern = r'request\.(\w+)'
            attr_matches = re.findall(attr_pattern, code)
            fields.update(attr_matches)
            
            # Filter out common non-field attributes
            excluded = {'model_dump', 'dict', 'json', 'parse_obj', 'validate', 'schema'}
            fields = {f for f in fields if f not in excluded and not f.startswith('_')}
            
            return fields
            
        except Exception as e:
            logger.error(f"Error extracting Pydantic fields: {e}")
            return set()
    

# Global instance
test_service = TestService()