import anthropic
from typing import Tuple, Optional
import logging
from ..config import settings

logger = logging.getLogger(__name__)

class ClaudeService:
    def __init__(self):
        if not settings.CLAUDE_API_KEY:
            raise ValueError("Claude API key not configured. Please set CLAUDE_API_KEY environment variable.")
        
        logger.info("Initializing Claude client...")
        self.client = anthropic.Anthropic(api_key=settings.CLAUDE_API_KEY)
        logger.info("Claude client initialized successfully")
    
    async def generate_api_code(self, prompt: str, sample_input: Optional[str] = None, 
                               expected_output: Optional[str] = None) -> str:
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
        
        MANDATORY REQUIREMENTS:
        1. ALWAYS wrap your code in a function called `run(file_bytes=None, input_data=None)`
        2. The function MUST accept either file_bytes (bytes) or input_data (dict)
        3. ALWAYS return a JSON-serializable result
        4. You CAN use HTTP libraries: requests, urllib, httpx, openai
        5. You CAN make API calls to external AI services
        6. Never use dangerous modules like os, subprocess, eval, exec for system operations
        7. Use safe libraries: json, re, datetime, math, base64, hashlib, requests, openai, os (only for os.getenv)
        8. Include proper error handling with try-catch blocks
        9. Add docstrings and comments for clarity
        10. If working with files, assume file_bytes contains the file content
        11. For text processing, decode file_bytes to string first
        12. Return results in a structured format: {"result": your_data, "message": "success"}
        13. For AI-powered requests, make REAL API calls to OpenAI or other AI services
        14. Include API keys as environment variables using os.getenv() or hardcode them for demo purposes
        15. Always include confidence scores and detailed AI analysis in results
        16. For PDF processing, wrap file_bytes in io.BytesIO() before passing to PDF libraries
        17. For file processing, always handle bytes properly - use io.BytesIO for binary data
        18. ENSURE PROPER PYTHON SYNTAX - all return statements must be properly formatted
        19. ALWAYS include 'return' keyword before return statements in except blocks
        20. Use os.getenv('OPENAI_API_KEY') instead of hardcoded API keys
        21. Only import libraries that are commonly available or specified in requirements
        22. NEVER have multiple return statements in the same except block
        
        
        
        CRITICAL: Ensure all Python syntax is correct, especially return statements in except blocks.
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
        
        try:
            logger.info("Making Claude API request...")
            response = await self._make_claude_request(system_prompt, user_prompt)
            logger.info("Claude API request successful")
            code = self._extract_code_from_response(response)
            logger.info(f"Generated code length: {len(code)} characters")
            return code
        except Exception as e:
            logger.error(f"Failed to generate API code: {str(e)}")
            raise Exception(f"Failed to generate API code: {str(e)}")
    
    async def modify_api_code(self, prompt: str, sample_input: Optional[str] = None, 
                             expected_output: Optional[str] = None, existing_code: Optional[str] = None) -> str:
        """Modify existing API code based on user prompt."""
        
        logger.info(f"Modifying API code with prompt: {prompt[:100]}...")
        
        system_prompt = """You are an expert Python developer specializing in AI-powered APIs using FastAPI. 
        Modify the existing Python code based on the user's requirements while maintaining the original functionality.
        
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
        
        MANDATORY REQUIREMENTS:
        1. ALWAYS maintain the function signature `run(file_bytes=None, input_data=None)`
        2. The function MUST accept either file_bytes (bytes) or input_data (dict)
        3. ALWAYS return a JSON-serializable result
        4. You CAN use HTTP libraries: requests, urllib, httpx, openai
        5. You CAN make API calls to external AI services
        6. Never use dangerous modules like os, subprocess, eval, exec for system operations
        7. Use safe libraries: json, re, datetime, math, base64, hashlib, requests, openai, os (only for os.getenv)
        8. Include proper error handling with try-catch blocks
        9. Add docstrings and comments for clarity
        10. If working with files, assume file_bytes contains the file content
        11. For text processing, decode file_bytes to string first
        12. Return results in a structured format: {"result": your_data, "message": "success"}
        13. For AI-powered requests, make REAL API calls to OpenAI or other AI services
        14. Include API keys as environment variables using os.getenv() or hardcode them for demo purposes
        15. Always include confidence scores and detailed AI analysis in results
        16. For PDF processing, wrap file_bytes in io.BytesIO() before passing to PDF libraries
        17. For file processing, always handle bytes properly - use io.BytesIO for binary data
        18. ENSURE PROPER PYTHON SYNTAX - all return statements must be properly formatted
        19. ALWAYS include 'return' keyword before return statements in except blocks
        20. Use os.getenv('OPENAI_API_KEY') instead of hardcoded API keys
        21. Only import libraries that are commonly available or specified in requirements
        22. NEVER have multiple return statements in the same except block
        23. PRESERVE the core structure and functionality of the existing code
        24. Only modify the parts that the user specifically requests
        25. Maintain backward compatibility unless explicitly asked to break it
        
        CRITICAL: Ensure all Python syntax is correct, especially return statements in except blocks.
        """
        
        user_prompt = f"""
        Please modify the following Python code based on the requirements:
        
        Modification Request: {prompt}
        
        Existing Code:
        {existing_code or "No existing code provided"}
        """
        
        if sample_input:
            user_prompt += f"\n\nSample Input: {sample_input}"
        
        if expected_output:
            user_prompt += f"\n\nExpected Output: {expected_output}"
        
        user_prompt += "\n\nGenerate only the modified Python code, no explanations. Ensure the code maintains the same function signature and structure while implementing the requested changes."
        
        try:
            logger.info("Making Claude API request for code modification...")
            response = await self._make_claude_request(system_prompt, user_prompt)
            logger.info("Claude API request for modification successful")
            code = self._extract_code_from_response(response)
            logger.info(f"Modified code length: {len(code)} characters")
            return code
        except Exception as e:
            logger.error(f"Failed to modify API code: {str(e)}")
            raise Exception(f"Failed to modify API code: {str(e)}")
    
    async def generate_documentation(self, code: str, prompt: str) -> Tuple[str, str]:
        """Generate documentation and curl example for the generated API."""
        
        system_prompt = """You are a technical documentation expert. 
        Generate clear, concise documentation for API endpoints and provide practical curl examples.
        """
        
        user_prompt = f"""
        Based on this API code and original request, generate:
        1. Clear documentation (markdown format)
        2. A practical curl example
        
        Original Request: {prompt}
        
        Generated Code:
        {code}
        
        
        """
        
        try:
            response = await self._make_claude_request(system_prompt, user_prompt)
            return self._parse_documentation_response(response)
        except Exception as e:
            raise Exception(f"Failed to generate documentation: {str(e)}")
    

    async def _make_claude_request(self, system_prompt: str, user_prompt: str) -> str:
        """Make a request to Claude API."""
        import asyncio
        
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
            return response.content[0].text
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, make_request)
    
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
