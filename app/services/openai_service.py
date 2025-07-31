from openai import OpenAI
from typing import Tuple, Optional
import logging
import time
from ..config import settings
from .usage_service import usage_service

logger = logging.getLogger(__name__)

class OpenAIService:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not configured. Please set OPENAI_API_KEY environment variable.")
        
        logger.info("Initializing OpenAI client...")
        self.client = OpenAI(api_key=settings.OPENAI_API_KEY)
        logger.info("OpenAI client initialized successfully")
    
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
        - model="gpt-3.5-turbo" or "gpt-4"
        
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
            model="gpt-3.5-turbo",
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
            model="gpt-3.5-turbo",
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
            "ai_model": "gpt-3.5-turbo",
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
            response = await self._make_openai_request(system_prompt, user_prompt)
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
        
        system_prompt = """You are an expert API documentation generator specializing in OpenAPI/Swagger specifications.
        Generate comprehensive, precise, and developer-friendly API documentation that follows OpenAPI 3.0 standards.
        Include all necessary details for proper API integration and usage.
        """
        
        user_prompt = f"""
        Based on this API code and original request, generate comprehensive API documentation including:

        1. OpenAPI 3.0 Specification (in YAML format) with:
           - Complete endpoint details (path, method, operationId)
           - Request/response schemas
           - All parameters (query, path, body)
           - Authentication requirements
           - Examples for requests/responses
           - Error responses
           - Tags and grouping
           - Rate limiting info
        
        2. Markdown Documentation:
           - Overview and purpose
           - Authentication guide
           - Detailed endpoint documentation
           - Request/response examples
           - Error handling guide
           - Rate limiting details
        
        3. Practical Examples:
           - Curl example
           - Python client example
           - Request/response examples in JSON
        
        Original Request: {prompt}
        
        Generated Code:
        {code}
        """
        
        # Track usage
        start_time = time.time()
        success = False
        error_message = None
        response_length = 0
        
        try:
            response = await self._make_openai_request(system_prompt, user_prompt)
            doc, curl = self._parse_documentation_response(response)
            
            success = True
            response_length = len(doc) + len(curl)
            
            return doc, curl
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
    
    async def _make_openai_request(self, system_prompt: str, user_prompt: str) -> str:
        """Make a request to OpenAI API."""
        import asyncio
        
        # Run the synchronous OpenAI call in a thread pool
        def make_request():
            try:
                logger.info(f"Making OpenAI request with model: {settings.OPENAI_MODEL}")
                response = self.client.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.3,
                    max_tokens=2000
                )
                
                content = response.choices[0].message.content
                if content is None:
                    logger.error("OpenAI returned None content")
                    return ""
                
                logger.info(f"OpenAI response received, length: {len(content)}")
                return content
                
            except Exception as e:
                logger.error(f"Error in OpenAI request: {str(e)}")
                raise e
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, make_request)
    
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