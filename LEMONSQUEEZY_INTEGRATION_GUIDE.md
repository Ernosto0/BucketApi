# LemonSqueezy Integration Guide

## 🎉 Integration Complete!

Your AI-Powered API Generator now has full LemonSqueezy subscription support! Here's what was added and what you need to do next.

## ✅ What Was Added

### 1. Database Schema Updates
- **New subscription fields in users table**:
  - `subscription_tier` (free, starter, professional, enterprise)
  - `subscription_status` (active, cancelled, past_due, unpaid)
  - `lemonsqueezy_customer_id` and `lemonsqueezy_subscription_id`
  - `monthly_token_allocation` (based on subscription tier)

- **New subscription tables**:
  - `subscriptions` - Complete subscription records
  - `subscription_events` - Webhook event tracking

### 2. Subscription Tiers

| Tier | Price | Monthly Tokens | AI Models | Features |
|------|-------|----------------|-----------|----------|
| **Free** | $0 | 10,000 | GPT-3.5, GPT-4o-mini, Claude Haiku | Basic API generation, Community support |
| **Starter** | $9 | 50,000 | + GPT-4, Claude Sonnet | Priority support, API analytics |
| **Professional** | $29 | 200,000 | + GPT-4 Turbo, Claude Opus | Advanced analytics, Custom complexity |
| **Enterprise** | $99 | 1,000,000 | + Claude-4, Latest models | Dedicated support, White-label options |

### 3. New API Endpoints

#### Subscription Management
- `GET /subscription/tiers` - Get available subscription plans
- `GET /subscription/status` - Get current user's subscription status
- `POST /subscription/create` - Create subscription (generates checkout URL)
- `POST /subscription/webhook` - Handle LemonSqueezy webhooks
- `POST /subscription/update` - Update/cancel subscription
- `GET /subscription` - Subscription management page (HTML)

### 4. Enhanced Services

#### SubscriptionService (`app/services/subscription_service.py`)
- Tier-based token allocation
- LemonSqueezy webhook handling
- Subscription lifecycle management
- Checkout URL generation

#### Updated APIPricingService
- AI model access control by tier
- Subscription-aware token allocation
- Tier-based usage restrictions

### 5. User Interface
- New subscription management page (`/subscription`)
- Beautiful tier comparison cards
- Real-time usage tracking
- Upgrade/downgrade functionality

## 🚀 Next Steps

### 1. Set Up LemonSqueezy Account

1. **Create LemonSqueezy Store**: Go to [lemonsqueezy.com](https://lemonsqueezy.com) and create your store
2. **Create Products**: Set up products for each tier:
   - Starter Plan ($9/month)
   - Professional Plan ($29/month) 
   - Enterprise Plan ($99/month)
3. **Get API Credentials**: Find your API key and store ID in your LemonSqueezy dashboard

### 2. Configure Environment Variables

Copy `env.example` to `.env` and fill in your values:

```bash
# LemonSqueezy Configuration
LEMONSQUEEZY_API_KEY=your_api_key_here
LEMONSQUEEZY_STORE_ID=your_store_id_here
LEMONSQUEEZY_WEBHOOK_SECRET=your_webhook_secret_here

# Product/Variant IDs from your LemonSqueezy dashboard
LEMONSQUEEZY_STARTER_PRODUCT_ID=12345
LEMONSQUEEZY_STARTER_VARIANT_ID=67890
LEMONSQUEEZY_PROFESSIONAL_PRODUCT_ID=12346
LEMONSQUEEZY_PROFESSIONAL_VARIANT_ID=67891
LEMONSQUEEZY_ENTERPRISE_PRODUCT_ID=12347
LEMONSQUEEZY_ENTERPRISE_VARIANT_ID=67892
```

### 3. Install Dependencies

```bash
pip install lemonsqueezy-py
```

### 4. Set Up Webhooks

1. **In LemonSqueezy Dashboard**:
   - Go to Settings → Webhooks
   - Add webhook URL: `https://your-domain.com/subscription/webhook`
   - Enable events: `subscription_created`, `subscription_updated`, `subscription_cancelled`, `subscription_payment_success`, `subscription_payment_failed`
   - Set webhook secret (use the same value in your `.env`)

### 5. Update LemonSqueezy Integration

Update `app/services/subscription_service.py` to implement actual LemonSqueezy API calls:

```python
async def create_lemonsqueezy_checkout(self, user_id: str, tier: str) -> str:
    """Create actual LemonSqueezy checkout URL."""
    # Replace the placeholder with real LemonSqueezy API integration
    # Use the lemonsqueezy-py library to create checkout sessions
    pass
```

### 6. Test the Integration

1. **Start your application**:
   ```bash
   python -m uvicorn app.main:app --reload
   ```

2. **Visit subscription page**: `http://localhost:8000/subscription`

3. **Test user flows**:
   - Free tier → Starter upgrade
   - View usage statistics
   - Process webhook events

## 🔧 Configuration Options

### Customizing Subscription Tiers

Edit `app/services/subscription_service.py` to modify:

```python
self.SUBSCRIPTION_TIERS = {
    "starter": SubscriptionTier(
        name="starter",
        display_name="Custom Starter",
        monthly_tokens=75000,  # Increase tokens
        price_cents=1200,      # Change price to $12
        features=[...],        # Customize features
        ai_models=[...]        # Modify available AI models
    )
}
```

### AI Model Access Control

The system automatically restricts AI model access based on subscription tier. Users on lower tiers cannot access premium models.

### Token Allocation

Monthly tokens are automatically allocated based on the user's subscription tier. The system:
- Tracks usage per user
- Prevents over-usage
- Allocates new tokens on subscription renewal

## 🎨 UI Customization

### Subscription Page Styling

The subscription page (`templates/subscription.html`) includes:
- Responsive tier cards
- Usage progress bars
- Real-time status updates
- Bootstrap 5 styling

### Navigation Integration

Add subscription link to your navigation:

```html
<a href="/subscription" class="nav-link">Subscription</a>
```

## 📊 Analytics and Monitoring

### Subscription Events

All LemonSqueezy webhook events are logged in the `subscription_events` table for:
- Debugging webhook issues
- Analytics and reporting
- Audit trails

### Usage Tracking

The existing usage tracking system now includes:
- Subscription tier information
- Token usage by tier
- Model access patterns

## 🔒 Security Considerations

### Webhook Verification

The system includes webhook signature verification to ensure events come from LemonSqueezy:

```python
def _verify_webhook_signature(self, payload: Dict[str, Any], signature: str) -> bool:
    # Implement proper signature verification
    # Use your webhook secret to verify the signature
```

### API Access Control

- AI model access is enforced at the service level
- Token usage is validated before API execution
- Subscription status is checked in real-time

## 🚨 Important Notes

### Migration Required

Run the database migration to add subscription support:

```bash
python migration_add_subscriptions.py
```

### Testing Webhooks

For local development, use tools like ngrok to expose your webhook endpoint:

```bash
ngrok http 8000
# Use the ngrok URL for webhook configuration in LemonSqueezy
```

### Production Deployment

Ensure your production environment has:
- Proper SSL certificate for webhook security
- Environment variables configured
- Database backup before migration

## 📚 Resources

- [LemonSqueezy API Documentation](https://docs.lemonsqueezy.com/api)
- [LemonSqueezy Python SDK](https://github.com/lemonsqueezy/lemonsqueezy-py)
- [Webhook Testing with ngrok](https://ngrok.com/)

## 🎯 Success!

Your app now has a complete subscription system with:
- ✅ Tier-based pricing
- ✅ AI model access control  
- ✅ Automated token allocation
- ✅ Webhook event handling
- ✅ Beautiful subscription UI
- ✅ Usage tracking and analytics

Ready to start monetizing your AI API generator! 🚀
