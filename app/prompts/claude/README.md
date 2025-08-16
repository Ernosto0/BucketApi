# Claude Prompts

This directory contains prompt configurations for Claude AI service integration.

## Available Prompts

### 1. api_code_generator.json
**Purpose**: Generate FastAPI-compatible Python code based on user requirements.

**Features**:
- Enforces modern coding patterns (async/await, modern OpenAI client)
- Includes comprehensive validation rules
- Prevents deprecated API usage patterns
- Ensures proper error handling and security

**Usage**:
```python
from app.prompts.claude import load_claude_prompt, format_claude_prompt

prompt_config = load_claude_prompt("api_code_generator")
system_prompt, user_prompt = format_claude_prompt(prompt_config, 
    prompt="Create a text analysis API",
    sample_input_section="\nSample Input: {'text': 'Hello world'}",
    expected_output_section="\nExpected Output: {'sentiment': 'positive'}"
)
```

### 2. api_code_modifier.json
**Purpose**: Modify existing FastAPI-compatible Python code based on user requirements.

**Features**:
- Preserves original function signature and core structure
- Maintains backward compatibility unless explicitly requested
- Enforces modern coding patterns and API usage
- Validates preservation of critical code elements
- Enhanced error handling for modification-specific scenarios

**Usage**:
```python
prompt_config = load_claude_prompt("api_code_modifier")
system_prompt, user_prompt = format_claude_prompt(prompt_config,
    prompt="Add input validation to the API",
    existing_code="async def run(input_data=None): ...",
    sample_input_section="\nSample Input: {'text': 'Hello'}",
    expected_output_section=""
)
```

### 3. documentation_generator.json
**Purpose**: Generate clear API documentation and curl examples.

**Features**:
- Creates markdown-formatted documentation
- Generates practical curl examples
- Validates output format and content length
- Ensures both documentation and examples are present

**Usage**:
```python
prompt_config = load_claude_prompt("documentation_generator")
system_prompt, user_prompt = format_claude_prompt(prompt_config,
    prompt="Text analysis API",
    code="async def run(input_data=None): ..."
)
```

## Prompt Structure

Each prompt JSON file contains:

```json
{
  "system_prompt": "The system/context prompt for Claude",
  "user_prompt_template": "Template with {variables} for formatting",
  "description": "Human-readable description",
  "model": "claude-3-sonnet-20240229",
  "temperature": 0.3,
  "max_tokens": 2000,
  "operation_type": "code_generation|documentation_generation",
  "validation_rules": {
    "min_code_length": 10,
    "required_function": "async def run",
    "forbidden_patterns": ["deprecated_pattern"]
  },
  "expected_format": {
    "must_contain_documentation": true,
    "documentation_min_length": 20
  }
}
```

## Validation Rules

### Code Generation
- **min_code_length**: Minimum character count for generated code
- **required_function**: Function that must be present in the code
- **forbidden_patterns**: Array of patterns that should not appear

### Code Modification
- **preservation_rules**: Rules for maintaining existing code structure
  - **must_maintain_function_signature**: Ensures function signatures are preserved
  - **must_preserve_core_structure**: Maintains overall code organization
  - **must_maintain_backward_compatibility**: Prevents breaking changes
- **must_contain_existing_logic**: Validates that original functionality is preserved
- **must_maintain_error_handling**: Ensures error handling patterns are kept

### Documentation Generation
- **must_contain_documentation**: Ensures documentation section exists
- **must_contain_curl_example**: Ensures curl example exists
- **documentation_min_length**: Minimum length for documentation
- **curl_min_length**: Minimum length for curl examples

## Integration with Claude Service

The prompts are automatically loaded and validated by the Claude service:

```python
# In claude_service.py
from app.prompts.claude import load_claude_prompt, validate_claude_response

# Load prompt
prompt_config = load_claude_prompt("api_code_generator")

# Generate response
response = await self._make_claude_request(system_prompt, user_prompt, ...)

# Validate response
if not validate_claude_response(response, prompt_config):
    raise CodeExtractionError("Validation failed")
```

## Error Handling

Prompt loading includes comprehensive error handling:
- **FileNotFoundError**: Prompt file doesn't exist
- **JSONDecodeError**: Invalid JSON format
- **KeyError**: Missing required template variables
- **ValidationError**: Response doesn't meet prompt requirements

All errors are logged and converted to appropriate `PromptBuildError` or `CodeExtractionError` exceptions.

## Adding New Prompts

1. Create a new JSON file following the structure above
2. Add the prompt name to `AVAILABLE_CLAUDE_PROMPTS` in `prompt_loader.py`
3. Update validation rules as needed
4. Test the prompt with various inputs
5. Document the prompt in this README

## Best Practices

1. **Template Variables**: Use descriptive variable names in `{variable}` format
2. **Validation**: Always include appropriate validation rules
3. **Error Messages**: Make validation error messages specific and helpful
4. **Testing**: Test prompts with edge cases and various input types
5. **Documentation**: Keep this README updated when adding new prompts
