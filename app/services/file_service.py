import os
import re
import importlib.util
import sys
from pathlib import Path
from typing import Optional, Any, Dict, List
from datetime import datetime
from ..config import settings
from ..models import SavedAPI, SaveAPIRequest, User, APIVersion, DatabaseConfig
from ..services.auth_service import auth_service
from .mongodb import mongodb
import logging
from .sandbox_service import sandbox_service
from ..services.api_execution_usage_service import api_execution_usage_service

logger = logging.getLogger(__name__)

class FileService:
    def __init__(self):
        self.generated_apis_dir = settings.GENERATED_APIS_DIR
        self._ensure_directory_exists()
        # Store the absolute path for security validation
        self.safe_base_path = Path(self.generated_apis_dir).resolve()
    
    def _ensure_directory_exists(self):
        """Ensure the generated APIs directory exists."""
        os.makedirs(self.generated_apis_dir, exist_ok=True)
    
    def _validate_api_slug(self, api_slug: str) -> str:
        """
        Validate and sanitize API slug to prevent path traversal attacks.
        
        Args:
            api_slug: The API slug to validate
            
        Returns:
            Sanitized API slug
            
        Raises:
            ValueError: If the slug contains dangerous characters
        """
        if not api_slug or not isinstance(api_slug, str):
            raise ValueError("API slug must be a non-empty string")
        
        # Remove any null bytes (can be used to bypass filters)
        api_slug = api_slug.replace('\x00', '')
        
        # Check for path traversal patterns
        dangerous_patterns = ['..', '/', '\\', '~', '$', '|', ';', '&', '`', '<', '>', '"', "'"]
        for pattern in dangerous_patterns:
            if pattern in api_slug:
                raise ValueError(f"API slug contains dangerous character sequence: '{pattern}'")
        
        # Only allow alphanumeric, underscore, and hyphen
        if not re.match(r'^[a-zA-Z0-9_-]+$', api_slug):
            raise ValueError("API slug can only contain letters, numbers, underscores, and hyphens")
        
        # Limit length to prevent buffer overflow issues
        if len(api_slug) > 100:
            raise ValueError("API slug too long (max 100 characters)")
        
        return api_slug
    
    def _get_safe_file_path(self, api_slug: str) -> str:
        """
        Get a safe file path that's guaranteed to be within the allowed directory.
        
        Args:
            api_slug: The API slug (will be validated)
            
        Returns:
            Safe absolute file path
            
        Raises:
            ValueError: If path validation fails
        """
        # Validate the slug first
        safe_slug = self._validate_api_slug(api_slug)
        
        # Construct the path
        file_path = self.safe_base_path / f"{safe_slug}.py"
        
        # Resolve to absolute path and check it's within our base directory
        resolved_path = file_path.resolve()
        
        # Security check: ensure the resolved path is within our safe directory
        try:
            resolved_path.relative_to(self.safe_base_path)
        except ValueError:
            raise ValueError(f"File path '{resolved_path}' is outside the allowed directory")
        
        return str(resolved_path)
    
    # User Management Methods (delegated to auth_service)

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email (delegated to auth_service)."""
        return auth_service.get_user_by_email(email)

    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user (delegated to auth_service)."""
        return auth_service.authenticate_user(email, password)

    # API Management Methods
    def generate_api_slug(self, user_id: str, api_name: Optional[str] = None) -> str:
        """Generate a unique and secure slug for the API."""
        # Validate user_id for security
        if not user_id or not re.match(r'^[a-zA-Z0-9_-]+$', user_id):
            raise ValueError("Invalid user_id: must contain only letters, numbers, underscores, and hyphens")
        
        if api_name:
            # Clean the API name thoroughly
            slug_base = re.sub(r'[^a-zA-Z0-9_-]', '_', api_name.lower())
            # Remove consecutive underscores and trim
            slug_base = re.sub(r'_+', '_', slug_base).strip('_')
            # Ensure it's not empty after cleaning
            if not slug_base:
                slug_base = "api"
        else:
            # Generate timestamp-based slug
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            slug_base = f"api_{timestamp}"
        
        # Combine with user_id
        api_slug = f"{user_id}_{slug_base}"
        
        # Ensure the generated slug passes our security validation
        try:
            self._validate_api_slug(api_slug)
        except ValueError:
            # If validation fails, use a safe fallback
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            api_slug = f"{user_id}_api_{timestamp}"
        
        # Ensure uniqueness
        counter = 1
        original_slug = api_slug
        while self._api_file_exists(api_slug):
            api_slug = f"{original_slug}_{counter}"
            counter += 1
            # Validate the new slug with counter
            try:
                self._validate_api_slug(api_slug)
            except ValueError:
                # If even with counter it's invalid, something is very wrong
                raise ValueError(f"Unable to generate safe API slug for user {user_id}")
        
        return api_slug
    
    async def save_api_code(self, api_slug: str, code: str) -> str:
        """Save generated API code to file with security validation."""
        logger.info(f"Saving API code to {api_slug}")
        try:
            # Validate API slug for security (will raise ValueError if invalid)
            safe_slug = self._validate_api_slug(api_slug)
            
            # Extract user_id from api_slug
            user_id = safe_slug.split('_')[0]
            api_name = '_'.join(safe_slug.split('_')[1:])
            
            # Get the secure file path
            file_path = self._get_safe_file_path(safe_slug)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Validate code syntax before saving
            try:
                import ast
                ast.parse(code)
            except SyntaxError as e:
                logger.error(f"Syntax error in generated code: {e}")
                # Provide more detailed error information
                error_details = self._analyze_syntax_error(code, e)
                raise Exception(f"Generated code has syntax errors: {error_details}")
            
            # Additional security: validate code size to prevent DOS
            if len(code) > 1024 * 1024:  # 1MB limit
                raise Exception("Generated code too large (max 1MB)")
            
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
        except ValueError as e:
            # Security validation error
            logger.error(f"Security validation failed for API slug '{api_slug}': {e}")
            raise Exception("Invalid API identifier. Please use only letters, numbers, underscores, and hyphens.")
        except Exception as e:
            logger.error(f"Error saving API code: {e}")
            raise Exception("Failed to save API code. Please try again.")
    
    def load_api_code(self, user_id: str, api_slug: str) -> str:
        """Load existing API code from file."""
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        if not os.path.exists(file_path):
            # Try to recover from database
            logger.info(f"File not found for {full_slug}, attempting DB recovery")
            try:
                metadata = self.get_api_metadata(user_id, api_slug)
                if metadata and metadata.code:
                    # Return code directly from metadata - no need to enforce file write
                    # This is crucial for ephemeral environments like Railway/Docker
                    try:
                        # Attempt to cache to disk if possible, but don't fail if we can't
                        os.makedirs(os.path.dirname(file_path), exist_ok=True)
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(metadata.code)
                        logger.info(f"Restored {full_slug} from database to file")
                    except Exception as e:
                        logger.warning(f"Could not cache restored code to disk (using memory only): {e}")
                    
                    return metadata.code
                else:
                    raise FileNotFoundError(f"API not found: {full_slug}")
            except Exception as e:
                if isinstance(e, FileNotFoundError):
                    raise
                logger.error(f"DB recovery failed: {e}")
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
            logger.error(f"Failed to load API code for {user_id}/{api_slug}: {e}")
            raise Exception("Failed to load API code. The API may not exist or be corrupted.")
    
    def save_api_metadata(self, request: SaveAPIRequest) -> SavedAPI:
        """Save API metadata to database."""
        # Get creation time from the Python file
        full_slug = f"{request.user_id}_{request.api_slug}"
        python_file_path = self._get_api_file_path(full_slug)
        created_at = self._get_file_creation_time_from_path(python_file_path)
        
        # Check if API metadata already exists
        existing_api = mongodb.saved_apis.find_one({
            "user_id": request.user_id,
            "api_slug": request.api_slug
        })
        
        if existing_api:
            raise Exception("API metadata already exists")
        
        # Create database entry
        current_code = None
        try:
            current_code = self.load_api_code(request.user_id, request.api_slug)
        except Exception as e:
            logger.warning(f"Could not load code for saving to DB: {e}")

        db_api = {
            "api_slug": request.api_slug,
            "user_id": request.user_id,
            "api_name": request.api_name,
            "prompt": request.prompt,
            "endpoint_url": request.endpoint_url,
            "documentation": request.documentation,
            "curl_example": request.curl_example,
            "openapi_spec": request.openapi_spec,
            "sample_input": request.sample_input,
            "expected_output": request.expected_output,
            "database_config": request.database_config.model_dump() if request.database_config else None,
            "code": current_code,  # Save code to DB for persistence
            "created_at": created_at,
            "saved_at": datetime.utcnow(),
            "is_saved": True,
        }
        
        mongodb.saved_apis.insert_one(db_api)
        
        # Create initial version (v1) from the current code
        try:
            if current_code:
                self.save_version(
                    user_id=request.user_id,
                    api_slug=request.api_slug,
                    code=current_code,
                    prompt=request.prompt,
                    endpoint_url=request.endpoint_url,
                    commit_message="Initial version",
                    version_override=1
                )
                logger.info(f"Created initial version for API {request.api_slug}")
        except Exception as e:
            logger.warning(f"Failed to create initial version for {request.api_slug}: {e}")
            # Don't fail the whole save operation if versioning fails
        
        # Return SavedAPI model
        return SavedAPI(
            api_slug=db_api["api_slug"],
            user_id=db_api["user_id"],
            api_name=db_api["api_name"],
            prompt=db_api["prompt"],
            endpoint_url=db_api["endpoint_url"],
            documentation=db_api["documentation"],
            curl_example=db_api["curl_example"],
            openapi_spec=db_api["openapi_spec"],
            sample_input=db_api["sample_input"],
            expected_output=db_api["expected_output"],
            database_config=DatabaseConfig(**db_api["database_config"]) if db_api.get("database_config") else None,
            code=db_api.get("code"),
            created_at=db_api["created_at"],
            saved_at=db_api["saved_at"],
            is_saved=db_api["is_saved"],
            current_version=1,
            versions=[]
        )
    
    def get_api_metadata(self, user_id: str, api_slug: str) -> Optional[SavedAPI]:
        """Get API metadata from database."""
        db_api = mongodb.saved_apis.find_one({
            "user_id": user_id,
            "api_slug": api_slug
        })
        
        if not db_api:
            return None
        
        # Handle versions field - convert dicts to APIVersion objects
        versions = []
        if "versions" in db_api and db_api["versions"]:
            for v_dict in db_api["versions"]:
                try:
                    versions.append(APIVersion(**v_dict))
                except Exception as e:
                    logger.warning(f"Failed to parse version: {e}")
                    continue
        
        # Handle database_config field
        database_config = None
        if db_api.get("database_config"):
            try:
                database_config = DatabaseConfig(**db_api["database_config"])
            except Exception as e:
                logger.warning(f"Failed to parse database_config: {e}")
        
        return SavedAPI(
            api_slug=db_api["api_slug"],
            user_id=db_api["user_id"],
            api_name=db_api["api_name"],
            prompt=db_api["prompt"],
            endpoint_url=db_api["endpoint_url"],
            documentation=db_api["documentation"],
            curl_example=db_api["curl_example"],
            openapi_spec=db_api.get("openapi_spec"),
            sample_input=db_api.get("sample_input"),
            expected_output=db_api.get("expected_output"),
            database_config=database_config,
            code=db_api.get("code"),
            created_at=db_api["created_at"],
            saved_at=db_api["saved_at"],
            is_saved=db_api.get("is_saved", True),
            current_version=db_api.get("current_version", 1),
            versions=versions
        )
    
    def get_api_details(self, user_id: str, api_slug: str) -> Dict[str, Any]:
        """Get comprehensive API details including metadata, code, and execution statistics."""
        # Get API metadata from database
        api_metadata = self.get_api_metadata(user_id, api_slug)
        
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
                    "openapi_spec": None,
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
            # Check if code is available in metadata (DB)
            code_in_db = api_metadata.code if api_metadata else None
            if code_in_db:
                 file_info = {
                    "code_available": True,
                    "file_size": len(code_in_db.encode('utf-8')),
                    "last_modified": api_metadata.saved_at
                }
            else:
                file_info = {
                    "code_available": False,
                    "file_size": 0,
                    "last_modified": None
                }
        
        # Convert SavedAPI to dict and add file info
        # Use model_dump() to properly serialize Pydantic model including nested objects
        try:
            api_details = api_metadata.model_dump()
        except AttributeError:
            # Fallback for older Pydantic versions
            api_details = api_metadata.dict()
        
        # Add file info
        api_details.update(file_info)
        
        return api_details
    
    def create_initial_version_if_needed(self, user_id: str, api_slug: str) -> None:
        """
        Check if API has versions tracked. If not, create version 1 from current code.
        """
        metadata = self.get_api_metadata(user_id, api_slug)
        if not metadata:
            return
            
        if not metadata.versions:
            try:
                # Load current code
                current_code = self.load_api_code(user_id, api_slug)
                
                # Create v1
                self.save_version(
                    user_id=user_id,
                    api_slug=api_slug,
                    code=current_code,
                    prompt=metadata.prompt,
                    endpoint_url=metadata.endpoint_url,
                    commit_message="Initial version",
                    version_override=1
                )
            except Exception as e:
                logger.error(f"Failed to create initial version for {api_slug}: {e}")

    def save_version(self, user_id: str, api_slug: str, code: str, prompt: str, endpoint_url: str, commit_message: Optional[str] = None, version_override: Optional[int] = None) -> int:
        """Save a new version of the API."""
        # Get current metadata
        metadata = self.get_api_metadata(user_id, api_slug)
        if not metadata:
            raise Exception("API metadata not found")
            
        # Determine version number
        if version_override:
            next_version = version_override
        else:
            # If no versions exist, start at 2 (assuming v1 was just created or current state is v1)
            # But if create_initial_version_if_needed was called, we should have v1.
            current_max = metadata.current_version or 0
            if not metadata.versions and current_max == 1:
                # Metadata says v1 but no versions list? inconsistent.
                # Just find max from versions list if available
                if metadata.versions:
                    current_max = max(v.version for v in metadata.versions)
                else:
                    current_max = 0
            
            # If we are saving a NEW version, increment
            next_version = current_max + 1
        
        # Create version file slug: user_id_api_slug_v{num}
        # Note: save_api_code logic splits by first underscore for user_id.
        # So we need: user_id + "_" + api_slug + "_v" + num
        # But api_slug might contain underscores. 
        # _get_safe_file_path calls _validate_api_slug.
        # We will manually construct the path to avoid "user_id" parsing issues in save_api_code if we used that.
        
        safe_slug = self._validate_api_slug(api_slug)
        version_filename = f"{user_id}_{safe_slug}_v{next_version}.py"
        file_path = self.safe_base_path / version_filename
        
        # Save file
        try:
            with open(file_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(code)
        except Exception as e:
            logger.error(f"Failed to save version file {version_filename}: {e}")
            raise
            
        # Relative path for DB
        try:
            rel_path = file_path.relative_to(self.safe_base_path)
        except ValueError:
             rel_path = version_filename # Fallback
        
        # Create version object data
        version_data = {
            "version": next_version,
            "created_at": datetime.utcnow(),
            "prompt": prompt,
            "endpoint_url": endpoint_url,
            "commit_message": commit_message or f"Version {next_version}",
            "code_path": str(rel_path)
        }
        
        # Update MongoDB
        # We need to convert to dict manually if using pymongo direct update, 
        # but SavedAPI model suggests we might want to use it.
        # Since we are using update_one, we pass raw dict.
        
        update_op = {
            "$push": {"versions": version_data},
            "$set": {"current_version": next_version}
        }
        
        # If this is v1 and we want to ensure versions list is initialized
        if not metadata.versions and next_version == 1:
             # Just push is fine, it will create the array if missing (standard mongo behavior)
             pass
             
        mongodb.saved_apis.update_one(
            {"user_id": user_id, "api_slug": api_slug},
            update_op
        )
        
        return next_version

    def restore_version(self, user_id: str, api_slug: str, version_num: int) -> str:
        """Restore a specific version of the API."""
        metadata = self.get_api_metadata(user_id, api_slug)
        if not metadata:
            raise Exception("API metadata not found")
            
        # Find the version
        target_version = None
        for v in metadata.versions:
            if v.version == version_num:
                target_version = v
                break
        
        if not target_version:
            raise Exception(f"Version {version_num} not found")
            
        # Load version code
        if target_version.code_path:
            version_path = self.safe_base_path / target_version.code_path
        else:
            # Fallback
            safe_slug = self._validate_api_slug(api_slug)
            version_filename = f"{user_id}_{safe_slug}_v{version_num}.py"
            version_path = self.safe_base_path / version_filename
            
        if not version_path.exists():
             raise FileNotFoundError(f"Version file not found: {version_path}")
             
        with open(version_path, 'r', encoding='utf-8') as f:
            code = f.read()
            
        # Overwrite main API file
        main_slug = f"{user_id}_{api_slug}"
        self.save_api_code(main_slug, code)
        
        return code

    def is_api_saved(self, user_id: str, api_slug: str) -> bool:
        """Check if an API has been saved with metadata in database."""
        return mongodb.saved_apis.find_one({
            "user_id": user_id,
            "api_slug": api_slug
        }) is not None
    
    async def load_and_execute_api(self, user_id: str, api_slug: str, 
                           file_bytes: Optional[bytes] = None, 
                           input_data: Optional[Dict[str, Any]] = None,
                           is_test_execution: bool = False) -> Any:
        """Load and execute the generated API from Python file."""
        full_slug = f"{user_id}_{api_slug}"
        
        try:
            # Load code using the robust loader (handles DB fallback for ephemeral envs)
            code = self.load_api_code(user_id, api_slug)
            
            # Get database configuration if available
            database_url = None
            try:
                api_metadata = self.get_api_metadata(user_id, api_slug)
                if api_metadata:
                    db_api = mongodb.saved_apis.find_one({
                        "user_id": user_id,
                        "api_slug": api_slug
                    })
                    if db_api and db_api.get("database_config"):
                        from ..models import DatabaseConfig, DatabaseType
                        from ..services.database_connection_service import database_connection_service
                        
                        db_config_dict = db_api["database_config"]
                        db_config = DatabaseConfig(**db_config_dict)
                        
                        # Decode credentials if needed
                        db_config = database_connection_service.decode_credentials(db_config)
                        
                        # Build connection string
                        database_url = database_connection_service.build_connection_string(db_config)
                        logger.info(f"Database connection configured for API {api_slug}")
            except Exception as e:
                logger.warning(f"Failed to load database configuration for {api_slug}: {e}")
                # Continue without database config
            
            # Execute in sandbox with default timeout and memory limits
            result, execution_time, success, error = await api_execution_usage_service.execute_api_with_limits(
                code=code,
                input_data=input_data or {},
                file_bytes=file_bytes,
                is_test_execution=is_test_execution,
                database_url=database_url
            )
            
            if not success:
                raise Exception(error or "API execution failed")
            
            return result
            
        except Exception as e:
            raise Exception(f"Failed to execute API {full_slug}: {str(e)}")
    
    def api_exists(self, user_id: str, api_slug: str) -> bool:
        """Check if an API Python file exists (or can be restored from DB)."""
        full_slug = f"{user_id}_{api_slug}"
        if self._api_file_exists(full_slug):
            return True
            
        # Check database as fallback
        return self.is_api_saved(user_id, api_slug)
    
    def load_api_code(self, user_id: str, api_slug: str) -> str:
        """Load the Python code for a specific API."""
        full_slug = f"{user_id}_{api_slug}"
        file_path = self._get_api_file_path(full_slug)
        
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"API code not found: {full_slug}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise Exception(f"Failed to load API code {full_slug}: {str(e)}")
    
    def get_user_apis(self, user_id: str) -> List[SavedAPI]:
        """Get list of saved APIs with full metadata for a specific user from database."""
        db_apis = mongodb.saved_apis.find(
            {"user_id": user_id}
        ).sort("saved_at", -1)
        
        saved_apis = []
        for db_api in db_apis:
            # Handle versions field - convert dicts to APIVersion objects
            versions = []
            if "versions" in db_api and db_api["versions"]:
                for v_dict in db_api["versions"]:
                    try:
                        versions.append(APIVersion(**v_dict))
                    except Exception as e:
                        logger.warning(f"Failed to parse version: {e}")
                        continue
            
            saved_apis.append(SavedAPI(
                api_slug=db_api["api_slug"],
                user_id=db_api["user_id"],
                api_name=db_api["api_name"],
                prompt=db_api["prompt"],
                endpoint_url=db_api["endpoint_url"],
                documentation=db_api["documentation"],
                curl_example=db_api["curl_example"],
                openapi_spec=db_api.get("openapi_spec"),
                sample_input=db_api.get("sample_input"),
                expected_output=db_api.get("expected_output"),
                code=db_api.get("code"),
                created_at=db_api["created_at"],
                saved_at=db_api["saved_at"],
                is_saved=db_api.get("is_saved", True),
                current_version=db_api.get("current_version", 1),
                versions=versions
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
    
    def delete_api(self, user_id: str, api_slug: str) -> bool:
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
            mongodb.saved_apis.delete_one({
                "user_id": user_id,
                "api_slug": api_slug
            })
        except Exception:
            success = False
        
        return success
    
    def _api_file_exists(self, api_slug: str) -> bool:
        """Check if API file exists."""
        file_path = self._get_api_file_path(api_slug)
        return os.path.exists(file_path)
    
    def _get_api_file_path(self, api_slug: str) -> str:
        """
        Get the full file path for an API with security validation.
        
        DEPRECATED: Use _get_safe_file_path instead for new code.
        This method is kept for backward compatibility but now includes security checks.
        """
        return self._get_safe_file_path(api_slug)
    
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

    def _analyze_syntax_error(self, code: str, syntax_error: SyntaxError) -> str:
        """Analyze syntax error and provide helpful details."""
        error_msg = str(syntax_error)
        line_no = getattr(syntax_error, 'lineno', 0)
        
        # Get the problematic line if available
        lines = code.split('\n')
        if line_no and line_no <= len(lines):
            problematic_line = lines[line_no - 1]
            
            # Check for common issues
            if 'unterminated triple-quoted string' in error_msg.lower():
                return f"{error_msg} (Line {line_no}: unterminated triple-quote - {problematic_line.strip()})"
            elif '[' in problematic_line and ']' not in problematic_line:
                return f"{error_msg} (Line {line_no}: unclosed bracket '[' - {problematic_line.strip()})"
            elif '(' in problematic_line and ')' not in problematic_line:
                return f"{error_msg} (Line {line_no}: unclosed parenthesis '(' - {problematic_line.strip()})"
            elif '{' in problematic_line and '}' not in problematic_line:
                return f"{error_msg} (Line {line_no}: unclosed brace '{{' - {problematic_line.strip()})"
            elif '"""' in problematic_line:
                triple_count = problematic_line.count('"""')
                if triple_count % 2 == 1:
                    return f"{error_msg} (Line {line_no}: unclosed triple-quote - {problematic_line.strip()})"
            else:
                return f"{error_msg} (Line {line_no}: {problematic_line.strip()})"
        
        return error_msg

# Global instance
file_service = FileService() 