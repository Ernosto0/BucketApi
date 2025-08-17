import asyncio
import logging
import sys
import traceback
from typing import Any, Dict, Optional
from functools import partial
import multiprocessing
import signal
import psutil
import platform

logger = logging.getLogger(__name__)

class SandboxService:
    """Service for executing API code in a sandboxed environment with resource limits."""
    
    def __init__(self):
        self.DEFAULT_TIMEOUT_SECONDS = 10  # Reduced from 30 to 10 seconds
        self.DEFAULT_MEMORY_LIMIT_MB = 512  # Default memory limit in MB
        self.DEFAULT_CPU_TIME_LIMIT_SECONDS = 10  # Reduced from 30 to 10 seconds
        self.IS_WINDOWS = platform.system() == 'Windows'
        
    def _set_process_limits(self, memory_mb: int, cpu_time: int):
        """Set resource limits for the current process."""
        # On Windows, we can only monitor (not limit) resources
        # Resource limits will be enforced through monitoring
        pass
        
    def _extract_api_logic(self, code: str) -> str:
        """Extract the actual API logic from the FastAPI wrapper."""
        try:
            # Look for the run() function
            run_start = code.find('def run(')
            if run_start != -1:
                # Find the function body
                body_start = code.find(':', run_start)
                if body_start != -1:
                    # Find the next function or EOF
                    next_def = code.find('\ndef ', body_start)
                    if next_def == -1:
                        next_def = code.find('\n@app', body_start)
                    if next_def == -1:
                        next_def = code.find('\nif __name__', body_start)
                    if next_def == -1:
                        next_def = len(code)
                    
                    # Extract the run function
                    extracted_code = code[run_start:next_def]
                    
                    # Add result assignment
                    if 'async def run' in extracted_code:
                        extracted_code += '\nresult = await run(file_bytes=file_bytes, input_data=input_data)'
                    else:
                        extracted_code += '\nresult = run(file_bytes=file_bytes, input_data=input_data)'
                    
                    return extracted_code

            # Fallback to old method if no run() function found
            if 'app = FastAPI()' not in code:
                return code

            # Find the execute function body
            start = code.find('async def execute():')
            if start == -1:
                start = code.find('def execute():')  # Try non-async version
                if start == -1:
                    return code

            # Find the try block
            try_start = code.find('try:', start)
            if try_start == -1:
                return code

            # Find the actual code block
            code_start = code.find('\n', try_start) + 1
            code_end = code.find('        return result')
            if code_end == -1:
                code_end = code.find('return result')  # Try without indentation
                if code_end == -1:
                    return code

            # Extract and clean the code
            extracted_code = code[code_start:code_end].strip()
            # Remove common indentation
            lines = extracted_code.split('\n')
            if lines:
                common_indent = len(lines[0]) - len(lines[0].lstrip())
                extracted_code = '\n'.join(line[common_indent:] if line.startswith(' ' * common_indent) else line for line in lines)

            # Remove FastAPI-specific imports and app creation
            extracted_code = '\n'.join(line for line in extracted_code.split('\n') 
                                     if 'from fastapi' not in line 
                                     and 'app = FastAPI()' not in line
                                     and '@app' not in line
                                     and 'uvicorn.run' not in line)

            # Add result variable initialization
            extracted_code = 'result = None\n' + extracted_code

            return extracted_code
        except Exception as e:
            logger.error(f"Error extracting API logic: {str(e)}")
            # If extraction fails, return original code
            return code

    def _execute_in_process(self, code: str, input_data: Dict[str, Any], 
                          memory_limit_mb: int, cpu_limit: int,
                          file_bytes: Optional[bytes] = None) -> Any:
        """Execute code in the current process with resource limits."""
        try:
            # Set process resource limits
            self._set_process_limits(memory_limit_mb, cpu_limit)
            
            # Create namespace for execution
            namespace = {
                'input_data': input_data,
                'file_bytes': file_bytes,
                'result': None
            }
            
            # Monitor process resources
            process = psutil.Process()
            start_time = process.cpu_times().user

            # Create a temporary module to execute the code
            import tempfile
            import os
            import importlib.util
            import asyncio
            
            # Create a temporary file with the code
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
                temp_file.write(code)
                temp_file_path = temp_file.name
            
            try:
                # Import the temporary module
                spec = importlib.util.spec_from_file_location("api_module", temp_file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Execute the run function
                if hasattr(module, 'run'):
                    # Create a new event loop for this process
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        # Run the async function and get the result
                        result = loop.run_until_complete(module.run(file_bytes=file_bytes, input_data=input_data))
                        namespace['result'] = result
                    finally:
                        loop.close()
                else:
                    raise Exception("API code must define a 'run' function")
            finally:
                # Clean up the temporary file
                os.unlink(temp_file_path)
            
            # Check CPU time
            cpu_time = process.cpu_times().user - start_time
            if cpu_time > cpu_limit:
                raise Exception(f"CPU time limit exceeded: {cpu_time:.2f}s > {cpu_limit}s")
            
            # Check memory usage
            memory_used = process.memory_info().rss / (1024 * 1024)  # Convert to MB
            if memory_used > memory_limit_mb:
                raise Exception(f"Memory limit exceeded: {memory_used:.2f}MB > {memory_limit_mb}MB")
            
            # Get the result
            if 'result' not in namespace:
                raise Exception("API code must set a 'result' variable")
            
            return namespace['result']
            
        except Exception as e:
            # Log detailed error for debugging but don't expose to users
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"API execution error: {str(e)}", exc_info=True)
            # Return safe error message
            raise Exception("API execution failed. Please check your code and try again.")
    
    async def execute_api_sandboxed(
        self,
        code: str,
        input_data: Dict[str, Any],
        file_bytes: Optional[bytes] = None,
        timeout_seconds: int = None,
        memory_limit_mb: int = None,
        cpu_limit: int = None
    ) -> Any:
        """
        Execute API code in a sandboxed environment with resource limits.
        """
        # Use default limits if not specified
        timeout = timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS
        memory_limit = memory_limit_mb or self.DEFAULT_MEMORY_LIMIT_MB
        cpu_time_limit = cpu_limit or self.DEFAULT_CPU_TIME_LIMIT_SECONDS
        
        # Create a process pool for execution
        ctx = multiprocessing.get_context('spawn')  # Use spawn for better isolation
        pool = None
        
        try:
            pool = ctx.Pool(1)  # Single worker for API execution
            
            # Prepare the execution function
            exec_func = partial(self._execute_in_process, code, input_data, 
                              memory_limit, cpu_time_limit, file_bytes)
            
            # Create a future for the process pool execution
            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, pool.apply, exec_func)
            
            # Wait for result with timeout
            try:
                result = await asyncio.wait_for(future, timeout=timeout)
                return result
            except asyncio.TimeoutError:
                # Kill the worker process on timeout
                if pool:
                    pool.terminate()
                raise Exception(f"API execution timed out after {timeout} seconds")
            
        except Exception as e:
            logger.error(f"Error in sandboxed execution: {str(e)}")
            raise
        
        finally:
            # Clean up
            if pool:
                pool.close()
                pool.join()
            
            # Force cleanup of any remaining processes
            for child in psutil.Process().children(recursive=True):
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass

    @staticmethod
    def _wrap_code_in_fastapi(code: str) -> str:
        """Wrap user code in FastAPI app with proper imports and error handling."""
        # Check if code already has a run() function
        if 'def run(' in code:
            return code  # Don't wrap if it already has a run function

        # First extract any existing FastAPI wrapper
        if 'app = FastAPI()' in code:
            start = code.find('async def execute():')
            if start != -1:
                try_start = code.find('try:', start)
                if try_start != -1:
                    code_start = code.find('\n', try_start) + 1
                    code_end = code.find('        return result')
                    if code_end != -1:
                        code = code[code_start:code_end].strip()

        # Create an async run() function wrapper
        wrapper = '''async def run(file_bytes=None, input_data=None):
    """Execute the API logic."""
    try:
        # Execute the API code
{indented_code}
        return result
    except Exception as e:
        return {{"error": str(e), "result": None}}

# FastAPI wrapper for HTTP endpoints
from fastapi import FastAPI, HTTPException
import traceback

app = FastAPI()

@app.post("/")
async def execute():
    try:
        return run(None, input_data)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"API execution failed: {str(e)}\\n{traceback.format_exc()}"
        )
'''
        # Indent the code
        indented_code = '\n'.join(f"        {line}" for line in code.split('\n'))
        return wrapper.format(indented_code=indented_code)

# Initialize the service
sandbox_service = SandboxService() 