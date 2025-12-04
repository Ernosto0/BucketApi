"""
Venv Execution Service for running generated APIs in the api_venv.
Handles code execution with proper isolation and resource limits.
"""
import asyncio
import logging
import subprocess
import tempfile
import os
import json
import signal
import psutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from datetime import datetime
import time

from .package_installer import package_installer

logger = logging.getLogger(__name__)

class VenvExecutionService:
    """Executes generated API code in the isolated api_venv."""
    
    def __init__(self):
        self.package_installer = package_installer
        
        # Execution limits
        self.DEFAULT_TIMEOUT_SECONDS = 30
        self.DEFAULT_MEMORY_LIMIT_MB = 512
        self.DEFAULT_CPU_TIME_LIMIT_SECONDS = 20
        
        # Execution statistics
        self._execution_stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "timeout_executions": 0,
            "memory_limit_exceeded": 0,
            "dependency_install_count": 0,
            "average_execution_time": 0.0,
            "last_reset": datetime.now().isoformat()
        }
    
    async def execute_api_in_venv(
        self,
        code: str,
        input_data: Dict[str, Any],
        file_bytes: Optional[bytes] = None,
        timeout_seconds: int = None,
        memory_limit_mb: int = None,
        auto_install_dependencies: bool = True,
        skip_dependency_check: bool = False,
        database_url: Optional[str] = None
    ) -> Any:
        """
        Execute API code in the api_venv with automatic dependency management.
        
        Args:
            code: Python code to execute
            input_data: Input data for the API
            file_bytes: Optional file bytes for file processing APIs
            timeout_seconds: Execution timeout
            memory_limit_mb: Memory limit
            auto_install_dependencies: Whether to auto-install missing dependencies
            
        Returns:
            API execution result
        """
        start_time = time.time()
        execution_id = f"exec_{int(start_time * 1000)}"
        
        try:
            logger.info(f"Starting API execution {execution_id}")
            
            # Step 1: Prepare execution environment (install dependencies if needed)
            if auto_install_dependencies and not skip_dependency_check:
                logger.info(f"Preparing execution environment for {execution_id}")
                prep_result = await self.package_installer.prepare_execution_environment(code)
                
                if not prep_result["success"]:
                    logger.error(f"Failed to prepare environment for {execution_id}: {prep_result.get('error')}")
                    self._update_execution_stats(False, time.time() - start_time, "dependency_failure")
                    raise Exception(f"Environment preparation failed: {prep_result.get('error')}")
                
                if prep_result.get("installation_results"):
                    self._execution_stats["dependency_install_count"] += 1
                    logger.info(f"Installed dependencies for {execution_id}: {list(prep_result['installation_results'].keys())}")
            elif skip_dependency_check:
                logger.debug(f"Skipping dependency check for {execution_id} (already prepared)")
            
            # Step 2: Execute the code
            logger.info(f"Executing code in api_venv for {execution_id}")
            result = await self._execute_code_in_venv(
                code=code,
                input_data=input_data,
                file_bytes=file_bytes,
                timeout_seconds=timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS,
                memory_limit_mb=memory_limit_mb or self.DEFAULT_MEMORY_LIMIT_MB,
                execution_id=execution_id,
                database_url=database_url
            )
            
            # Step 3: Update statistics and return result
            execution_time = time.time() - start_time
            self._update_execution_stats(True, execution_time, "success")
            
            logger.info(f"API execution {execution_id} completed successfully in {execution_time:.2f}s")
            return result
            
        except asyncio.TimeoutError:
            execution_time = time.time() - start_time
            self._update_execution_stats(False, execution_time, "timeout")
            logger.error(f"API execution {execution_id} timed out after {execution_time:.2f}s")
            raise Exception(f"API execution timed out after {timeout_seconds or self.DEFAULT_TIMEOUT_SECONDS} seconds")
            
        except Exception as e:
            execution_time = time.time() - start_time
            self._update_execution_stats(False, execution_time, "error")
            logger.error(f"API execution {execution_id} failed after {execution_time:.2f}s: {e}")
            raise
    
    async def _execute_code_in_venv(
        self,
        code: str,
        input_data: Dict[str, Any],
        file_bytes: Optional[bytes],
        timeout_seconds: int,
        memory_limit_mb: int,
        execution_id: str,
        database_url: Optional[str] = None
    ) -> Any:
        """Execute code in the api_venv with resource limits."""
        
        # Get Python executable from api_venv
        python_path = self.package_installer.venv_manager.get_api_venv_python_path()
        
        # Create temporary file with the code
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            # Prepare the execution wrapper
            execution_wrapper = self._create_execution_wrapper(code, input_data, file_bytes)
            temp_file.write(execution_wrapper)
            temp_file_path = temp_file.name
        
        try:
            # Execute in subprocess with resource limits
            result = await self._run_subprocess_with_limits(
                python_path=python_path,
                script_path=temp_file_path,
                timeout_seconds=timeout_seconds,
                memory_limit_mb=memory_limit_mb,
                execution_id=execution_id,
                database_url=database_url
            )
            
            return result
            
        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(f"Failed to clean up temp file {temp_file_path}: {e}")
    
    def _create_execution_wrapper(self, code: str, input_data: Dict[str, Any], file_bytes: Optional[bytes]) -> str:
        """Create a wrapper script that executes the API code and returns JSON result."""
        
        # Prepare input data as JSON (properly escaped for Python)
        input_data_json = json.dumps(input_data) if input_data else "{}"
        file_bytes_b64 = None
        if file_bytes:
            import base64
            file_bytes_b64 = base64.b64encode(file_bytes).decode('utf-8')
        
        # Use repr to safely embed JSON string in Python code
        input_data_repr = repr(input_data_json)
        
        # Safe representation of file_bytes_b64 for the script
        file_bytes_b64_repr = f'"{file_bytes_b64}"' if file_bytes_b64 else "None"
        
        wrapper_code = f'''
import json
import sys
import traceback
import base64
import io

# Input data (load from JSON to ensure proper Python types)
input_data_json_str = {input_data_repr}
input_data = json.loads(input_data_json_str) if input_data_json_str else None
file_bytes = None

# Decode file bytes if provided
file_bytes_b64 = {file_bytes_b64_repr}
if file_bytes_b64:
    try:
        file_bytes = base64.b64decode(file_bytes_b64)
    except Exception as e:
        print(json.dumps({{"error": f"Failed to decode file bytes: {{str(e)}}", "success": False}}))
        sys.exit(1)

# Execute the API code
try:
    # Insert the generated API code here
{self._indent_code(code, "    ")}
    
    # The code should define a run() function
    if 'run' not in locals() and 'run' not in globals():
        print(json.dumps({{"error": "API code must define a 'run' function", "success": False}}))
        sys.exit(1)
    
    # Execute the run function
    import asyncio
    import inspect
    
    if inspect.iscoroutinefunction(run):
        # Async function
        result = asyncio.run(run(file_bytes=file_bytes, input_data=input_data))
    else:
        # Sync function
        result = run(file_bytes=file_bytes, input_data=input_data)
    
    # Handle binary data by base64-encoding it
    if isinstance(result, bytes):
        result_encoded = {{
            "_type": "bytes",
            "_data": base64.b64encode(result).decode('ascii')
        }}
    elif isinstance(result, io.BytesIO):
        result_encoded = {{
            "_type": "bytes",
            "_data": base64.b64encode(result.getvalue()).decode('ascii')
        }}
    else:
        result_encoded = result
    
    # Return the result as JSON
    output = {{
        "result": result_encoded,
        "success": True,
        "execution_info": {{
            "has_file_bytes": file_bytes is not None,
            "input_data_keys": list(input_data.keys()) if input_data else [],
            "result_type": type(result).__name__
        }}
    }}
    
    print(json.dumps(output))
    
except Exception as e:
    # Return error as JSON
    error_output = {{
        "error": str(e),
        "success": False,
        "traceback": traceback.format_exc(),
        "execution_info": {{
            "has_file_bytes": file_bytes is not None,
            "input_data_keys": list(input_data.keys()) if input_data else []
        }}
    }}
    
    print(json.dumps(error_output))
    sys.exit(1)
'''
        
        return wrapper_code
    
    def _indent_code(self, code: str, indent: str) -> str:
        """Indent code by the specified amount."""
        lines = code.split('\n')
        indented_lines = [indent + line if line.strip() else line for line in lines]
        return '\n'.join(indented_lines)
    
    async def _run_subprocess_with_limits(
        self,
        python_path: str,
        script_path: str,
        timeout_seconds: int,
        memory_limit_mb: int,
        execution_id: str,
        database_url: Optional[str] = None
    ) -> Any:
        """Run subprocess with resource limits and monitoring."""
        
        process = None
        try:
            # Prepare environment variables
            env = os.environ.copy()
            if database_url:
                env['DATABASE_URL'] = database_url
                logger.info(f"Setting DATABASE_URL environment variable for execution {execution_id}")
            
            # Start the subprocess
            process = await asyncio.create_subprocess_exec(
                python_path, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                limit=1024 * 1024  # 1MB buffer limit
            )
            
            # Monitor process with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout_seconds
                )
                
                # Check if process completed successfully
                if process.returncode != 0:
                    error_msg = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
                    logger.error(f"Process {execution_id} failed with return code {process.returncode}: {error_msg}")
                    raise Exception(f"API execution failed: {error_msg}")
                
                # Parse the JSON output - handle potential encoding issues
                try:
                    output_str = stdout.decode('utf-8').strip()
                except UnicodeDecodeError as decode_error:
                    logger.error(f"Failed to decode stdout as UTF-8 for {execution_id}: {decode_error}")
                    logger.debug(f"First 100 bytes of stdout: {stdout[:100]}")
                    raise Exception(f"API execution produced non-text output. Make sure your API returns JSON-serializable data, not raw binary data.")
                
                try:
                    result = json.loads(output_str)
                    
                    if not result.get("success", False):
                        error_msg = result.get("error", "Unknown error")
                        traceback_info = result.get("traceback", "")
                        logger.error(f"API execution {execution_id} failed: {error_msg}")
                        if traceback_info:
                            logger.debug(f"Traceback for {execution_id}: {traceback_info}")
                        raise Exception(error_msg)
                    
                    # Decode base64-encoded binary data if present
                    api_result = result.get("result")
                    if isinstance(api_result, dict) and api_result.get("_type") == "bytes":
                        # This was binary data that was base64-encoded
                        import base64
                        return base64.b64decode(api_result["_data"])
                    
                    return api_result
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON output for {execution_id}: {output_str}")
                    raise Exception(f"Invalid JSON output from API execution: {str(e)}")
                
            except asyncio.TimeoutError:
                # Kill the process if it times out
                if process and process.returncode is None:
                    try:
                        process.kill()
                        await process.wait()
                    except Exception as e:
                        logger.warning(f"Failed to kill timed out process {execution_id}: {e}")
                
                logger.error(f"Process {execution_id} timed out after {timeout_seconds} seconds")
                raise asyncio.TimeoutError(f"API execution timed out after {timeout_seconds} seconds")
                
        except Exception as e:
            # Ensure process cleanup
            if process and process.returncode is None:
                try:
                    process.kill()
                    await process.wait()
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup process {execution_id}: {cleanup_error}")
            
            raise
    
    def _update_execution_stats(self, success: bool, execution_time: float, failure_type: str = None):
        """Update execution statistics."""
        self._execution_stats["total_executions"] += 1
        
        if success:
            self._execution_stats["successful_executions"] += 1
        else:
            self._execution_stats["failed_executions"] += 1
            
            if failure_type == "timeout":
                self._execution_stats["timeout_executions"] += 1
            elif failure_type == "memory":
                self._execution_stats["memory_limit_exceeded"] += 1
        
        # Update average execution time
        total_execs = self._execution_stats["total_executions"]
        current_avg = self._execution_stats["average_execution_time"]
        self._execution_stats["average_execution_time"] = (
            (current_avg * (total_execs - 1) + execution_time) / total_execs
        )
    
    def get_execution_stats(self) -> Dict:
        """Get execution statistics."""
        return {
            "execution_stats": self._execution_stats.copy(),
            "venv_info": self.package_installer.venv_manager.get_venv_info(),
            "installation_status": self.package_installer.get_installation_status(),
            "timestamp": datetime.now().isoformat()
        }
    
    def reset_execution_stats(self):
        """Reset execution statistics."""
        self._execution_stats = {
            "total_executions": 0,
            "successful_executions": 0,
            "failed_executions": 0,
            "timeout_executions": 0,
            "memory_limit_exceeded": 0,
            "dependency_install_count": 0,
            "average_execution_time": 0.0,
            "last_reset": datetime.now().isoformat()
        }
    
    async def test_venv_execution(self) -> Dict:
        """Test the venv execution system with a simple API."""
        test_code = '''
import json
import datetime

async def run(file_bytes=None, input_data=None):
    """Test API that returns system info."""
    return {
        "message": "Venv execution test successful",
        "timestamp": datetime.datetime.now().isoformat(),
        "input_received": input_data,
        "has_file": file_bytes is not None,
        "python_version": "3.x"
    }
'''
        
        test_input = {"test": True, "timestamp": datetime.now().isoformat()}
        
        try:
            logger.info("Running venv execution test...")
            
            result = await self.execute_api_in_venv(
                code=test_code,
                input_data=test_input,
                timeout_seconds=10,
                auto_install_dependencies=False  # No dependencies needed for test
            )
            
            return {
                "success": True,
                "test_result": result,
                "message": "Venv execution test passed",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Venv execution test failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Venv execution test failed",
                "timestamp": datetime.now().isoformat()
            }
    
    async def cleanup_and_maintenance(self) -> Dict:
        """Perform cleanup and maintenance tasks."""
        try:
            logger.info("Starting cleanup and maintenance...")
            
            # Check if cleanup is needed
            cleanup_result = self.package_installer.cleanup_if_needed()
            
            # Get current status
            status = self.get_execution_stats()
            
            return {
                "success": True,
                "cleanup_result": cleanup_result,
                "current_status": status,
                "message": "Cleanup and maintenance completed",
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Cleanup and maintenance failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Cleanup and maintenance failed",
                "timestamp": datetime.now().isoformat()
            }

# Initialize the service
venv_execution_service = VenvExecutionService()
