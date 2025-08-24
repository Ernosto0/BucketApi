"""
Claude Prompt Loader

Helper functions for loading and managing Claude-specific prompts
"""

import json
import os
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

def load_claude_prompt(prompt_name: str) -> Dict[str, Any]:
    """Load a Claude prompt configuration from JSON file"""
    try:
        # Get the directory of this file
        current_dir = os.path.dirname(os.path.abspath(__file__))
        prompt_path = os.path.join(current_dir, f"{prompt_name}.json")
        
        with open(prompt_path, 'r', encoding='utf-8') as f:
            prompt_config = json.load(f)
            
        logger.info(f"Successfully loaded Claude prompt: {prompt_name}")
        return prompt_config
        
    except FileNotFoundError:
        logger.error(f"Claude prompt file not found: {prompt_name}.json")
        raise ValueError(f"Claude prompt '{prompt_name}' not found")
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in Claude prompt {prompt_name}: {str(e)}")
        raise ValueError(f"Invalid JSON in Claude prompt '{prompt_name}': {str(e)}")
    except Exception as e:
        logger.error(f"Error loading Claude prompt {prompt_name}: {str(e)}")
        raise

def format_claude_prompt(prompt_config: Dict[str, Any], **kwargs) -> tuple[str, str]:
    """Format Claude prompt with provided variables
    
    Args:
        prompt_config: The loaded prompt configuration
        **kwargs: Variables to substitute in the prompt template
        
    Returns:
        tuple: (system_prompt, formatted_user_prompt)
    """
    try:
        system_prompt = prompt_config.get("system_prompt", "")
        user_prompt_template = prompt_config.get("user_prompt_template", "")
        
        # Format the user prompt template with provided variables
        formatted_user_prompt = user_prompt_template.format(**kwargs)
        
        return system_prompt, formatted_user_prompt
        
    except KeyError as e:
        logger.error(f"Missing required variable in prompt template: {str(e)}")
        raise ValueError(f"Missing required variable: {str(e)}")
    except Exception as e:
        logger.error(f"Error formatting Claude prompt: {str(e)}")
        raise

def get_claude_prompt_config(prompt_name: str) -> Dict[str, Any]:
    """Get Claude prompt configuration including model settings"""
    prompt_config = load_claude_prompt(prompt_name)
    
    return {
        "model": prompt_config.get("model", "claude-3-sonnet-20240229"),
        "temperature": prompt_config.get("temperature", 0.3),
        "max_completion_tokens": prompt_config.get("max_completion_tokens", 2000),
        "operation_type": prompt_config.get("operation_type", "general"),
        "validation_rules": prompt_config.get("validation_rules", {}),
        "expected_format": prompt_config.get("expected_format", {})
    }

def validate_claude_response(response: str, prompt_config: Dict[str, Any]) -> bool:
    """Validate Claude response against prompt configuration rules
    
    Args:
        response: The response from Claude
        prompt_config: The prompt configuration with validation rules
        
    Returns:
        bool: True if response passes validation
    """
    validation_rules = prompt_config.get("validation_rules", {})
    
    try:
        # Check minimum length requirements
        if "min_code_length" in validation_rules:
            if len(response.strip()) < validation_rules["min_code_length"]:
                logger.warning("Response too short according to validation rules")
                return False
        
        # Check for required content
        if "required_function" in validation_rules:
            if validation_rules["required_function"] not in response:
                logger.warning(f"Response missing required function: {validation_rules['required_function']}")
                return False
        
        # Check for forbidden patterns
        forbidden_patterns = validation_rules.get("forbidden_patterns", [])
        for pattern in forbidden_patterns:
            if pattern in response:
                logger.warning(f"Response contains forbidden pattern: {pattern}")
                return False
        
        # Check expected format requirements
        expected_format = prompt_config.get("expected_format", {})
        if "must_contain_documentation" in expected_format and expected_format["must_contain_documentation"]:
            if "documentation" not in response.lower():
                logger.warning("Response missing required documentation section")
                return False
        
        if "must_contain_curl_example" in expected_format and expected_format["must_contain_curl_example"]:
            if "curl" not in response.lower():
                logger.warning("Response missing required curl example")
                return False
        
        logger.info("Response passed all validation rules")
        return True
        
    except Exception as e:
        logger.error(f"Error during response validation: {str(e)}")
        return False

# Available Claude prompts
AVAILABLE_CLAUDE_PROMPTS = [
    "api_code_generator",
    "documentation_generator",
    "api_code_modifier"
]

def list_available_claude_prompts() -> list[str]:
    """Get list of available Claude prompts"""
    return AVAILABLE_CLAUDE_PROMPTS.copy()
