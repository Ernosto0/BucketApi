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
            with open(prompt_path, 'r') as f:
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
                        estimated_cost_cents=int((estimated_input_tokens + estimated_output_tokens) * 0.002 * 100),  # GPT-3.5-turbo estimate
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
            code=code
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
                        estimated_cost_cents=int((estimated_input_tokens + estimated_output_tokens) * 0.002 * 100),
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
                    max_completion_tokens=prompt_config.get("max_completion_tokens", 2000),
                    temperature=prompt_config.get("temperature", 0.7)
                )
                
                content = response.choices[0].message.content
                if content is None or content.strip() == "":
                    logger.warning(f"OpenAI returned empty/None content with model {model}")
                    logger.warning(f"Response details - Choice count: {len(response.choices) if response.choices else 0}")
                    if hasattr(response.choices[0], 'finish_reason'):
                        logger.warning(f"Finish reason: {response.choices[0].finish_reason}")
                    
                    # Try with fallback model if the primary model returns empty content
                    fallback_model = "gpt-4o-mini"
                    if model != fallback_model:
                        logger.info(f"Trying fallback model: {fallback_model}")
                        fallback_response = self.client.chat.completions.create(
                            model=fallback_model,
                            messages=[
                                {"role": "system", "content": system_prompt},
                                {"role": "user", "content": user_prompt}
                            ],
                            max_completion_tokens=prompt_config.get("max_completion_tokens", 2000),
                            temperature=prompt_config.get("temperature", 0.7)
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

    def _estimate_openai_cost(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Estimate OpenAI API cost in cents."""
        # Rough pricing estimates (as of 2024)
        pricing = {
            "gpt-4": {"input": 0.03, "output": 0.06},  # per 1K tokens
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-4o-mini": {"input": 0.0015, "output": 0.002},
            "gpt-3.5-turbo": {"input": 0.003, "output": 0.004},
            "gpt-3.5-turbo-16k": {"input": 0.003, "output": 0.004},
            # GPT-5 models (based on your pricing table)
            "gpt-5": {"input": 1.25, "output": 10.00},
            "gpt-5-mini": {"input": 0.25, "output": 2.00},
            "gpt-5-nano": {"input": 0.05, "output": 0.40},
            "gpt-5-chat-latest": {"input": 1.25, "output": 10.00}
        }
        
        # Default to gpt-3.5-turbo pricing if model not found
        model_pricing = pricing.get(model, pricing["gpt-5-mini"])
        
        input_cost = (input_tokens / 1000) * model_pricing["input"]
        output_cost = (output_tokens / 1000) * model_pricing["output"]
        
        return int((input_cost + output_cost) * 100)  # Convert to cents
    
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
                openapi_yaml = sections['OpenAPI Specification']
                openapi_spec = yaml.safe_load(openapi_yaml)
            except Exception as e:
                logger.error(f"Failed to parse OpenAPI spec: {e}")
                openapi_spec = {"error": "Failed to parse OpenAPI specification"}
        
        # Extract documentation and examples
        documentation = sections.get('Documentation', '').strip()
        curl_example = sections.get('Curl Example', '').strip()
        
        return documentation, openapi_spec, curl_example
# Global instance
openai_service = OpenAIService() 