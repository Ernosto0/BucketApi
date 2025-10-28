from openai import OpenAI
from typing import Dict, Tuple, Optional, Any
import logging
import time
import os
import json
from fastapi import HTTPException
from ..config import settings
from .usage_service import usage_service
from .logging_service import logging_service, LogLevel, LogCategory

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        logger.info("Initializing OpenAI client...")
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully")
            
    def _load_documentation_prompt(self) -> Dict[str, str]:
        """Load the documentation generator prompts from JSON file."""
        try:
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 
                                    'prompts', 'openai', 'documentation_generator.json')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompts = json.load(f)
            return prompts
        except Exception as e:
            logger.error(f"Failed to load documentation prompts: {str(e)}")
            raise HTTPException(status_code=500, 
                            detail="Failed to load documentation prompts")
    
    async def generate_api_code(self, prompt: str, sample_input: Optional[str] = None, 
                               expected_output: Optional[str] = None, user_id: Optional[str] = None,
                               api_key_id: Optional[str] = None) -> str:
        """Generate FastAPI-compatible code based on user prompt."""
        
        logger.info(f"Generating API code for prompt: {prompt[:100]}...")
        
        system_prompt = """You are an expert Python developer specializing in AI-powered APIs using FastAPI. 
        Generate clean, secure, and efficient Python code that implements the requested functionality.
        
        IMPORTANT: When the user requests AI-powered functionality (like text analysis, extraction, classification, etc.), 
        you SHOULD make real API calls to AI services like OpenAI, Anthropic, or other AI APIs.
        
        CRITICAL - NEVER USE THESE DEPRECATED PATTERNS:
        - openai.Completion.create() (DEPRECATED)
        - openai.ChatCompletion.create() (DEPRECATED) 
        - openai.api_key = "..." (DEPRECATED)
        - engine="text-davinci-003" (DEPRECATED)
        
        ALWAYS USE MODERN OPENAI CLIENT:
        - from openai import OpenAI
        - client = OpenAI(api_key=api_key)
        - client.chat.completions.create()
        - model="gpt-4o-mini" or "gpt-4"
        
        IMPORTANT RULES:
        1. Always wrap your code in an ASYNC function called `run(file_bytes=None, input_data=None)`
        2. The function should accept either file_bytes (bytes) or input_data (dict)
        3. Always return a JSON-serializable result
        4. CRITICAL: All external API calls MUST be async:
           - Use asyncio.to_thread() for synchronous operations
           - Use aiohttp or httpx for HTTP requests
           - Wrap OpenAI calls in asyncio.to_thread()
        5. You CAN make API calls to external AI services
        6. Never use dangerous modules like os, subprocess, eval, exec for system operations
        7. Use safe libraries: json, re, datetime, math, base64, hashlib, aiohttp/httpx, openai
        8. Include proper error handling with try-catch blocks
        9. Add docstrings and comments for clarity
        10. If working with files, assume file_bytes contains the file content
        11. For text processing, decode file_bytes to string first
        12. Return results in a structured format: {"result": your_data, "message": "success"}
        13. For AI-powered requests, make REAL API calls to OpenAI or other AI services
        14. Include API keys as environment variables or hardcode them for demo purposes
        15. Always include confidence scores and detailed AI analysis in results
        16. For PDF processing, wrap file_bytes in io.BytesIO() before passing to PDF libraries
        17. For file processing, always handle bytes properly - use io.BytesIO for binary data
        
        EXAMPLE OF PROPER ASYNC OPENAI CALL:
        ```python
        # Make AI API call
        response = await asyncio.to_thread(
            client.chat.completions.create,
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Your system message"},
                {"role": "user", "content": "Your user message"}
            ]
        )
        ```
        
        
        # Use MODERN OpenAI client (v1.0+)
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            return {"error": "OpenAI API key not found", "message": "failed"}
        
        client = OpenAI(api_key=api_key)
        
        # Make AI API call for name and date extraction
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Extract all person names and dates from the text. Return JSON with 'names' and 'dates' arrays."},
                {"role": "user", "content": f"Extract names and dates from: {text[:2000]}"}
            ],
            temperature=0.2,
            max_tokens=500
        )
        
        ai_response = response.choices[0].message.content
        
        # Try to parse AI response as JSON, fallback if needed
        try:
            extracted_data = json.loads(ai_response)
        except:
            extracted_data = {"raw_response": ai_response}
        
        result = {
            "extracted_data": extracted_data,
            "ai_model": "gpt-4o-mini",
            "text_length": len(text),
            "confidence": 0.9,
            "timestamp": datetime.now().isoformat()
        }
        
        return {"result": result, "message": "success"}
            
    except Exception as e:
        return {"error": str(e), "message": "failed"}
         ```
        """
        
        user_prompt = f"""
        Please generate Python code for the following API:
        
        Description: {prompt}
        """
        
        if sample_input:
            user_prompt += f"\nSample Input: {sample_input}"
        
        if expected_output:
            user_prompt += f"\nExpected Output: {expected_output}"
        
        user_prompt += "\n\nGenerate only the Python code, no explanations."
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            logger.info("Making OpenAI API request...")
            response = await self.make_openai_request(
                system_prompt, user_prompt,
                user_id=user_id,
                api_key_id=api_key_id,
                operation_type="code_generation"
            )
            logger.info("OpenAI API request successful")
            code = self._extract_code_from_response(response)
            logger.info(f"Generated code length: {len(code)} characters")
            
            success = True
            response_length = len(code)
            
            return code
        except Exception as e:
            error_message = str(e)
            logger.error(f"Failed to generate API code: {str(e)}")
            raise Exception(f"Failed to generate API code: {str(e)}")
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
                        service_type="openai",
                        model_name=settings.OPENAI_MODEL,
                        operation_type="code_generation",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        prompt_length=prompt_length,
                        response_content=code if success else None,
                        response_length=response_length,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        estimated_cost_cents=self._calculate_openai_cost(settings.OPENAI_MODEL, estimated_input_tokens, estimated_output_tokens),
                        duration_ms=duration_ms,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        success=success,
                        error_message=error_message,
                        operation_context={
                            "has_sample_input": sample_input is not None,
                            "has_expected_output": expected_output is not None,
                            "prompt_preview": prompt[:100] + "..." if len(prompt) > 100 else prompt
                        }
                    )
                except Exception as log_error:
                    logger.error(f"Failed to log LLM call: {log_error}")
                
                try:
                    await usage_service.record_usage(
                        user_id=user_id,
                        api_key_id=api_key_id,
                        service_type="openai",
                        operation_type="code_generation",
                        model_name=settings.OPENAI_MODEL,
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
    
    async def generate_documentation(self, code: str, prompt: str, user_id: Optional[str] = None,
                                    api_key_id: Optional[str] = None, api_slug: Optional[str] = None) -> Tuple[str, dict, str]:
        """Generate comprehensive API documentation including OpenAPI spec.
        
        Returns:
            Tuple containing:
            - Markdown documentation (str)
            - OpenAPI specification (dict)
            - Curl example (str)
        """
        
        # Load prompts from file
        prompts = self._load_documentation_prompt()
        system_prompt = prompts["system_prompt"]
        
        # Format the user prompt template with actual values
        user_prompt = prompts["user_prompt_template"].format(
            prompt=prompt,
            code=code,
            user_id=user_id or "USER_ID",
            api_slug=api_slug or "API_SLUG"
        )
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self.make_openai_request(
                system_prompt, user_prompt,
                prompt_config=self._load_documentation_prompt(),
                user_id=user_id,
                api_key_id=api_key_id,
                operation_type="documentation_generation",
                api_slug=api_slug
            )
            doc, openapi_spec, curl = self._parse_documentation_response(response)
            
            success = True
            response_length = len(doc) + len(str(openapi_spec)) + len(curl)
            
            return doc, openapi_spec, curl
        except Exception as e:
            error_message = str(e)
            raise Exception(f"Failed to generate documentation: {str(e)}")
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
                        service_type="openai",
                        model_name=settings.OPENAI_MODEL,
                        operation_type="documentation",
                        system_prompt=system_prompt,
                        user_prompt=user_prompt,
                        prompt_length=prompt_length,
                        response_content=f"Doc: {doc[:200]}... OpenAPI: {str(openapi_spec)[:100]}... Curl: {curl[:200]}..." if success else None,
                        response_length=response_length,
                        input_tokens=estimated_input_tokens,
                        output_tokens=estimated_output_tokens,
                        total_tokens=estimated_input_tokens + estimated_output_tokens,
                        estimated_cost_cents=self._calculate_openai_cost(settings.OPENAI_MODEL, estimated_input_tokens, estimated_output_tokens),
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
                        service_type="openai",
                        operation_type="documentation",
                        model_name=settings.OPENAI_MODEL,
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
    
    async def make_openai_request(self, system_prompt: str, user_prompt: str, prompt_config: Dict[str, Any] = None, 
                                 user_id: Optional[str] = None, api_key_id: Optional[str] = None, 
                                 operation_type: str = "general", api_slug: Optional[str] = None) -> str:
        """Make a request to OpenAI API with configurable parameters."""
        import asyncio
        import uuid
        
        # Use provided config or load documentation config as fallback
        if prompt_config is None:
            prompt_config = self._load_documentation_prompt()
        
        model = prompt_config.get("model", settings.OPENAI_MODEL)
        start_time = time.time()
        request_id = str(uuid.uuid4())
        
        # Run the synchronous OpenAI call in a thread pool
        def make_request():
            # First try with the specified model
            try:
                logger.info(f"Making OpenAI request with model: {model}")
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_completion_tokens=prompt_config.get("max_completion_tokens", 5000),
                )
                
                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason if hasattr(response.choices[0], 'finish_reason') else None
                
                if content is None or content.strip() == "":
                    logger.warning(f"OpenAI returned empty/None content with model {model}")
                    logger.warning(f"Response details - Choice count: {len(response.choices) if response.choices else 0}")
                    logger.warning(f"Finish reason: {finish_reason}")
                    
                    # If length limit was hit, try reducing max_completion_tokens and retry
                    if finish_reason == "length":
                        logger.warning("Response was truncated due to length limit, trying with reduced token limit")
                        reduced_tokens = max(500, prompt_config.get("max_completion_tokens", 2000) // 2)
                        logger.info(f"Retrying with reduced max_completion_tokens: {reduced_tokens}")
                        
                        retry_response = self.client.chat.completions.create(
                            model=model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            max_completion_tokens=reduced_tokens,
                        )
                        
                        retry_content = retry_response.choices[0].message.content
                        if retry_content and retry_content.strip():
                            logger.info(f"Retry with reduced tokens succeeded, length: {len(retry_content)}")
                            return retry_content, retry_response
                        else:
                            logger.warning("Retry with reduced tokens also failed")
                    
                    # Try with fallback model if the primary model returns empty content
                    fallback_model = "gpt-4o-mini"  # Use a more reliable fallback
                    if model != fallback_model:
                        logger.info(f"Trying fallback model: {fallback_model}")
                        fallback_response = self.client.chat.completions.create(
                            model=fallback_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            max_completion_tokens=prompt_config.get("max_completion_tokens", 2000),
                        )
                        
                        fallback_content = fallback_response.choices[0].message.content
                        if fallback_content and fallback_content.strip():
                            logger.info(f"Fallback model {fallback_model} succeeded, length: {len(fallback_content)}")
                            return fallback_content, fallback_response
                        else:
                            logger.error(f"Fallback model {fallback_model} also returned empty content")
                    
                    # If fallback fails or same model, return empty with original response
                    return "", response
                
                logger.info(f"OpenAI response received, length: {len(content)}")
                return content, response
                
            except Exception as e:
                logger.error(f"Error in OpenAI request: {str(e)}")
                raise e
        
        # Execute the request in thread pool
        loop = asyncio.get_event_loop()
        try:
            content, response = await loop.run_in_executor(None, make_request)
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log successful LLM call
            try:
                usage = response.usage if hasattr(response, 'usage') else None
                input_tokens = usage.prompt_tokens if usage else len(system_prompt + user_prompt) // 4
                output_tokens = usage.completion_tokens if usage else len(content) // 4
                total_tokens = usage.total_tokens if usage else input_tokens + output_tokens
                
                # Estimate cost (rough calculation for OpenAI pricing)
                estimated_cost_cents = self._estimate_openai_cost(model, input_tokens, output_tokens)
                
                await logging_service.log_llm_call(
                    service_type="openai",
                    model_name=model,
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
                logger.error(f"Failed to log OpenAI LLM call: {log_error}")
            
            return content
            
        except Exception as e:
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Log failed LLM call
            try:
                await logging_service.log_llm_call(
                    service_type="openai",
                    model_name=model,
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
                logger.error(f"Failed to log failed OpenAI LLM call: {log_error}")
            
            raise e

    def _calculate_openai_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Calculate accurate OpenAI cost using usage service."""
        from .usage_service import usage_service
        return usage_service._calculate_cost_cents(model, input_tokens, output_tokens)
    
    def _estimate_openai_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate OpenAI API cost in cents using centralized pricing."""
        # Import here to avoid circular imports
        from .api_pricing_service import api_pricing_service
        
        # Use centralized pricing from APIpricingService
        if model in api_pricing_service.AI_MODEL_BASE_COSTS:
            pricing = api_pricing_service.AI_MODEL_BASE_COSTS[model]
        else:
            # Default to gpt-4o-mini pricing if model not found (cents per 1M tokens)
            pricing = api_pricing_service.AI_MODEL_BASE_COSTS.get('gpt-4o-mini', {'input': 0.015, 'output': 0.06})
        
        # Calculate cost (pricing is in cents per 1M tokens)
        input_cost = (input_tokens / 1000000) * pricing["input"]
        output_cost = (output_tokens / 1000000) * pricing["output"]
        
        return input_cost + output_cost  # Return fractional cents
    
    async def _make_openai_request(self, system_prompt: str, user_prompt: str) -> str:
        """Make a request to OpenAI API for documentation generation (legacy method)."""
        return await self.make_openai_request(system_prompt, user_prompt, self._load_documentation_prompt())
    
    def _extract_code_from_response(self, response: str) -> str:
        """Extract Python code from OpenAI response."""
        # Remove markdown code blocks if present
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
    
    def _parse_documentation_response(self, response: str) -> Tuple[str, dict, str]:
        """Parse documentation, OpenAPI spec, and examples from OpenAI response.
        
        Returns:
            Tuple containing:
            - Markdown documentation (str)
            - OpenAPI specification (dict)
            - Curl example (str)
        """
        import yaml
        
        # Split response into sections using markdown headers
        sections = {}
        current_section = []
        current_header = None
        
        for line in response.split('\n'):
            if line.startswith('## '):
                if current_header:
                    sections[current_header] = '\n'.join(current_section).strip()
                current_header = line[3:].strip()
                current_section = []
            else:
                current_section.append(line)
                
        if current_header:
            sections[current_header] = '\n'.join(current_section).strip()
            
        # Extract OpenAPI spec
        openapi_spec = {}
        if 'OpenAPI Specification' in sections:
            try:
                openapi_yaml = sections['OpenAPI Specification'].strip()
                
                # Clean up common YAML issues that the AI might generate
                openapi_yaml = self._sanitize_yaml(openapi_yaml)
                
                openapi_spec = yaml.safe_load(openapi_yaml)
                
                # Validate it's a proper OpenAPI spec
                if not isinstance(openapi_spec, dict) or 'openapi' not in openapi_spec:
                    logger.warning("Generated YAML is not a valid OpenAPI specification")
                    openapi_spec = self._generate_fallback_openapi_spec()
                    
            except Exception as e:
                logger.error(f"Failed to parse OpenAPI spec: {e}")
                logger.error(f"Problematic YAML content: {openapi_yaml[:500]}...")
                openapi_spec = self._generate_fallback_openapi_spec()
        
        # Extract documentation and examples
        documentation = sections.get('Documentation', '').strip()
        curl_example = sections.get('Curl Example', '').strip()
        
        return documentation, openapi_spec, curl_example
    
    def _sanitize_yaml(self, yaml_content: str) -> str:
        """Sanitize YAML content to fix common issues generated by AI."""
        lines = yaml_content.split('\n')
        sanitized_lines = []
        
        for line in lines:
            # Skip empty lines at the beginning
            if not line.strip() and not sanitized_lines:
                continue
                
            # Fix unquoted strings that contain colons, quotes, or special characters
            if ':' in line and not line.strip().startswith('#'):
                # Check if this is a key-value pair
                if ': ' in line:
                    key_part, value_part = line.split(': ', 1)
                    value_part = value_part.strip()
                    
                    # Skip if it's already properly quoted or is a complex structure
                    if value_part.startswith(('"', "'", '[', '{', '|', '>', '-')):
                        sanitized_lines.append(line)
                        continue
                    
                    # Check if value needs quoting (contains special YAML characters)
                    needs_quoting = any(char in value_part for char in ['"', "'", ':', '[', ']', '{', '}', '|', '>', '@', '`', '&', '*', '!', '%', '\\'])
                    
                    # Also check for strings that look like they need quoting
                    if needs_quoting or ('Entity type:' in value_part):
                        # Escape any existing double quotes inside the string
                        escaped_value = value_part.replace('"', '\\"')
                        line = f"{key_part}: \"{escaped_value}\""
            
            sanitized_lines.append(line)
        
        return '\n'.join(sanitized_lines)
    
    def _generate_fallback_openapi_spec(self) -> dict:
        """Generate a basic fallback OpenAPI specification."""
        return {
            "openapi": "3.0.0",
            "info": {
                "title": "Generated API",
                "description": "API endpoint for processing requests",
                "version": "1.0.0"
            },
            "servers": [
                {
                    "url": "https://api.example.com",
                    "description": "API server"
                }
            ],
            "paths": {
                "/api/{user_id}/{api_slug}": {
                    "post": {
                        "summary": "Process API request",
                        "description": "Main API endpoint",
                        "parameters": [
                            {
                                "name": "user_id",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"}
                            },
                            {
                                "name": "api_slug",
                                "in": "path",
                                "required": True,
                                "schema": {"type": "string"}
                            }
                        ],
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "object",
                                                "description": "Request payload"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Success",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "success": {"type": "boolean"},
                                                "data": {"type": "object"}
                                            }
                                        }
                                    }
                                }
                            },
                            "400": {
                                "description": "Bad Request",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "error": {"type": "string"},
                                                "message": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            },
                            "500": {
                                "description": "Internal Server Error",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "error": {"type": "string"},
                                                "message": {"type": "string"}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

# Global instance
openai_service = OpenAIService() 