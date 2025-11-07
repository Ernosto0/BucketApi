# API Pricing and Internal Token System Guide

## Overview

The AI-Powered API Generator now includes a sophisticated pricing system that calculates usage costs for each generated API based on the underlying AI model used during creation. This system introduces **internal tokens** that are separate from AI model tokens and provides per-API pricing based on complexity and AI model costs.

## Key Concepts

### 1. Internal Tokens
- **Purpose**: Internal currency for API usage (separate from AI model tokens)
- **Exchange Rate**: 10,000 internal tokens = $1 (or 100 internal tokens = 1 cent)
- **Monthly Allocation**: 100,000 internal tokens (worth $10) for free tier users
- **Expiration**: Tokens expire at the end of the month following allocation

### 2. API Metadata and Pricing
Each generated API has metadata that includes:
- **AI Model Used**: The LLM model used during API generation (e.g., gpt-3.5-turbo, claude-3-sonnet)
- **Estimated Tokens Per Call**: Average AI model tokens consumed per API execution
- **Base Complexity**: Simple, medium, or complex rating
- **Cost Per Call**: Calculated cost in cents per API execution

### 3. Complexity Multipliers
- **Simple** (1.0x): Basic text processing, simple calculations
- **Medium** (1.5x): Data transformation, validation logic
- **Complex** (2.0x): ML inference, advanced business logic

## How Pricing Works

### 1. API Generation Phase
When an API is generated:
1. The system tracks which AI model was used (Claude, GPT, etc.)
2. Estimates token usage based on prompt complexity
3. Calculates base cost using model pricing
4. Applies complexity multiplier
5. Saves metadata for future pricing calculations

```python
# Example pricing calculation
base_cost_per_1k_tokens = 3.0  # $0.03 for GPT-4
estimated_tokens = 1500
complexity_multiplier = 1.5  # Medium complexity
cost_per_call_cents = (1500/1000) * 3.0 * 1.5 = 6.75 cents
internal_tokens_per_call = 6.75 * 100 = 675 tokens
```

### 2. API Testing Phase
During testing:
- Cost estimation is calculated and displayed in response headers
- No tokens are deducted (testing is free)
- Users can see exact pricing before using the API

### 3. API Execution Phase
When APIs are called:
1. System checks user's internal token balance
2. Verifies sufficient tokens for the call
3. Executes the API if balance is sufficient
4. Deducts internal tokens upon successful execution
5. Records usage for analytics

## API Endpoints

### Token Management

#### Get Token Balance
```http
GET /internal-token-balance
Authorization: Bearer <token>
```

Response:
```json
{
  "user_id": "user123",
  "total_tokens": 9500,
  "used_tokens": 500,
  "remaining_tokens": 9500,
  "monthly_allocation": 10000,
  "expires_soon_tokens": 0,
  "last_updated": "2024-01-15T10:30:00"
}
```

#### Allocate Monthly Tokens
```http
POST /allocate-monthly-tokens
Authorization: Bearer <token>
Content-Type: application/json

{
  "amount": 10000
}
```

### Pricing Information

#### Get API Cost
```http
GET /api-cost/{api_slug}
Authorization: Bearer <token>
```

Response:
```json
{
  "api_slug": "name-extractor",
  "cost_per_call_cents": 5,
  "internal_tokens_per_call": 50,
  "ai_model_used": "gpt-3.5-turbo",
  "complexity_multiplier": 1.5,
  "estimated_tokens_used": 1200,
  "last_calculated": "2024-01-15T10:30:00"
}
```

#### Estimate API Cost
```http
POST /estimate-api-cost
Authorization: Bearer <token>
Content-Type: application/json

{
  "api_slug": "my-api",
  "sample_input": "Extract names from this text",
  "expected_calls_per_month": 1000
}
```

Response:
```json
{
  "api_slug": "my-api",
  "cost_per_call_cents": 3,
  "internal_tokens_per_call": 30,
  "estimated_monthly_cost_cents": 3000,
  "estimated_monthly_tokens": 30000,
  "ai_model_used": "gpt-3.5-turbo",
  "complexity_rating": "medium",
  "breakdown": {
    "base_cost_per_1k_tokens": 0.15,
    "estimated_ai_tokens": 1000,
    "complexity_multiplier": 1.5,
    "tokens_per_cent_ratio": 10
  }
}
```

### Usage Analytics

#### API Execution Stats
```http
GET /api-execution-stats?days=30
Authorization: Bearer <token>
```

#### API Execution Limits
```http
GET /api-execution-limits
Authorization: Bearer <token>
```

## Database Schema

### API Metadata Table
```sql
CREATE TABLE api_metadata (
    id TEXT PRIMARY KEY,
    api_slug TEXT NOT NULL,
    user_id TEXT NOT NULL,
    ai_model_used TEXT NOT NULL,
    estimated_tokens_per_call INTEGER DEFAULT 0,
    estimated_cost_per_call_cents INTEGER DEFAULT 0,
    base_complexity TEXT DEFAULT 'medium',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### Internal Tokens Table
```sql
CREATE TABLE internal_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    api_key_id TEXT,
    token_type TEXT DEFAULT 'api_execution',
    amount INTEGER NOT NULL,
    source TEXT NOT NULL,
    expires_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    used_at DATETIME,
    is_used BOOLEAN DEFAULT FALSE
);
```

### Token Usage Tracking Table
```sql
CREATE TABLE api_execution_token_usage (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    api_key_id TEXT,
    api_slug TEXT NOT NULL,
    internal_tokens_used INTEGER NOT NULL,
    cost_cents INTEGER NOT NULL,
    execution_successful BOOLEAN DEFAULT TRUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Error Handling

### Insufficient Tokens
When a user doesn't have enough internal tokens:

```json
{
  "detail": "Insufficient internal tokens. Need 50, have 25",
  "status_code": 402
}
```

### API Metadata Not Found
If pricing information isn't available:

```json
{
  "detail": "API metadata not found for my-api",
  "status_code": 404
}
```

## Implementation Flow

### 1. API Generation
```python
# In generate_api endpoint
await api_pricing_service.save_api_metadata(
    api_slug=clean_slug,
    user_id=request.user_id,
    ai_model_used="claude-3-sonnet",
    estimated_tokens_per_call=1500,
    base_complexity='medium'
)
```

### 2. API Execution
```python
# In execute_api endpoint
# Check cost and balance
api_cost = await api_pricing_service.get_api_execution_cost(api_slug, user_id)
token_balance = await api_pricing_service.get_token_balance(user_id, api_key_id)

if token_balance.remaining_tokens < api_cost.internal_tokens_per_call:
    raise HTTPException(status_code=402, detail="Insufficient tokens")

# Execute API...

# Deduct tokens
await api_pricing_service.deduct_tokens_for_execution(
    user_id=user_id,
    api_key_id=api_key_id,
    api_slug=api_slug,
    internal_tokens_needed=api_cost.internal_tokens_per_call,
    cost_cents=api_cost.cost_per_call_cents,
    execution_successful=True
)
```

### 3. Monthly Token Allocation
```python
# Monthly task or user registration
await api_pricing_service.allocate_monthly_tokens(
    user_id=user_id,
    amount=10000  # Default monthly allocation
)
```

## Configuration

### Model Pricing (cents per 1k tokens)
```python
AI_MODEL_BASE_COSTS = {
    'gpt-3.5-turbo': 0.15,
    'gpt-4': 3.0,
    'gpt-4-turbo': 1.0,
    'claude-3-haiku': 2.5,
    'claude-3-sonnet': 30.0,
    'claude-3-opus': 150.0,
}
```

### Token Economics
```python
TOKENS_PER_CENT = 10  # 10 internal tokens = 1 cent
DEFAULT_MONTHLY_TOKEN_ALLOCATION = 10000  # $10 worth
```

## Benefits

1. **Fair Pricing**: Users pay based on actual AI model costs and complexity
2. **Transparency**: Clear pricing before execution
3. **Budget Control**: Monthly token limits prevent overspending
4. **Analytics**: Detailed usage tracking per API
5. **Flexibility**: Different pricing for different AI models and complexity levels

## Future Enhancements

1. **Dynamic Pricing**: Adjust costs based on actual token usage during execution
2. **Subscription Plans**: Different monthly allocations for paid tiers
3. **Bulk Discounts**: Lower per-call costs for high-volume usage
4. **Custom Pricing**: Per-user or per-organization pricing models
5. **Real-time Monitoring**: Usage alerts and spending notifications

This system provides a robust foundation for monetizing generated APIs while maintaining transparency and fairness for users. 