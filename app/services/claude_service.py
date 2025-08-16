import anthropic
from typing import Tuple, Optional
import logging
import time
import uuid
from ..config import settings
from .usage_service import usage_service
from .logging_service import logging_service, LogLevel, LogCategory
from .exceptions import LLMBaseError, PromptBuildError, LLMAPIError, CodeExtractionError, UsageLoggingError
from tenacity import retry, stop_after_attempt, wait_exponential

from ..prompts.claude.prompt_loader import (
    load_claude_prompt, 
    format_claude_prompt, 
    get_claude_prompt_config,
    validate_claude_response
)
logger = logging.getLogger(__name__)

class ClaudeService:
    def __init__(self):
        if not settings.CLAUDE_API_KEY:
            raise ValueError("Claude API key not configured. Please set CLAUDE_API_KEY environment variable.")
        
        logger.info("Initializing Claude client...")
        self.client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)
        logger.info("Claude client initialized successfully")
    
    async def generate_api_code(self, prompt: str, sample_input: Optional[str] = None, 
                               expected_output: Optional[str] = None, user_id: Optional[str] = None,
                               api_key_id: Optional[str] = None) -> str:
        """Generate FastAPI-compatible code based on user prompt."""
        request_id = uuid.uuid4()
        logger.info(f"Generating API code for prompt: {prompt[:100]}... Request ID: {request_id}")
        
        # Load prompt configuration
        try:
            prompt_config = load_claude_prompt("api_code_generator")
            
            # Prepare prompt variables
            prompt_vars = {
                "prompt": prompt,
                "sample_input_section": f"\nSample Input: {sample_input}" if sample_input else "",
                "expected_output_section": f"\nExpected Output: {expected_output}" if expected_output else ""
            }
            
            # Format prompts using the template
            system_prompt, user_prompt = format_claude_prompt(prompt_config, **prompt_vars)
            
        except Exception as e:
            # Fallback to create a PromptBuildError
            prompt_error = PromptBuildError(
                message=f"Failed to load or format API code generation prompt: {str(e)}",
                user_id=user_id,
                request_id=str(request_id),
                api_slug="code_generation",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "prompt_name": "api_code_generator",
                    "error_type": type(e).__name__,
                    "original_error": str(e)
                }
            )
            await logging_service.log_llm_error(prompt_error)
            raise prompt_error
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            logger.info("Making Claude API request...")
            response = await self._make_claude_request(
                system_prompt, user_prompt,
                user_id=user_id,
                api_key_id=api_key_id,
                operation_type="code_generation",
                api_slug="code_generation"
            )
            logger.info("Claude API request successful")
            
            try:
                code = self._extract_code_from_response(response)
                logger.info(f"Generated code length: {len(code)} characters")
                
                # Validate using prompt configuration
                if not validate_claude_response(code, prompt_config):
                    raise CodeExtractionError(
                        message="Code validation failed according to prompt rules",
                        user_id=user_id,
                        request_id=str(request_id),
                        api_slug="code_generation",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_code_length": len(code) if code else 0,
                            "response_preview": response[:200],
                            "validation_rules": prompt_config.get("validation_rules", {})
                        }
                    )
                
                # Additional basic validation
                if not code or len(code.strip()) < 10:
                    raise CodeExtractionError(
                        message="No meaningful code extracted from Claude response",
                        user_id=user_id,
                        request_id=str(request_id),
                        api_slug="code_generation",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_code_length": len(code) if code else 0,
                            "response_preview": response[:200]
                        }
                    )
                
                success = True
                response_length = len(code)
                return code
                
            except CodeExtractionError as extraction_error:
                # Log the extraction error
                await logging_service.log_llm_error(extraction_error)
                raise extraction_error
                
        except (LLMAPIError, PromptBuildError, CodeExtractionError) as llm_error:
            # These are already logged in _make_claude_request or above
            error_message = str(llm_error)
            logger.error(f"LLM error in generate_api_code: {str(llm_error)}")
            raise llm_error
            
        except Exception as e:
            # Create and log unexpected error
            unexpected_error = LLMAPIError(
                message=f"Unexpected error in API code generation: {str(e)}",
                user_id=user_id,
                request_id=str(request_id),
                api_slug="code_generation",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "exception_type": type(e).__name__,
                    "original_error": str(e)
                }
            )
            
            await logging_service.log_llm_error(unexpected_error)
            error_message = str(e)
            logger.error(f"Failed to generate API code: {str(e)}")
            raise unexpected_error
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                # Log LLM call
                try:
                    await logging_service.log_llm_call(
                        service_type="claude",
                        model_name=settings.CLAUDE_MODEL,
                        operation_type="code_generation",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        prompt_length=prompt_length,
                        response_content=code if success else None,
                        response_length=response_length,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        estimated_cost_cents=int((estimated_input_tokens + estimated_output_tokens) * 0.003 * 100),  # Rough estimate
                        duration_ms=duration_ms,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        success=success,
                        error_message=error_message,
                        operation_context={
                            "has_sample_input": sample_input is not None,
                            "has_expected_output": expected_output is not None,
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        },
                        request_id=str(request_id)
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log LLM call: {log_error}")
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="code_generation",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "has_sample_input": sample_input is not None,
                            "has_expected_output": expected_output is not None,
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        },
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")
    
    async def modify_api_code(self, prompt: str, sample_input: Optional[str] = None, 
                             expected_output: Optional[str] = None, existing_code: Optional[str] = None,
                             user_id: Optional[str] = None, api_key_id: Optional[str] = None,
                             api_slug: Optional[str] = None) -> str:
        """Modify existing API code based on user prompt."""
        request_id = str(uuid.uuid4())
        logger.info(f"Modifying API code with prompt: {prompt[:100]}... Request ID: {request_id}")
        
        # Load prompt configuration
        try:
            prompt_config = load_claude_prompt("api_code_modifier")
            
            # Prepare prompt variables
            prompt_vars = {
                "prompt": prompt,
                "existing_code": existing_code or "No existing code provided",
                "sample_input_section": f"\n\nSample Input: {sample_input}" if sample_input else "",
                "expected_output_section": f"\n\nExpected Output: {expected_output}" if expected_output else ""
            }
            
            # Format prompts using the template
            system_prompt, user_prompt = format_claude_prompt(prompt_config, **prompt_vars)
            
        except Exception as e:
            # Fallback to create a PromptBuildError
            prompt_error = PromptBuildError(
                message=f"Failed to load or format API code modification prompt: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug or "code_modification",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "prompt_name": "api_code_modifier",
                    "error_type": type(e).__name__,
                    "original_error": str(e),
                    "existing_code_length": len(existing_code) if existing_code else 0
                }
            )
            await logging_service.log_llm_error(prompt_error)
            raise prompt_error
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            logger.info("Making Claude API request for code modification...")
            response = await self._make_claude_request(
                system_prompt, user_prompt,
                user_id=user_id,
                api_key_id=api_key_id,
                operation_type="code_modification",
                api_slug=api_slug or "code_modification"
            )
            logger.info("Claude API request for modification successful")
            
            try:
                # Validate using prompt configuration first
                if not validate_claude_response(response, prompt_config):
                    raise CodeExtractionError(
                        message="Code modification validation failed according to prompt rules",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "code_modification",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "response_preview": response[:200],
                            "validation_rules": prompt_config.get("validation_rules", {}),
                            "preservation_rules": prompt_config.get("validation_rules", {}).get("preservation_rules", {})
                        }
                    )
                
                code = self._extract_code_from_response(response)
                logger.info(f"Modified code length: {len(code)} characters")
                
                # Additional validation for code modification
                if not code or len(code.strip()) < 10:
                    raise CodeExtractionError(
                        message="No meaningful modified code extracted from Claude response",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "code_modification",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_code_length": len(code) if code else 0,
                            "response_preview": response[:200],
                            "existing_code_length": len(existing_code) if existing_code else 0
                        }
                    )
                
                # Validate that function signature is preserved (if existing code had it)
                if existing_code and "def run(" in existing_code and "def run(" not in code:
                    raise CodeExtractionError(
                        message="Modified code missing required 'run' function signature",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "code_modification",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_code_length": len(code),
                            "missing_signature": "def run(",
                            "preservation_failed": True
                        }
                    )
                
                success = True
                response_length = len(code)
                return code
                
            except CodeExtractionError as extraction_error:
                # Log the extraction error
                await logging_service.log_llm_error(extraction_error)
                raise extraction_error
                
        except (LLMAPIError, PromptBuildError, CodeExtractionError) as llm_error:
            # These are already logged in _make_claude_request or above
            error_message = str(llm_error)
            logger.error(f"LLM error in modify_api_code: {str(llm_error)}")
            raise llm_error
            
        except Exception as e:
            # Create and log unexpected error
            unexpected_error = LLMAPIError(
                message=f"Unexpected error in API code modification: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug or "code_modification",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "exception_type": type(e).__name__,
                    "original_error": str(e),
                    "existing_code_length": len(existing_code) if existing_code else 0,
                    "prompt_length": len(prompt)
                }
            )
            
            await logging_service.log_llm_error(unexpected_error)
            error_message = str(e)
            logger.error(f"Failed to modify API code: {str(e)}")
            raise unexpected_error
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                # Log LLM call
                try:
                    await logging_service.log_llm_call(
                        service_type="claude",
                        model_name=settings.CLAUDE_MODEL,
                        operation_type="code_modification",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        prompt_length=prompt_length,
                        response_content=code if success else None,
                        response_length=response_length,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        estimated_cost_cents=int((estimated_input_tokens + estimated_output_tokens) * 0.003 * 100),
                        duration_ms=duration_ms,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message,
                        operation_context={
                            "has_sample_input": sample_input is not None,
                            "has_expected_output": expected_output is not None,
                            "has_existing_code": existing_code is not None,
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        },
                        request_id=str(request_id)
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log LLM call: {log_error}")
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="code_modification",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "has_sample_input": sample_input is not None,
                            "has_expected_output": expected_output is not None,
                            "has_existing_code": existing_code is not None,
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        },
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")
    
    async def generate_documentation(self, code: str, prompt: str, user_id: Optional[str] = None,
                                    api_key_id: Optional[str] = None, api_slug: Optional[str] = None) -> Tuple[str, str]:
        """Generate documentation and curl example for the generated API."""
        request_id = str(uuid.uuid4())
        
        # Load prompt configuration
        try:
            prompt_config = load_claude_prompt("documentation_generator")
            
            # Prepare prompt variables
            prompt_vars = {
                "prompt": prompt,
                "code": code
            }
            
            # Format prompts using the template
            system_prompt, user_prompt = format_claude_prompt(prompt_config, **prompt_vars)
            
        except Exception as e:
            # Fallback to create a PromptBuildError
            prompt_error = PromptBuildError(
                message=f"Failed to load or format documentation generation prompt: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug or "documentation_generation",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "prompt_name": "documentation_generator",
                    "error_type": type(e).__name__,
                    "original_error": str(e)
                }
            )
            await logging_service.log_llm_error(prompt_error)
            raise prompt_error
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self._make_claude_request(
                system_prompt, user_prompt,
                user_id=user_id,
                api_key_id=api_key_id,
                operation_type="documentation_generation",
                api_slug=api_slug or "documentation_generation"
            )
            
            try:
                # Validate using prompt configuration first
                if not validate_claude_response(response, prompt_config):
                    raise CodeExtractionError(
                        message="Documentation validation failed according to prompt rules",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "documentation_generation",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "response_preview": response[:200],
                            "validation_rules": prompt_config.get("validation_rules", {}),
                            "expected_format": prompt_config.get("expected_format", {})
                        }
                    )
                
                doc, curl = self._parse_documentation_response(response)
                
                # Additional specific validation
                expected_format = prompt_config.get("expected_format", {})
                min_doc_length = expected_format.get("documentation_min_length", 20)
                min_curl_length = expected_format.get("curl_min_length", 10)
                
                if not doc or len(doc.strip()) < min_doc_length:
                    raise CodeExtractionError(
                        message=f"Documentation too short (min {min_doc_length} chars required)",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "documentation_generation",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_doc_length": len(doc) if doc else 0,
                            "extracted_curl_length": len(curl) if curl else 0,
                            "response_preview": response[:200],
                            "min_required_length": min_doc_length
                        }
                    )
                
                if not curl or len(curl.strip()) < min_curl_length:
                    raise CodeExtractionError(
                        message=f"Curl example too short (min {min_curl_length} chars required)",
                        user_id=user_id,
                        request_id=request_id,
                        api_slug=api_slug or "documentation_generation",
                        model_name=settings.CLAUDE_MODEL,
                        details={
                            "response_length": len(response),
                            "extracted_doc_length": len(doc) if doc else 0,
                            "extracted_curl_length": len(curl) if curl else 0,
                            "response_preview": response[:200],
                            "min_required_length": min_curl_length
                        }
                    )
                
                success = True
                response_length = len(doc) + len(curl)
                return doc, curl
                
            except CodeExtractionError as extraction_error:
                # Log the extraction error
                await logging_service.log_llm_error(extraction_error)
                raise extraction_error
                
        except (LLMAPIError, PromptBuildError, CodeExtractionError) as llm_error:
            # These are already logged in _make_claude_request or above
            error_message = str(llm_error)
            logger.error(f"LLM error in generate_documentation: {str(llm_error)}")
            raise llm_error
            
        except Exception as e:
            # Create and log unexpected error
            unexpected_error = LLMAPIError(
                message=f"Unexpected error in documentation generation: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug or "documentation_generation",
                model_name=settings.CLAUDE_MODEL,
                details={
                    "exception_type": type(e).__name__,
                    "original_error": str(e),
                    "code_length": len(code),
                    "prompt_length": len(prompt)
                }
            )
            
            await logging_service.log_llm_error(unexpected_error)
            error_message = str(e)
            logger.error(f"Failed to generate documentation: {str(e)}")
            raise unexpected_error
        finally:
            # Record usage regardless of success/failure
            if user_id:
                duration_ms = int((time.time() - start_time) * 1000)
                prompt_length = len(user_prompt)
                
                # Estimate tokens (rough approximation: 1 token ≈ 4 characters)
                estimated_input_tokens = max(1, (len(system_prompt) + len(user_prompt)) // 4)
                estimated_output_tokens = max(1, response_length // 4) if success else 0
                
                # Log LLM call
                try:
                    await logging_service.log_llm_call(
                        service_type="claude",
                        model_name=settings.CLAUDE_MODEL,
                        operation_type="documentation",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        prompt_length=prompt_length,
                        response_content=f"Doc: {doc[:200]}... Curl: {curl[:200]}..." if success else None,
                        response_length=response_length,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        estimated_cost_cents=int((estimated_input_tokens + estimated_output_tokens) * 0.003 * 100),
                        duration_ms=duration_ms,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message,
                        operation_context={
                            "code_length": len(code),
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        }
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log LLM call: {log_error}")
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="claude",
                        operation_type="documentation",
                        model_name=settings.CLAUDE_MODEL,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        prompt_length=prompt_length,
                        response_length=response_length,
                        request_duration_ms=duration_ms,
                        operation_context={
                            "code_length": len(code),
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        },
                        api_slug=api_slug,
                        success=success,
                        error_message=error_message
                    )
                except Exception as usage_error:
                    logger.error(f"Failed to record usage: {usage_error}")
    

    async def _make_claude_request(self, system_prompt: str, user_prompt: str, 
                                  user_id: Optional[str] = None, api_key_id: Optional[str] = None, 
                                  operation_type: str = "general", api_slug: Optional[str] = None) -> str:
        """Make a request to Claude API."""
        import asyncio
        
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Run the synchronous Claude call in a thread pool
        def make_request():
            response = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=2000,
                temperature=0.3,
                system=system_prompt,
                messages=[
                    {"role": "user", "content": user_prompt}
                ]
            )
            return response.content[0].text, response
        
        loop = asyncio.get_event_loop()
        
        try:
            content, response = await loop.run_in_executor(None, make_request)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log successful LLM call
            try:
                usage = response.usage if hasattr(response, 'usage') else None
                input_tokens = usage.input_tokens if usage else len(system_prompt + user_prompt) // 4
                output_tokens = usage.output_tokens if usage else len(content) // 4
                total_tokens = input_tokens + output_tokens
                
                # Estimate cost (rough calculation for Claude pricing)
                estimated_cost_cents = self._estimate_claude_cost(settings.CLAUDE_MODEL, input_tokens, output_tokens)
                
                await logging_service.log_llm_call(
                    service_type="claude",
                    model_name=settings.CLAUDE_MODEL,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],  # Limit for logging
                    user_prompt=user_prompt[:1000],  # Limit for logging
                    prompt_length=len(system_prompt + user_prompt),
                    response_content=content[:1000] if content else None,  # Limit for logging
                    response_length=len(content) if content else 0,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                    estimated_cost_cents=estimated_cost_cents,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    success=True,
                    request_id=request_id
                )
            except Exception as log_error:
                # Just log the failure, don't raise an exception for logging issues
                logger.error(f"Failed to log successful Claude LLM call: {log_error}")
            
            return content
            
        except anthropic.RateLimitError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Create specific LLM error for rate limiting
            rate_limit_error = LLMAPIError(
                message=f"Claude API rate limit exceeded: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug,
                model_name=settings.CLAUDE_MODEL,
                details={
                    "error_type": "rate_limit",
                    "duration_ms": duration_ms,
                    "original_error": str(e)
                }
            )
            
            # Log the error using the new error logging
            await logging_service.log_llm_error(rate_limit_error)
            
            # Also log failed LLM call for completeness
            try:
                await logging_service.log_llm_call(
                    service_type="claude",
                    model_name=settings.CLAUDE_MODEL,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],
                    user_prompt=user_prompt[:1000],
                    prompt_length=len(system_prompt + user_prompt),
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    success=False,
                    error_message=str(e),
                    request_id=request_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log failed Claude LLM call: {log_error}")
            
            raise rate_limit_error
            
        except anthropic.AuthenticationError as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Create specific LLM error for authentication issues
            auth_error = LLMAPIError(
                message=f"Claude API authentication failed: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug,
                model_name=settings.CLAUDE_MODEL,
                details={
                    "error_type": "authentication",
                    "duration_ms": duration_ms,
                    "original_error": str(e)
                }
            )
            
            # Log the error
            await logging_service.log_llm_error(auth_error)
            
            # Also log failed LLM call
            try:
                await logging_service.log_llm_call(
                    service_type="claude",
                    model_name=settings.CLAUDE_MODEL,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],
                    user_prompt=user_prompt[:1000],
                    prompt_length=len(system_prompt + user_prompt),
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    success=False,
                    error_message=str(e),
                    request_id=request_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log failed Claude LLM call: {log_error}")
            
            raise auth_error
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Create generic LLM error for unexpected issues
            llm_error = LLMAPIError(
                message=f"Claude API call failed: {str(e)}",
                user_id=user_id,
                request_id=request_id,
                api_slug=api_slug,
                model_name=settings.CLAUDE_MODEL,
                details={
                    "error_type": "api_error",
                    "duration_ms": duration_ms,
                    "original_error": str(e),
                    "exception_type": type(e).__name__
                }
            )
            
            # Log the error
            await logging_service.log_llm_error(llm_error)
            
            # Also log failed LLM call
            try:
                await logging_service.log_llm_call(
                    service_type="claude",
                    model_name=settings.CLAUDE_MODEL,
                    operation_type=operation_type,
                    system_prompt=system_prompt[:1000],
                    user_prompt=user_prompt[:1000],
                    prompt_length=len(system_prompt + user_prompt),
                    duration_ms=duration_ms,
                    user_id=user_id,
                    api_key_id=api_key_id,
                    api_slug=api_slug,
                    success=False,
                    error_message=str(e),
                    request_id=request_id
                )
            except Exception as log_error:
                logger.error(f"Failed to log failed Claude LLM call: {log_error}")
            
            raise llm_error
            
    # TODO CHANGE THIS LOGIC 
    def _estimate_claude_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Estimate Claude API cost in cents."""
        # Rough pricing estimates for Claude (as of 2024)
        pricing = {
            "claude-3-opus-20240229": {"input": 0.015, "output": 0.075},  # per 1K tokens
            "claude-3-sonnet-20240229": {"input": 0.003, "output": 0.015},
            "claude-3-haiku-20240307": {"input": 0.00025, "output": 0.00125}
        }
        
        # Default to sonnet pricing if model not found
        model_pricing = pricing.get(model, pricing["claude-3-sonnet-20240229"])
        
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]
        
        return int((input_cost + output_cost) * 100)  # Convert to cents
    
    def _extract_code_from_response(self, response: str) -> str:
        """Extract Python code from Claude response."""
        # Remove markdown code blocks if present
        if "```python" in response:
            start = response.find("```python") + 9
            end = response.find("```", start)
            if end != -1:
                code = response[start:end].strip()
            else:
                code = response.strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            if end != -1:
                code = response[start:end].strip()
            else:
                code = response.strip()
        else:
            code = response.strip()
        
        # Post-process to fix common syntax issues
        code = self._fix_syntax_issues(code)
        
        return code
    
    def _fix_syntax_issues(self, code: str) -> str:
        """Fix common syntax issues in generated code."""
        # First, fix obvious syntax errors
        lines = code.split('\n')
        fixed_lines = []
        
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Fix malformed return statements in except blocks
            if 'return {' in line and 'except Exception as e:' in code:
                # Look for incomplete return statements
                if line.strip().endswith('return {'):
                    # Find the matching closing brace
                    brace_count = line.count('{') - line.count('}')
                    j = i + 1
                    while j < len(lines) and brace_count > 0:
                        next_line = lines[j]
                        brace_count += next_line.count('{') - next_line.count('}')
                        if brace_count == 0:
                            break
                        j += 1
                    
                    # Check if there's a malformed return after this block
                    if j + 1 < len(lines) and 'return {' in lines[j + 1]:
                        # Remove the malformed return line
                        lines.pop(j + 1)
                        if j + 1 < len(lines) and lines[j + 1].strip() == '}':
                            lines.pop(j + 1)
            
            # Fix lines that have return statements without proper structure
            if line.strip().startswith('return {') and i + 1 < len(lines):
                next_line = lines[i + 1]
                # If next line starts with return, it's likely malformed
                if next_line.strip().startswith('return {'):
                    # Skip the malformed line
                    i += 1
                    continue
            
            fixed_lines.append(line)
            i += 1
        
        code = '\n'.join(fixed_lines)
        
        # Fix missing return statements in try blocks
        if 'result = {' in code and 'return {"result": result, "message": "success"}' not in code:
            # Find the position to insert the return statement
            lines = code.split('\n')
            for i, line in enumerate(lines):
                if line.strip().startswith('result = {'):
                    # Find the end of the result dictionary
                    brace_count = 0
                    for j in range(i, len(lines)):
                        brace_count += lines[j].count('{') - lines[j].count('}')
                        if brace_count == 0 and '}' in lines[j]:
                            # Insert return statement after the result definition
                            lines.insert(j + 1, '')
                            lines.insert(j + 2, '        return {"result": result, "message": "success"}')
                            break
                    break
            code = '\n'.join(lines)
        
        # Remove duplicate or malformed return statements
        lines = code.split('\n')
        cleaned_lines = []
        for i, line in enumerate(lines):
            # Skip lines that are just closing braces after return statements
            if line.strip() == '}' and i > 0 and 'return {' in cleaned_lines[-1]:
                # Check if this is a malformed closing brace
                if i + 1 < len(lines) and lines[i + 1].strip() == '':
                    continue
            cleaned_lines.append(line)
        
        return '\n'.join(cleaned_lines)
    
    def _parse_documentation_response(self, response: str) -> Tuple[str, str]:
        """Parse documentation and curl example from Claude response."""
        parts = response.split("## Curl Example")
        if len(parts) == 2:
            documentation = parts[0].replace("## Documentation", "").strip()
            curl_example = parts[1].strip()
            return documentation, curl_example
        else:
            # Fallback if parsing fails
            return response, "curl -X POST 'your-endpoint-url' -H 'Content-Type: application/json' -d '{}'"

# Global instance
claude_service = ClaudeService()
