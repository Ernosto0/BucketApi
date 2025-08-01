import os
import re
import importlib.util
import sys
from typing import Optional, Any, Dict, List
from datetime import datetime
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from ..config import settings
from ..models import SavedAPI, SaveAPIRequest, User, UserCreate
from ..services.auth_service import auth_service
from .database import SavedAPIDB, AsyncSessionLocal
import logging
from .sandbox_service import sandbox_service
from ..services.api_execution_usage_service import api_execution_usage_service

logger = logging.getLogger(__name__)

class FileService:
    def __init__(self):
        self.generated_apis_dir = settings.GENERATED_APIS_DIR
        self._ensure_directory_exists()
    
    def _ensure_directory_exists(self):
        """Ensure the generated APIs directory exists."""
        os.makedirs(self.generated_apis_dir, exist_ok=True)
    
    # User Management Methods (delegated to auth_service)
    async def save_user(self, user_data: UserCreate, hashed_password: str) -> User:
        """Save a new user (delegated to auth_service)."""
        return await auth_service.save_user(user_data, hashed_password)

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email (delegated to auth_service)."""
        return await auth_service.get_user_by_email(email)

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user (delegated to auth_service)."""
        return await auth_service.authenticate_user(email, password)

    # API Management Methods
    def generate_api_slug(self, user_id: str, api_name: Optional[str] = None) -> str:
        """Generate a unique slug for the API."""
        if api_name:
            # Clean the API name
            slug_base = re.sub(r'[^a-zA-Z0-9_-]', '_', api_name.lower())
        else:
            # Generate timestamp-based slug
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug_base = f"api_{timestamp}"
        
        # Combine with user_id
        api_slug = f"{user_id}_{slug_base}"
        
        # Ensure uniqueness
        counter = 1
        original_slug = api_slug
        while self._api_file_exists(api_slug):
            api_slug = f"{original_slug}_{counter}"
            counter += 1
        
        return api_slug
    
    async def save_api_code(self, api_slug: str, code: str) -> str:
        """Save generated API code to file."""
        logger.info(f"Saving API code to {api_slug}")
        try:
            # Extract user_id from api_slug
            user_id = api_slug.split('_')[0]
            api_name = '_'.join(api_slug.split('_')[1:])
            
            # Get the file path
            file_path = self._get_api_file_path(api_slug)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Validate code syntax before saving
            try:
                import ast
                ast.parse(code)
            except SyntaxError as e:
                logger.error(f"Syntax error in generated code: {e}")
                raise Exception(f"Generated code has syntax errors: {str(e)}")
            
            # Save the code directly (FastAPI wrapper is now handled by sandbox)
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(code)
            
            # Verify the file was created and content is complete
            if not os.path.exists(file_path):
                raise Exception(f"Failed to create API file at {file_path}")
            
            # Verify saved content
            with open(file_path, 'r', encoding='utf-8') as f:
                saved_content = f.read()
                if len(saved_content) != len(code):
                    raise Exception(f"File content length mismatch: expected {len(code)}, got {len(saved_content)}")
            
            logger.info(f"API code saved to {file_path}")
            return file_path
        except Exception as e:
            logger.error(f"Error saving API code: {e}")
            raise Exception(f"Failed to save API code: {str(e)}")
    
    def load_api_code(self, user_id: str, api_slug: str) -> str:
        """Load existing API code from file."""
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"API not found: {full_slug}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
                # Verify the file contains a FastAPI app
                if 'app = FastAPI(' not in content:
                    # Try to fix the file by wrapping it in FastAPI app
                    try:
                        # Extract the original code (everything after the docstring)
                        if content.startswith('"""'):
                            end_quote = content.find('"""', 3)
                            if end_quote != -1:
                                original_code = content[end_quote + 3:].lstrip('\n')
                            else:
                                original_code = content
                        else:
                            original_code = content
                            
                        # Wrap and save the code
                        wrapped_code = sandbox_service._wrap_code_in_fastapi(original_code)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(wrapped_code)
                            
                        return wrapped_code
                    except Exception as wrap_error:
                        logger.error(f"Failed to wrap code in FastAPI app: {wrap_error}")
                        raise Exception("API file does not contain FastAPI app and could not be fixed")
                
                return content
        except Exception as e:
            raise Exception(f"Failed to load API code: {str(e)}")
    
    async def save_api_metadata(self, request: SaveAPIRequest) -> SavedAPI:
        """Save API metadata to database."""
        async with AsyncSessionLocal() as session:
            # Get creation time from the Python file
            full_slug = f"{request.user_id}_{request.api_slug}"
            python_file_path = self._get_api_file_path(full_slug)
            created_at = self._get_file_creation_time_from_path(python_file_path)
            
            # Check if API metadata already exists
            existing_api = await session.execute(
                select(SavedAPIDB).where(
                    and_(
                        SavedAPIDB.user_id == request.user_id,
                        SavedAPIDB.api_slug == request.api_slug
                    )
                )
            )
            
            if existing_api.scalar_one_or_none():
                raise Exception("API metadata already exists")
            
            # Create database entry
            db_api = SavedAPIDB(
                api_slug=request.api_slug,
                user_id=request.user_id,
                api_name=request.api_name,
                prompt=request.prompt,
                endpoint_url=request.endpoint_url,
                documentation=request.documentation,
                curl_example=request.curl_example,
                sample_input=request.sample_input,
                expected_output=request.expected_output,
                created_at=created_at,
                saved_at=datetime.utcnow(),
                is_saved=True
            )
            
            session.add(db_api)
            await session.commit()
            await session.refresh(db_api)
            
            # Return SavedAPI model
            return SavedAPI(
                api_slug=db_api.api_slug,
                user_id=db_api.user_id,
                api_name=db_api.api_name,
                prompt=db_api.prompt,
                endpoint_url=db_api.endpoint_url,
                documentation=db_api.documentation,
                curl_example=db_api.curl_example,
                sample_input=db_api.sample_input,
                expected_output=db_api.expected_output,
                created_at=db_api.created_at,
                saved_at=db_api.saved_at,
                is_saved=db_api.is_saved
            )
    
    async def get_api_metadata(self, user_id: str, api_slug: str) -> Optional[SavedAPI]:
        """Get API metadata from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SavedAPIDB).where(
                    and_(
                        SavedAPIDB.user_id == user_id,
                        SavedAPIDB.api_slug == api_slug
                    )
                )
            )
            
            db_api = result.scalar_one_or_none()
            if not db_api:
                return None
            
            return SavedAPI(
                api_slug=db_api.api_slug,
                user_id=db_api.user_id,
                api_name=db_api.api_name,
                prompt=db_api.prompt,
                endpoint_url=db_api.endpoint_url,
                documentation=db_api.documentation,
                curl_example=db_api.curl_example,
                sample_input=db_api.sample_input,
                expected_output=db_api.expected_output,
                created_at=db_api.created_at,
                saved_at=db_api.saved_at,
                is_saved=db_api.is_saved
            )
    
    async def get_api_details(self, user_id: str, api_slug: str) -> Dict[str, Any]:
        """Get comprehensive API details including metadata, code, and execution statistics."""
        # Get API metadata from database
        api_metadata = await self.get_api_metadata(user_id, api_slug)
        
        if not api_metadata:
            # Check if API file exists but not saved to database
            if self.api_exists(user_id, api_slug):
                # Return basic details for unsaved API
                full_slug = f"{user_id}_{api_slug}"
                file_path = self._get_api_file_path(full_slug)
                created_at = self._get_file_creation_time_from_path(file_path)
                
                return {
                    "api_slug": api_slug,
                    "user_id": user_id,
                    "api_name": f"API {api_slug}",
                    "prompt": "API details not available",
                    "endpoint_url": f"{settings.API_PREFIX}/{user_id}/{api_slug}",
                    "documentation": "Documentation not available",
                    "curl_example": f"curl -X POST '{settings.API_PREFIX}/{user_id}/{api_slug}' -H 'Content-Type: application/json' -d '{{}}'",
                    "sample_input": None,
                    "expected_output": None,
                    "created_at": created_at,
                    "saved_at": None,
                    "is_saved": False,
                    "code_available": True,
                    "file_size": os.path.getsize(file_path) if os.path.exists(file_path) else 0,
                    "last_modified": datetime.fromtimestamp(os.path.getmtime(file_path)) if os.path.exists(file_path) else None
                }
            else:
                raise FileNotFoundError(f"API not found: {user_id}/{api_slug}")
        
        # Get additional file information
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        file_info = {}
        if os.path.exists(file_path):
            file_info = {
                "code_available": True,
                "file_size": os.path.getsize(file_path),
                "last_modified": datetime.fromtimestamp(os.path.getmtime(file_path))
            }
        else:
            file_info = {
                "code_available": False,
                "file_size": 0,
                "last_modified": None
            }
        
        # Convert SavedAPI to dict and add file info
        api_details = {
            "api_slug": api_metadata.api_slug,
            "user_id": api_metadata.user_id,
            "api_name": api_metadata.api_name,
            "prompt": api_metadata.prompt,
            "endpoint_url": api_metadata.endpoint_url,
            "documentation": api_metadata.documentation,
            "curl_example": api_metadata.curl_example,
            "sample_input": api_metadata.sample_input,
            "expected_output": api_metadata.expected_output,
            "created_at": api_metadata.created_at,
            "saved_at": api_metadata.saved_at,
            "is_saved": api_metadata.is_saved,
            **file_info
        }
        
        return api_details
    
    async def is_api_saved(self, user_id: str, api_slug: str) -> bool:
        """Check if an API has been saved with metadata in database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SavedAPIDB.id).where(
                    and_(
                        SavedAPIDB.user_id == user_id,
                        SavedAPIDB.api_slug == api_slug
                    )
                )
            )
            return result.scalar_one_or_none() is not None
    
    async def load_and_execute_api(self, user_id: str, api_slug: str, 
                           file_bytes: Optional[bytes] = None, 
                           input_data: Optional[Dict[str, Any]] = None) -> Any:
        """Load and execute the generated API from Python file."""
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"API not found: {full_slug}")
        
        try:
            # Read the code
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            # Execute in sandbox with default timeout and memory limits
            result, execution_time, success, error = await api_execution_usage_service.execute_api_with_limits(
                code=code,
                input_data=input_data or {},
                file_bytes=file_bytes
            )
            
            if not success:
                raise Exception(error or "API execution failed")
            
            return result
            
        except Exception as e:
            raise Exception(f"Failed to execute API {full_slug}: {str(e)}")
    
    def api_exists(self, user_id: str, api_slug: str) -> bool:
        """Check if an API Python file exists."""
        full_slug = f"{user_id}_{api_slug}"
        return self._api_file_exists(full_slug)
    
    async def get_user_apis(self, user_id: str) -> List[SavedAPI]:
        """Get list of saved APIs with full metadata for a specific user from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(SavedAPIDB).where(SavedAPIDB.user_id == user_id).order_by(SavedAPIDB.saved_at.desc())
            )
            
            db_apis = result.scalars().all()
            
            saved_apis = []
            for db_api in db_apis:
                saved_apis.append(SavedAPI(
                    api_slug=db_api.api_slug,
                    user_id=db_api.user_id,
                    api_name=db_api.api_name,
                    prompt=db_api.prompt,
                    endpoint_url=db_api.endpoint_url,
                    documentation=db_api.documentation,
                    curl_example=db_api.curl_example,
                    sample_input=db_api.sample_input,
                    expected_output=db_api.expected_output,
                    created_at=db_api.created_at,
                    saved_at=db_api.saved_at,
                    is_saved=db_api.is_saved
                ))
            
            return saved_apis
    
    def get_user_apis_basic(self, user_id: str) -> list:
        """Get basic list of APIs for a specific user (legacy method - file-based)."""
        apis = []
        if not os.path.exists(self.generated_apis_dir):
            return apis
        
        prefix = f"{user_id}_"
        for filename in os.listdir(self.generated_apis_dir):
            if filename.startswith(prefix) and filename.endswith('.py'):
                api_slug = filename[len(prefix):-3]  # Remove user_id prefix and .py extension
                apis.append({
                    'api_slug': api_slug,
                    'filename': filename,
                    'created_at': self._get_file_creation_time(filename),
                    'is_saved': False  # We'd need to check database, but this is legacy
                })
        
        return sorted(apis, key=lambda x: x['created_at'], reverse=True)
    
    async def delete_api(self, user_id: str, api_slug: str) -> bool:
        """Delete an API file and its metadata from both filesystem and database."""
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        success = True
        
        # Delete Python file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                success = False
        
        # Delete metadata from database
        try:
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(SavedAPIDB).where(
                        and_(
                            SavedAPIDB.user_id == user_id,
                            SavedAPIDB.api_slug == api_slug
                        )
                    )
                )
                
                db_api = result.scalar_one_or_none()
                if db_api:
                    await session.delete(db_api)
                    await session.commit()
        except Exception:
            success = False
        
        return success
    
    def _api_file_exists(self, api_slug: str) -> bool:
        """Check if API file exists."""
        file_path = self._get_api_file_path(api_slug)
        return os.path.exists(file_path)
    
    def _get_api_file_path(self, api_slug: str) -> str:
        """Get the full file path for an API."""
        return os.path.join(self.generated_apis_dir, f"{api_slug}.py")
    
    def _get_file_creation_time(self, filename: str) -> datetime:
        """Get file creation time."""
        file_path = os.path.join(self.generated_apis_dir, filename)
        return self._get_file_creation_time_from_path(file_path)
    
    def _get_file_creation_time_from_path(self, file_path: str) -> datetime:
        """Get file creation time from full path."""
        try:
            timestamp = os.path.getctime(file_path)
            return datetime.fromtimestamp(timestamp)
        except Exception:
            return datetime.now()

    def cleanup_orphaned_json_files(self) -> int:
        """Clean up orphaned JSON files from the old metadata storage system."""
        if not os.path.exists(self.generated_apis_dir):
            return 0
        
        cleaned_count = 0
        for filename in os.listdir(self.generated_apis_dir):
            if filename.endswith('.json'):
                json_path = os.path.join(self.generated_apis_dir, filename)
                try:
                    os.remove(json_path)
                    cleaned_count += 1
                    print(f"Removed orphaned JSON file: {filename}")
                except Exception as e:
                    print(f"Failed to remove {filename}: {str(e)}")
        
        return cleaned_count

# Global instance
file_service = FileService() 