import os
import psutil
import uuid
import asyncio
import logging
import subprocess
from datetime import datetime, timedelta
from sqlalchemy import select, update, and_
from typing import Optional, Tuple, Dict
from ..services.database import APIProcessDB, AsyncSessionLocal
from ..config import settings
import time
import aiohttp
import asyncio
import sys
import re

logger = logging.getLogger(__name__)

class APIProcessService:
    def __init__(self):
        self.base_port = 8100  # Start API ports from 8100
        self.max_port = 8999  # Maximum port number
        self.process_cleanup_interval = 300  # 5 minutes
        self.process_idle_timeout = 1800  # 30 minutes
        self.running_processes: Dict[str, subprocess.Popen] = {}
        logger.info(f"APIProcessService initialized with base port {self.base_port} and max port {self.max_port}")
        
    async def _cleanup_stale_processes(self, session) -> None:
        """Cleanup stale process entries in database."""
        import psutil
        
        try:
            # First, force cleanup any processes that haven't been accessed recently
            idle_threshold = datetime.utcnow() - timedelta(seconds=self.process_idle_timeout)
            await session.execute(
                update(APIProcessDB)
                .where(
                    and_(
                        APIProcessDB.is_running == True,
                        APIProcessDB.last_accessed < idle_threshold
                    )
                )
                .values(is_running=False)
            )
            await session.commit()
            
            # Get all processes marked as running
            result = await session.execute(
                select(APIProcessDB).where(APIProcessDB.is_running == True)
            )
            running_processes = result.scalars().all()
            
            for process in running_processes:
                is_running = False
                try:
                    # Check if process is actually running
                    if process.process_id:
                        try:
                            os_process = psutil.Process(process.process_id)
                            is_running = os_process.is_running()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            is_running = False
                    
                    # Also check if port is actually in use
                    port_free = await self._is_port_free(process.port)
                    
                    if not is_running or port_free:
                        # Process is dead or port is free, mark as not running
                        process.is_running = False
                        if process.id in self.running_processes:
                            try:
                                self.running_processes[process.id].terminate()
                            except:
                                pass
                            del self.running_processes[process.id]
                except Exception as e:
                    logger.error(f"Error cleaning up process {process.id}: {e}")
                    # If any error occurs, mark process as not running
                    process.is_running = False
                    if process.id in self.running_processes:
                        try:
                            self.running_processes[process.id].terminate()
                        except:
                            pass
                        del self.running_processes[process.id]
            
            # Commit all changes
            try:
                await session.commit()
            except Exception as e:
                logger.error(f"Error committing cleanup changes: {e}")
                await session.rollback()
                # Force cleanup of all processes in this batch
                for process in running_processes:
                    process.is_running = False
                await session.commit()
        except Exception as e:
            logger.error(f"Error in cleanup_stale_processes: {e}")
            # Ensure session is rolled back
            await session.rollback()

    async def _is_port_free(self, port: int) -> bool:
        """Check if a port is actually free."""
        import socket
        try:
            # Try to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(('localhost', port))
            sock.close()
            return True
        except socket.error:
            return False

    def _wrap_code_in_fastapi(self, code: str) -> str:
        """Wrap the generated code in a FastAPI application."""
        return f'''# Generated FastAPI application
from fastapi import FastAPI, HTTPException, Body
from typing import Optional, Dict, Any
import json

# Initialize FastAPI app
app = FastAPI(
    title="Generated API",
    description="Auto-generated API endpoint",
    version="1.0.0"
)

# Original generated code
{code}

@app.post("/execute")
async def execute_endpoint(
    request_data: Dict[str, Any] = Body(...)
):
    """Execute the API with the provided input data."""
    try:
        # Extract file data if provided
        file_bytes = None
        if request_data.get("file_data"):
            import base64
            file_bytes = base64.b64decode(request_data["file_data"])
        
        # Get input data
        input_data = request_data.get("test_data")
        
        # Execute the API
        result = run(file_bytes=file_bytes, input_data=input_data)
        return result
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# For local testing
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
'''

    async def _prepare_api_code(self, user_id: str, api_slug: str, code: str) -> None:
        """Prepare the API code by wrapping it in FastAPI and saving it."""
        # Ensure generated_apis directory exists
        if not os.path.exists("generated_apis"):
            os.makedirs("generated_apis")
            
        # Create __init__.py if it doesn't exist
        init_file = os.path.join("generated_apis", "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Generated APIs package\n")
        
        # Wrap the code in FastAPI
        full_code = self._wrap_code_in_fastapi(code)
        
        # Save to file
        api_file = f"generated_apis/{user_id}_{api_slug}.py"
        with open(api_file, 'w', encoding='utf-8') as f:
            f.write(full_code)

    def _sanitize_module_name(self, name: str) -> str:
        """Convert a string into a valid Python module name."""
        # Replace invalid characters with underscores
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        # Ensure it doesn't start with a number
        if sanitized[0].isdigit():
            sanitized = 'api_' + sanitized
        return sanitized

    async def _get_available_port(self) -> int:
        """Find the next available port."""
        async with AsyncSessionLocal() as session:
            try:
                # First cleanup any stale processes
                await self._cleanup_stale_processes(session)
                await session.commit()
                
                # Force cleanup any processes using ports we want to allocate
                for port in range(self.base_port, self.max_port + 1):
                    if await self._is_port_free(port):
                        # Port is free, make sure it's marked as not in use in DB
                        await session.execute(
                            update(APIProcessDB)
                            .where(
                                and_(
                                    APIProcessDB.port == port,
                                    APIProcessDB.is_running == True
                                )
                            )
                            .values(is_running=False)
                        )
                        await session.commit()
                        
                        # Double check port is still free and not in database
                        check_result = await session.execute(
                            select(APIProcessDB)
                            .where(
                                APIProcessDB.port == port,
                                APIProcessDB.is_running == True
                            )
                        )
                        if check_result.first() is None:
                            return port
                
                raise RuntimeError("No available ports")
            except Exception as e:
                logger.error(f"Error getting available port: {e}")
                await session.rollback()
                raise

    async def start_api_process(self, user_id: str, api_slug: str) -> Tuple[str, int]:
        """Start a new API process and return its ID and port."""
        max_retries = 3
        last_error = None
        
        # Ensure generated_apis directory exists
        if not os.path.exists("generated_apis"):
            os.makedirs("generated_apis")
            
        # Create __init__.py if it doesn't exist
        init_file = os.path.join("generated_apis", "__init__.py")
        if not os.path.exists(init_file):
            with open(init_file, 'w') as f:
                f.write("# Generated APIs package\n")
        
        for attempt in range(max_retries):
            try:
                # Get an available port
                port = await self._get_available_port()
                process_id = str(uuid.uuid4())
                
                # First try to cleanup any existing processes for this API
                async with AsyncSessionLocal() as session:
                    await session.execute(
                        update(APIProcessDB)
                        .where(
                            and_(
                                APIProcessDB.user_id == user_id,
                                APIProcessDB.api_slug == api_slug,
                                APIProcessDB.is_running == True
                            )
                        )
                        .values(is_running=False)
                    )
                    await session.commit()
                
                # Prepare the API code
                api_file = f"generated_apis/{user_id}_{api_slug}.py"
                if not os.path.exists(api_file):
                    raise FileNotFoundError(f"API file not found: {api_file}")
                
                # Get absolute paths
                generated_apis_dir = os.path.abspath("generated_apis")
                api_file_path = os.path.abspath(api_file)
                
                # Create sanitized module name
                module_name = self._sanitize_module_name(f"{user_id}_{api_slug}")
                
                # Create a symlink with sanitized name if it doesn't exist
                sanitized_file = os.path.join(generated_apis_dir, f"{module_name}.py")
                try:
                    if os.path.exists(sanitized_file):
                        os.remove(sanitized_file)
                    os.symlink(api_file_path, sanitized_file)
                except OSError:
                    # If symlink fails (e.g., on Windows without admin), copy the file
                    import shutil
                    shutil.copy2(api_file_path, sanitized_file)
                
                # Create a temporary launcher file
                launcher_file = os.path.join(generated_apis_dir, f"launcher_{api_slug}.py")
                with open(launcher_file, 'w', encoding='utf-8') as f:
                    # Use raw string for Windows paths
                    reload_dir = generated_apis_dir.replace('\\', '/')
                    f.write(f'''import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "generated_apis.{module_name}:app",
        host="0.0.0.0",
        port={port},
        reload=True,
        reload_dirs=["{reload_dir}"],
        workers=1
    )
''')
                
                # Prepare environment with Python path
                env = os.environ.copy()
                if "PYTHONPATH" in env:
                    env["PYTHONPATH"] = f"{os.path.dirname(generated_apis_dir)}{os.pathsep}{env['PYTHONPATH']}"
                else:
                    env["PYTHONPATH"] = os.path.dirname(generated_apis_dir)
                
                # Start the process with output capture
                process = subprocess.Popen(
                    [
                        sys.executable,  # Use the same Python interpreter
                        launcher_file
                    ],
                    cwd=os.path.dirname(generated_apis_dir),  # Set CWD to parent of generated_apis
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,  # Get string output instead of bytes
                    env=env  # Use modified environment
                )
                
                # Wait a bit to ensure process starts
                await asyncio.sleep(2)  # Give it a bit more time to start
                
                # Check if process failed to start
                if process.poll() is not None:
                    # Process failed - capture output
                    stdout, stderr = process.communicate()
                    error_msg = f"Process failed to start (exit code: {process.poll()})\n"
                    if stdout:
                        error_msg += f"STDOUT:\n{stdout}\n"
                    if stderr:
                        error_msg += f"STDERR:\n{stderr}"
                    logger.error(error_msg)
                    
                    # Clean up temporary files
                    try:
                        os.remove(launcher_file)
                        os.remove(sanitized_file)
                    except:
                        pass
                        
                    raise Exception(error_msg)
                
                # Read the generated file to verify it has the app
                try:
                    with open(api_file, 'r') as f:
                        file_content = f.read()
                        if 'app = FastAPI(' not in file_content:
                            raise Exception("Generated API file does not contain FastAPI app")
                except Exception as e:
                    logger.error(f"Error verifying API file: {e}")
                    process.terminate()
                    
                    # Clean up temporary files
                    try:
                        os.remove(launcher_file)
                        os.remove(sanitized_file)
                    except:
                        pass
                        
                    raise
                
                self.running_processes[process_id] = process
                
                # Save process info to database
                async with AsyncSessionLocal() as session:
                    try:
                        # Double check port is still free
                        if not await self._is_port_free(port):
                            stdout, stderr = process.communicate()
                            logger.error(f"Port {port} is taken. Process output:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                            process.terminate()
                            
                            # Clean up temporary files
                            try:
                                os.remove(launcher_file)
                                os.remove(sanitized_file)
                            except:
                                pass
                                
                            continue
                        
                        # Check if port is already in use in database
                        check_result = await session.execute(
                            select(APIProcessDB)
                            .where(
                                APIProcessDB.port == port,
                                APIProcessDB.is_running == True
                            )
                        )
                        if check_result.first() is not None:
                            stdout, stderr = process.communicate()
                            logger.error(f"Port {port} is in database. Process output:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                            process.terminate()
                            
                            # Clean up temporary files
                            try:
                                os.remove(launcher_file)
                                os.remove(sanitized_file)
                            except:
                                pass
                                
                            continue
                            
                        db_process = APIProcessDB(
                            id=process_id,
                            user_id=user_id,
                            api_slug=api_slug,
                            port=port,
                            process_id=process.pid,
                            is_running=True
                        )
                        session.add(db_process)
                        await session.commit()
                    except Exception as db_error:
                        stdout, stderr = process.communicate()
                        logger.error(f"Database error while saving process: {db_error}\nProcess output:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                        process.terminate()
                        
                        # Clean up temporary files
                        try:
                            os.remove(launcher_file)
                            os.remove(sanitized_file)
                        except:
                            pass
                            
                        await session.rollback()
                        raise
                
                # Wait for the process to be ready
                try:
                    await self._wait_for_process_ready(port)
                    return process_id, port
                except TimeoutError:
                    stdout, stderr = process.communicate()
                    logger.error(f"Process startup timeout. Output:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                    process.terminate()
                    
                    # Clean up temporary files
                    try:
                        os.remove(launcher_file)
                        os.remove(sanitized_file)
                    except:
                        pass
                        
                    raise
                    
            except Exception as e:
                last_error = e
                logger.warning(f"Failed to start API process (attempt {attempt + 1}/{max_retries}): {e}")
                # Cleanup any partial process
                if 'process' in locals():
                    try:
                        stdout, stderr = process.communicate()
                        logger.error(f"Process cleanup output:\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
                        process.terminate()
                    except:
                        pass
                if 'process_id' in locals() and process_id in self.running_processes:
                    del self.running_processes[process_id]
                    
                # Clean up temporary files
                try:
                    if 'launcher_file' in locals():
                        os.remove(launcher_file)
                    if 'sanitized_file' in locals():
                        os.remove(sanitized_file)
                except:
                    pass
                    
                await asyncio.sleep(1)  # Wait before retry
        
        raise Exception(f"Failed to start API process after {max_retries} attempts: {last_error}")

    async def _wait_for_process_ready(self, port: int, timeout: int = 30, interval: float = 0.5):
        """Wait for the API process to be ready to accept connections."""
        
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(f"http://localhost:{port}/docs") as response:
                        if response.status == 200:
                            return True
            except aiohttp.ClientError:
                await asyncio.sleep(interval)
                continue
        
        raise TimeoutError(f"API process failed to start within {timeout} seconds")

    async def get_api_process(self, user_id: str, api_slug: str) -> Optional[Tuple[str, int]]:
        """Get running process info for an API, or start new if none exists."""
        async with AsyncSessionLocal() as session:
            try:
                # First cleanup any stale processes
                await self._cleanup_stale_processes(session)
                await session.commit()
                
                # Check for existing process
                result = await session.execute(
                    select(APIProcessDB)
                    .where(
                        APIProcessDB.user_id == user_id,
                        APIProcessDB.api_slug == api_slug,
                        APIProcessDB.is_running == True
                    )
                )
                process = result.scalar_one_or_none()
                
                if process:
                    # Verify process is actually running
                    try:
                        os_process = psutil.Process(process.process_id)
                        if os_process.is_running() and not await self._is_port_free(process.port):
                            # Process is running and port is in use
                            process.last_accessed = datetime.utcnow()
                            await session.commit()
                            return process.id, process.port
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                    
                    # Process not running or port free, mark as stopped
                    process.is_running = False
                    if process.id in self.running_processes:
                        try:
                            self.running_processes[process.id].terminate()
                        except:
                            pass
                        del self.running_processes[process.id]
                    await session.commit()
                
                # Start new process
                return await self.start_api_process(user_id, api_slug)
            except Exception as e:
                logger.error(f"Error in get_api_process: {e}")
                await session.rollback()
                raise

    async def stop_api_process(self, process_id: str):
        """Stop an API process."""
        async with AsyncSessionLocal() as session:
            process = await session.execute(
                select(APIProcessDB).where(APIProcessDB.id == process_id)
            )
            process = process.scalar_one_or_none()
            
            if process and process.is_running:
                # Stop the process
                if process.process_id in self.running_processes:
                    self.running_processes[process.process_id].terminate()
                    del self.running_processes[process.process_id]
                
                # Update database
                process.is_running = False
                await session.commit()

    async def cleanup_idle_processes(self):
        """Stop processes that haven't been accessed recently."""
        idle_threshold = datetime.utcnow() - timedelta(seconds=self.process_idle_timeout)
        
        async with AsyncSessionLocal() as session:
            # Find idle processes
            result = await session.execute(
                select(APIProcessDB)
                .where(
                    APIProcessDB.is_running == True,
                    APIProcessDB.last_accessed < idle_threshold
                )
            )
            idle_processes = result.scalars().all()
            
            # Stop each idle process
            for process in idle_processes:
                await self.stop_api_process(process.id)

    async def start_cleanup_task(self):
        """Start background task to cleanup idle processes."""
        while True:
            try:
                await self.cleanup_idle_processes()
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")
            await asyncio.sleep(self.process_cleanup_interval)

    async def update_process_metrics(self, process_id: str):
        """Update CPU and memory usage metrics for a process."""
        async with AsyncSessionLocal() as session:
            process = await session.execute(
                select(APIProcessDB).where(APIProcessDB.id == process_id)
            )
            process = process.scalar_one_or_none()
            
            if process and process.is_running:
                try:
                    os_process = psutil.Process(process.process_id)
                    process.cpu_usage = os_process.cpu_percent()
                    process.memory_usage = os_process.memory_info().rss // (1024 * 1024)  # Convert to MB
                    await session.commit()
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.warning(f"Failed to update metrics for process {process_id}: {e}")

# Global instance
api_process_service = APIProcessService() 