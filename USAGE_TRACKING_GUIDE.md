# LLM Usage Tracking System

This document describes the comprehensive LLM usage tracking system implemented for the AI-Powered API Generator.

## Overview

The usage tracking system monitors and limits LLM usage (Claude, OpenAI) across all operations including:
- Code generation
- Code modification  
- Documentation generation
- Code debugging and analysis
- Test result validation
- Comprehensive debugging
- Prompt analysis

## Features

### 📊 **Usage Monitoring**
- Track tokens used (input/output)
- Monitor costs per request
- Record request duration and metadata
- Track success/failure rates
- Associate usage with API keys and users

### 🚦 **Rate Limiting**
- Daily token limits (default: 100,000 tokens)
- Monthly token limits (default: 1,000,000 tokens)
- Daily cost limits (default: $10.00)
- Automatic limit enforcement

### 💰 **Cost Tracking**
- Real-time cost estimation
- Support for multiple models and pricing
- Accurate billing per service (Claude, OpenAI)

### 📈 **Analytics**
- Usage statistics by service and operation
- Historical data tracking
- Usage trends and patterns

## Database Schema

### LLM Usage Table (`llm_usage`)
```sql
CREATE TABLE llm_usage (
    id VARCHAR PRIMARY KEY,
    user_id VARCHAR NOT NULL,
    api_key_id VARCHAR,
    service_type VARCHAR NOT NULL,  -- 'claude', 'openai'
    operation_type VARCHAR NOT NULL, -- 'code_generation', 'code_modification', 'documentation', 'code_debugging', 'test_validation', 'comprehensive_debugging', 'analysis'
    model_name VARCHAR NOT NULL,    -- 'claude-3-sonnet', 'gpt-4', etc.
    
    -- Token usage
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    total_tokens INTEGER DEFAULT 0,
    
    -- Cost tracking (in USD cents)
    estimated_cost_cents INTEGER DEFAULT 0,
    
    -- Request metadata
    prompt_length INTEGER DEFAULT 0,
    response_length INTEGER DEFAULT 0,
    request_duration_ms INTEGER DEFAULT 0,
    
    -- Context and debugging
    operation_context TEXT,         -- JSON string with additional context
    api_slug VARCHAR,              -- Related API if applicable
    
    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME,
    
    -- Status
    success BOOLEAN DEFAULT TRUE,
    error_message TEXT
);
```

## API Endpoints

### Usage Statistics
```http
GET /usage/stats?days=30&api_key_id=optional
```
Returns comprehensive usage statistics including:
- Total requests and tokens
- Cost breakdown by service/operation
- Recent usage history

### Usage Limits
```http
GET /usage/limits?api_key_id=optional
```
Returns current usage limits and remaining quotas:
- Daily/monthly token usage
- Cost limits
- Time until reset

### Cost Estimation
```http
GET /usage/estimate-cost?model_name=claude-3-sonnet&input_tokens=1000&output_tokens=500
```
Estimates costs before making requests.

### Manual Usage Recording
```http
POST /usage/record
```
For testing or external integrations.

## Service Integration

### Automatic Tracking
All LLM services now automatically track usage:

#### Claude Service
```python
# Code generation with tracking
code = await claude_service.generate_api_code(
    prompt="Generate a calculator API",
    user_id="user123",
    api_key_id="key456"  # Optional
)
```

#### OpenAI Service
```python
# Documentation generation with tracking
docs = await openai_service.generate_documentation(
    code=code,
    prompt=prompt,
    user_id="user123"
)
```

#### Code Debugger Service
```python
# Code debugging and fixing with tracking
fixed_code, issues, fixes = await code_debugger.analyze_and_fix_code(
    generated_code="def run():\n  return {result: 'test'}",
    original_prompt="Create a test API",
    user_id="user123",
    api_key_id="key456"
)

# Test result validation with tracking
validation_result = await code_debugger.validate_and_fix_test_result(
    code=api_code,
    test_request=test_data,
    test_response=test_result,
    user_id="user123",
    api_slug="my-api"
)
```

### Rate Limiting
Before each LLM operation, the system:
1. Checks current usage against limits
2. Estimates tokens for the request
3. Blocks requests that would exceed limits
4. Returns HTTP 429 (Too Many Requests) if over limit

## Configuration

### Default Limits
```python
# In UsageService
DEFAULT_DAILY_TOKEN_LIMIT = 100000      # 100k tokens per day
DEFAULT_MONTHLY_TOKEN_LIMIT = 1000000   # 1M tokens per month  
DEFAULT_DAILY_COST_LIMIT_CENTS = 1000   # $10 per day
```

### Model Pricing (in USD)
```python
COST_PER_TOKEN = {
    # Claude pricing (input/output tokens)
    'claude-3-haiku': {'input': 0.000025, 'output': 0.000125},
    'claude-3-sonnet': {'input': 0.0003, 'output': 0.0015},
    'claude-3-opus': {'input': 0.0015, 'output': 0.0075},
    
    # OpenAI pricing
    'gpt-3.5-turbo': {'input': 0.00015, 'output': 0.0002},
    'gpt-4': {'input': 0.003, 'output': 0.006},
    'gpt-4-turbo': {'input': 0.001, 'output': 0.002},
}
```

## Usage Examples

### Generate API with Tracking
```python
# The system automatically tracks usage when generating APIs
response = await client.post("/generate-api", json={
    "user_id": "user123",
    "prompt": "Create a weather API",
    "api_name": "WeatherService"
})
```

### Check Usage Limits
```python
# Before expensive operations
limits = await client.get("/usage/limits")
if limits["is_over_limit"]:
    raise Exception("Usage limit exceeded")
```

### Monitor Costs
```python
# Get detailed usage statistics
stats = await client.get("/usage/stats?days=7")
print(f"Weekly cost: ${stats['total_cost_cents']/100:.2f}")
```

## Authentication & API Keys

The system supports both JWT tokens and API keys:

### JWT Authentication
- Usage tracked per user
- No API key association

### API Key Authentication  
- Usage tracked per user AND API key
- Enables per-key limits and monitoring
- Useful for service accounts and integrations

## Error Handling

### Over Limit Response
```json
{
    "detail": "Usage limit exceeded. Daily tokens used: 95000/100000",
    "status_code": 429
}
```

### Usage Recording Failures
- Non-blocking: LLM operations continue even if usage recording fails
- Logged for debugging
- Graceful degradation

## Monitoring & Alerts

### Key Metrics to Monitor
- Daily/monthly token usage trends
- Cost per operation type
- Success/failure rates
- API response times
- Users approaching limits

### Recommended Alerts
- Users over 80% of daily limit
- Unusual cost spikes
- High error rates
- API key usage anomalies

## Development & Testing

### Running Tests
```bash
# Test the usage tracking system
python test_usage_system.py
```

### Database Setup
```python
from app.services.database import create_tables
create_tables()
```

### Environment Variables
```bash
# Required for LLM services
CLAUDE_API_KEY=your_claude_key
OPENAI_API_KEY=your_openai_key
```

## Future Enhancements

### Potential Improvements
1. **User-specific limits** - Different limits per user tier
2. **Webhook notifications** - Alert on limit approaches
3. **Usage forecasting** - Predict future usage patterns
4. **Batch operations** - Efficient bulk usage recording
5. **Export capabilities** - Usage data export for billing
6. **Advanced analytics** - ML-powered usage insights

### Integration Opportunities
1. **Billing systems** - Automatic invoice generation
2. **Monitoring tools** - Grafana/Prometheus metrics
3. **Notification services** - Email/Slack alerts
4. **Admin dashboards** - Usage management interface

## Troubleshooting

### Common Issues

**Usage not being recorded:**
- Check database connection
- Verify service imports
- Check for exceptions in logs

**Limits not enforcing:**
- Verify limit checking logic
- Check authentication flow
- Review error handling

**Inaccurate cost estimates:**
- Update model pricing
- Check token estimation logic
- Verify model name mapping

### Debug Commands
```python
# Check database connection
from app.services.usage_service import usage_service
await usage_service.record_usage(...)

# Verify limits
limits = await usage_service.check_usage_limits("user_id")
print(limits)
```

---

This usage tracking system provides comprehensive monitoring and control over LLM operations, ensuring cost management and preventing abuse while maintaining a smooth user experience. 