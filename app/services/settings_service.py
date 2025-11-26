"""
Settings Management Service
Handles dynamic configuration management for the application.
"""

import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from ..services.mongodb import mongodb

logger = logging.getLogger(__name__)


class SettingsService:
    """Service for managing application settings dynamically."""
    
    # Define all configurable settings with metadata
    SETTINGS_SCHEMA = {
        # AI Service Configuration
        "OPENAI_MODEL": {
            "category": "ai",
            "value_type": "string",
            "description": "OpenAI model to use for API generation",
            "is_sensitive": False,
            "requires_restart": True,
            "default": "gpt-4-turbo",
            "allowed_values": ["gpt-4", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o", "gpt-4o-mini", "gpt-5-mini",]
        },
        "CLAUDE_MODEL": {
            "category": "ai",
            "value_type": "string",
            "description": "Claude model to use for API generation",
            "is_sensitive": False,
            "requires_restart": True,
            "default": "claude-3-5-haiku-latest",
            "allowed_values": ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-3-opus-latest"]
        },
        "MAX_TOKENS_OPENAI": {
            "category": "ai",
            "value_type": "int",
            "description": "Maximum tokens for OpenAI requests",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 10000,
            "min_value": 1000,
            "max_value": 100000
        },
        "MAX_TOKENS_CLAUDE": {
            "category": "ai",
            "value_type": "int",
            "description": "Maximum tokens for Claude requests",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 10000,
            "min_value": 1000,
            "max_value": 100000
        },
        "TEMPERATURE_OPENAI": {
            "category": "ai",
            "value_type": "float",
            "description": "Temperature for OpenAI model (0.0-2.0)",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 0.3,
            "min_value": 0.0,
            "max_value": 2.0
        },
        "TEMPERATURE_CLAUDE": {
            "category": "ai",
            "value_type": "float",
            "description": "Temperature for Claude model (0.0-1.0)",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 0.3,
            "min_value": 0.0,
            "max_value": 1.0
        },
        "GENERATE_DOCS_SERVICE": {
            "category": "ai",
            "value_type": "string",
            "description": "Service to use for documentation generation",
            "is_sensitive": False,
            "requires_restart": True,
            "default": "OPENAI_SERVICE",
            "allowed_values": ["OPENAI_SERVICE", "CLAUDE_SERVICE"]
        },
        
        # Security Configuration
        "SECURITY_SERVICE_ENABLED": {
            "category": "security",
            "value_type": "bool",
            "description": "Enable/disable security service for code validation",
            "is_sensitive": False,
            "requires_restart": True,
            "default": True
        },
        "MAX_FILE_SIZE": {
            "category": "security",
            "value_type": "int",
            "description": "Maximum file upload size in bytes",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 10485760,  # 10MB
            "min_value": 1048576,  # 1MB
            "max_value": 104857600  # 100MB
        },
        
        # Application Configuration
        "ENVIRONMENT": {
            "category": "application",
            "value_type": "string",
            "description": "Application environment (development/production)",
            "is_sensitive": False,
            "requires_restart": True,
            "default": "development",
            "allowed_values": ["development", "production", "staging"]
        },
        "PORT": {
            "category": "application",
            "value_type": "int",
            "description": "Application port",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 8001,
            "min_value": 1024,
            "max_value": 65535
        },
        "HOST": {
            "category": "application",
            "value_type": "string",
            "description": "Application host",
            "is_sensitive": False,
            "requires_restart": True,
            "default": "127.0.0.1"
        },
        
        # Retry Configuration
        "RETRY_MAX_ATTEMPTS": {
            "category": "application",
            "value_type": "int",
            "description": "Maximum retry attempts for failed operations",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 3,
            "min_value": 1,
            "max_value": 10
        },
        "RETRY_MAX_DELAY_SECONDS": {
            "category": "application",
            "value_type": "int",
            "description": "Maximum delay between retries in seconds",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 10,
            "min_value": 1,
            "max_value": 60
        },
        "RETRY_MIN_DELAY_SECONDS": {
            "category": "application",
            "value_type": "int",
            "description": "Minimum delay between retries in seconds",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 2,
            "min_value": 1,
            "max_value": 30
        },
        
        # Authentication Configuration
        "ACCESS_TOKEN_EXPIRE_MINUTES": {
            "category": "authentication",
            "value_type": "int",
            "description": "Access token expiration time in minutes",
            "is_sensitive": False,
            "requires_restart": True,
            "default": 4320,  # 3 days
            "min_value": 60,
            "max_value": 43200  # 30 days
        },
        
        # Feature Flags
        "ENABLE_CUSTOM_AUTH": {
            "category": "features",
            "value_type": "bool",
            "description": "Enable custom email/password authentication",
            "is_sensitive": False,
            "requires_restart": True,
            "default": False
        },
        "ENABLE_GOOGLE_AUTH": {
            "category": "features",
            "value_type": "bool",
            "description": "Enable Google OAuth authentication",
            "is_sensitive": False,
            "requires_restart": True,
            "default": True
        },
        "ENABLE_GITHUB_AUTH": {
            "category": "features",
            "value_type": "bool",
            "description": "Enable GitHub OAuth authentication",
            "is_sensitive": False,
            "requires_restart": True,
            "default": True
        },
        "ENABLE_TEST_VALIDATION_DEBUGGING": {
            "category": "features",
            "value_type": "bool",
            "description": "Enable test validation debugging",
            "is_sensitive": False,
            "requires_restart": True,
            "default": True
        },
    }
    
    def __init__(self):
        """Initialize the settings service."""
        self.collection = mongodb.system_settings
        self._ensure_settings_initialized()
    
    def _ensure_settings_initialized(self):
        """Ensure all settings exist in the database with default values."""
        try:
            for key, schema in self.SETTINGS_SCHEMA.items():
                existing = self.collection.find_one({"key": key})
                if not existing:
                    # Get current value from environment or use default
                    current_value = os.getenv(key, schema["default"])
                    
                    # Convert to appropriate type
                    if schema["value_type"] == "int":
                        current_value = int(current_value)
                    elif schema["value_type"] == "float":
                        current_value = float(current_value)
                    elif schema["value_type"] == "bool":
                        if isinstance(current_value, str):
                            current_value = current_value.lower() == "true"
                        else:
                            current_value = bool(current_value)
                    
                    setting_doc = {
                        "key": key,
                        "value": current_value,
                        "value_type": schema["value_type"],
                        "category": schema["category"],
                        "description": schema["description"],
                        "is_sensitive": schema["is_sensitive"],
                        "requires_restart": schema["requires_restart"],
                        "created_at": datetime.utcnow(),
                        "last_updated": datetime.utcnow(),
                        "updated_by": None
                    }
                    self.collection.insert_one(setting_doc)
                    logger.info(f"Initialized setting: {key} = {current_value}")
        except Exception as e:
            logger.error(f"Failed to initialize settings: {str(e)}")
    
    def get_all_settings(self, include_sensitive: bool = False) -> List[Dict[str, Any]]:
        """
        Get all settings from the database.
        
        Args:
            include_sensitive: Whether to include actual values for sensitive settings
            
        Returns:
            List of setting dictionaries
        """
        try:
            settings = list(self.collection.find({}))
            
            result = []
            for setting in settings:
                setting_dict = {
                    "key": setting["key"],
                    "value": setting["value"] if not setting.get("is_sensitive") or include_sensitive else "***HIDDEN***",
                    "value_type": setting["value_type"],
                    "category": setting["category"],
                    "description": setting.get("description"),
                    "is_sensitive": setting.get("is_sensitive", False),
                    "requires_restart": setting.get("requires_restart", True),
                    "last_updated": setting.get("last_updated"),
                    "updated_by": setting.get("updated_by")
                }
                
                # Add schema metadata
                if setting["key"] in self.SETTINGS_SCHEMA:
                    schema = self.SETTINGS_SCHEMA[setting["key"]]
                    if "allowed_values" in schema:
                        setting_dict["allowed_values"] = schema["allowed_values"]
                    if "min_value" in schema:
                        setting_dict["min_value"] = schema["min_value"]
                    if "max_value" in schema:
                        setting_dict["max_value"] = schema["max_value"]
                
                result.append(setting_dict)
            
            return result
        except Exception as e:
            logger.error(f"Failed to get settings: {str(e)}")
            return []
    
    def get_setting(self, key: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific setting by key.
        
        Args:
            key: Setting key
            
        Returns:
            Setting dictionary or None if not found
        """
        try:
            setting = self.collection.find_one({"key": key})
            if setting:
                return {
                    "key": setting["key"],
                    "value": setting["value"],
                    "value_type": setting["value_type"],
                    "category": setting["category"],
                    "description": setting.get("description"),
                    "is_sensitive": setting.get("is_sensitive", False),
                    "requires_restart": setting.get("requires_restart", True),
                    "last_updated": setting.get("last_updated"),
                    "updated_by": setting.get("updated_by")
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get setting {key}: {str(e)}")
            return None
    
    def update_setting(self, key: str, value: Any, admin_user_id: str) -> Dict[str, Any]:
        """
        Update a setting value.
        
        Args:
            key: Setting key
            value: New value
            admin_user_id: ID of admin user making the change
            
        Returns:
            Result dictionary with success status and message
        """
        try:
            # Check if setting exists in schema
            if key not in self.SETTINGS_SCHEMA:
                return {
                    "success": False,
                    "message": f"Unknown setting: {key}"
                }
            
            schema = self.SETTINGS_SCHEMA[key]
            
            # Validate and convert value type
            try:
                if schema["value_type"] == "int":
                    value = int(value)
                    if "min_value" in schema and value < schema["min_value"]:
                        return {
                            "success": False,
                            "message": f"Value must be at least {schema['min_value']}"
                        }
                    if "max_value" in schema and value > schema["max_value"]:
                        return {
                            "success": False,
                            "message": f"Value must be at most {schema['max_value']}"
                        }
                elif schema["value_type"] == "float":
                    value = float(value)
                    if "min_value" in schema and value < schema["min_value"]:
                        return {
                            "success": False,
                            "message": f"Value must be at least {schema['min_value']}"
                        }
                    if "max_value" in schema and value > schema["max_value"]:
                        return {
                            "success": False,
                            "message": f"Value must be at most {schema['max_value']}"
                        }
                elif schema["value_type"] == "bool":
                    if isinstance(value, str):
                        value = value.lower() in ["true", "1", "yes"]
                    else:
                        value = bool(value)
                elif schema["value_type"] == "string":
                    value = str(value)
                    if "allowed_values" in schema and value not in schema["allowed_values"]:
                        return {
                            "success": False,
                            "message": f"Value must be one of: {', '.join(schema['allowed_values'])}"
                        }
            except (ValueError, TypeError) as e:
                return {
                    "success": False,
                    "message": f"Invalid value type. Expected {schema['value_type']}: {str(e)}"
                }
            
            # Update in database
            result = self.collection.update_one(
                {"key": key},
                {
                    "$set": {
                        "value": value,
                        "last_updated": datetime.utcnow(),
                        "updated_by": admin_user_id
                    }
                },
                upsert=True
            )
            
            if result.modified_count > 0 or result.upserted_id:
                logger.info(f"Setting {key} updated to {value} by admin {admin_user_id}")
                
                # Clear config cache so changes take effect immediately
                try:
                    from ..config import settings
                    settings.clear_cache()
                except Exception as e:
                    logger.warning(f"Failed to clear config cache: {str(e)}")
                
                # Get updated setting
                updated_setting = self.get_setting(key)
                
                return {
                    "success": True,
                    "message": f"Setting {key} updated successfully",
                    "setting": updated_setting,
                    "requires_restart": schema["requires_restart"]
                }
            else:
                return {
                    "success": False,
                    "message": "No changes made"
                }
                
        except Exception as e:
            logger.error(f"Failed to update setting {key}: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to update setting: {str(e)}"
            }
    
    def get_categories(self) -> List[str]:
        """Get list of all setting categories."""
        categories = set()
        for schema in self.SETTINGS_SCHEMA.values():
            categories.add(schema["category"])
        return sorted(list(categories))
    
    def get_settings_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Get all settings in a specific category."""
        try:
            settings = list(self.collection.find({"category": category}))
            
            result = []
            for setting in settings:
                setting_dict = {
                    "key": setting["key"],
                    "value": setting["value"] if not setting.get("is_sensitive") else "***HIDDEN***",
                    "value_type": setting["value_type"],
                    "category": setting["category"],
                    "description": setting.get("description"),
                    "is_sensitive": setting.get("is_sensitive", False),
                    "requires_restart": setting.get("requires_restart", True),
                    "last_updated": setting.get("last_updated"),
                    "updated_by": setting.get("updated_by")
                }
                
                # Add schema metadata
                if setting["key"] in self.SETTINGS_SCHEMA:
                    schema = self.SETTINGS_SCHEMA[setting["key"]]
                    if "allowed_values" in schema:
                        setting_dict["allowed_values"] = schema["allowed_values"]
                    if "min_value" in schema:
                        setting_dict["min_value"] = schema["min_value"]
                    if "max_value" in schema:
                        setting_dict["max_value"] = schema["max_value"]
                
                result.append(setting_dict)
            
            return result
        except Exception as e:
            logger.error(f"Failed to get settings for category {category}: {str(e)}")
            return []
    
    def reset_to_defaults(self, admin_user_id: str) -> Dict[str, Any]:
        """Reset all settings to their default values."""
        try:
            reset_count = 0
            for key, schema in self.SETTINGS_SCHEMA.items():
                self.collection.update_one(
                    {"key": key},
                    {
                        "$set": {
                            "value": schema["default"],
                            "last_updated": datetime.utcnow(),
                            "updated_by": admin_user_id
                        }
                    }
                )
                reset_count += 1
            
            logger.info(f"Reset {reset_count} settings to defaults by admin {admin_user_id}")
            
            # Clear config cache so changes take effect immediately
            try:
                from ..config import settings
                settings.clear_cache()
            except Exception as e:
                logger.warning(f"Failed to clear config cache: {str(e)}")
            
            return {
                "success": True,
                "message": f"Reset {reset_count} settings to default values",
                "requires_restart": True
            }
        except Exception as e:
            logger.error(f"Failed to reset settings: {str(e)}")
            return {
                "success": False,
                "message": f"Failed to reset settings: {str(e)}"
            }


# Singleton instance
settings_service = SettingsService()

