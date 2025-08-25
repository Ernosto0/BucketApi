"""
Claude Prompts Package

This package contains prompt configurations and utilities for Claude AI service integration.

Available prompts:
- api_code_generator: Generate new FastAPI-compatible Python code
- api_code_modifier: Modify existing Python code while preserving structure
- documentation_generator: Generate API documentation and curl examples
"""

from .prompt_loader import (
    load_claude_prompt,
    format_claude_prompt,
    get_claude_prompt_config,
    validate_claude_response,
    list_available_claude_prompts,
    AVAILABLE_CLAUDE_PROMPTS
)

__all__ = [
    "load_claude_prompt",
    "format_claude_prompt", 
    "get_claude_prompt_config",
    "validate_claude_response",
    "list_available_claude_prompts",
    "AVAILABLE_CLAUDE_PROMPTS"
]
