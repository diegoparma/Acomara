# Email Verification & Security System

## Overview

The Acomara sales agent now includes an advanced security feature that automatically verifies prospect emails against "Have I Been Pwned" (HIBP) breach databases. This helps protect both the company and prospects by:

1. Detecting compromised emails early in the sales process
2. Pausing conversations with compromised accounts
3. Alerting administrators for manual follow-up
4. Preventing sales to accounts with known security breaches

## How It Works

### 1. Email Request Timing
After 2-4 turns of natural conversation, the agent will naturally request the prospect's email address:

**Spanish:** "Para poder ayudarte mejor y enviarte detalles, ¿cuál es tu email?"  
**English:** "To send you detailed information, what's your email address?"

### 2. Email Verification Process
Once an email is detected in the conversation:

```
User provides email → Verify against HIBP API → Check result → Action
```

**If email is SAFE:**
- Conversation continues normally
- Email is marked as verified and safe
- `email_safe: true` stored in session variables

**If email is COMPROMISED:**
- Conversation is immediately paused
- Admin receives security alert email
- Prospect receives a holding message
- `conversation_paused: true` and `email_compromised: true` stored in session

**If verification fails (API error/rate limit):**
- System logs the failure
- Conversation continues with a note to retry verification
- `email_check_failed: true` stored in session

### 3. Session Variables Tracking

After email verification, the following variables are stored in the session:

```python
{
    "conversation_turn_count": 4,              # Current turn number
    "email_verified": true,                    # Email was checked
    "email_checked_at_ts": 1234567890,         # When it was checked
    "email_safe": true,                        # Email is not compromised
    # OR
    "email_compromised": true,                 # Email is compromised
    "conversation_paused": true,               # Conversation paused
    "pause_reason": "Email has been found in a security breach database",
    "paused_email": "prospect@example.com",    # Paused due to this email
    "compromised_email_alert_sent": true,      # Admin was notified
    "compromised_email_alert_sent_ts": 1234567890,
}
```

## Configuration

### Enable/Disable Feature

Add to `.env`:

```bash
# Email verification via Have I Been Pwned API (default: true)
EMAIL_VERIFICATION_ENABLED=true
```

Set to `false` to completely disable the feature.

### Admin Alert Configuration

The same email infrastructure used for human handoff is used for compromised email alerts:

**Using Resend (recommended):**
```bash
HANDOFF_EMAIL_PROVIDER=resend
HANDOFF_EMAIL_API_KEY=your_resend_api_key
HANDOFF_EMAIL_FROM=noreply@acomara.com
HANDOFF_EMAIL_TO=admin@acomara.com
```

**Using SMTP:**
```bash
HANDOFF_EMAIL_PROVIDER=smtp
HANDOFF_SMTP_HOST=smtp.gmail.com
HANDOFF_SMTP_PORT=587
HANDOFF_SMTP_USER=your_email@gmail.com
HANDOFF_SMTP_PASSWORD=your_app_password
HANDOFF_SMTP_STARTTLS=true
HANDOFF_EMAIL_FROM=noreply@acomara.com
HANDOFF_EMAIL_TO=admin@acomara.com
```

## API Response Format

The webhook response now includes email verification status:

```json
{
  "ok": true,
  "conversation_id": "conv-123",
  "reply": "Thank you for your interest...",
  "email_verification": {
    "enabled": true,
    "compromised": false,
    "alert_sent": false,
    "conversation_paused": false
  },
  "human_handoff_email": {
    "requested": false,
    "attempted": false,
    "sent": false
  }
}
```

### When Email is Compromised:

```json
{
  "ok": true,
  "conversation_id": "conv-123",
  "reply": "Thank you for your interest. We detected a security concern with your email. A member of our team will contact you shortly...",
  "email_verification": {
    "enabled": true,
    "compromised": true,
    "alert_sent": true,
    "conversation_paused": true
  }
}
```

## Session Events

When email verification occurs, events are appended to the session:

### Safe Email:
```python
{
    "event_type": "inbound_message",
    "event_data": {"text": "my email is john@example.com", ...}
}
```

### Compromised Email:
```python
{
    "event_type": "compromised_email_alert",
    "event_data": {
        "email": "john@breached.com",
        "status": "sent_to_admin",
        "reason": "Email found in security breach database"
    }
}
```

## Have I Been Pwned API

### How It Works

The system uses HIBP's **k-anonymity** method:

1. Email is hashed with SHA-1
2. First 5 characters of hash are sent to HIBP API
3. HIBP returns all hashes starting with those 5 characters (partial match)
4. System compares full hash locally (privacy-preserving)
5. If match found, email is compromised

### Rate Limiting

- Default timeout: 10 seconds
- HIBP API limits: ~0.5 requests per second per IP
- If rate limited (HTTP 429), verification fails gracefully
- Conversation continues with a flag to retry later

### API Endpoint

```
GET https://api.pwnedpasswords.com/range/{FIRST5CHARS}
Response: List of matching hash suffixes with breach counts
```

## Email Extraction Logic

The system uses a simple regex to extract emails from user messages:

```python
pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
```

Supported formats:
- ✅ `john@example.com`
- ✅ `john.doe@company.co.uk`
- ✅ `user+tag@domain.com`
- ✅ Plain text in message like "My email is john@example.com"

## Workflow Example

```
Turn 1: User asks about expedition
  → Agent responds with info, asks qualifying question

Turn 2: User answers about experience level  
  → Agent responds with route recommendation

Turn 3: User asks about pricing
  → Agent explains pricing model

Turn 4: User says "I'm interested, here's my email: john@breached.com"
  → System detects email john@breached.com
  → Queries HIBP API
  → Result: Email found in 3 breaches
  → Conversation PAUSED
  → Reply: "Security concern detected..."
  → Admin receives alert email
  → Admin manually contacts prospect
```

## Admin Alert Email Example

```
Subject: [ACOMARA SECURITY] Email comprometido detectado - conv-abc123

⚠️ ALERTA DE SEGURIDAD

Se detectó que el email proporcionado por un prospecto está en una base de datos de breaches.

Email comprometido: john@breached.com
conversation_id: conv-abc123
organization_id: org-123
contact_id: contact-456
contact_address: +15551234567
channel: whatsapp

La conversación ha sido PAUSADA automáticamente.
El prospecto deberá ser contactado por un asesor humano.

Último mensaje del cliente: my email is john@breached.com
```

## Security Considerations

### Privacy
- Email is hashed before sending to HIBP - your email is never shared in plain text
- Only hash prefixes are transmitted (k-anonymity pattern)
- HIBP API is public and well-trusted by security community

### Rate Limiting
- Don't check same email repeatedly (stored in session as `email_verified`)
- System respects API rate limits gracefully
- Failed checks don't block conversation, just flag for retry

### False Positives
- False positives are rare but possible
- Admins should manually verify before completely rejecting prospect
- Email may have been in a breach but subsequently secured

## Debugging

### Check Session Variables

Query session agent API:
```bash
curl https://session-agent-url/v1/sessions/{conversation_id}
```

Look for:
- `email_verified: true`
- `email_compromised: true` 
- `conversation_paused: true`
- Timestamps of when checks occurred

### Enable Logging

The orchestrator logs all email verification:
```
INFO: Email extracted: john@example.com
INFO: Email verified: john@example.com - is_pwned=false
WARNING: Email verification failed - check_succeeded=false
WARNING: send_compromised_email_alert exception: ...
```

### Test Email Verification

Use known pwned emails for testing:
```
test@example.com - Known to be in breaches (safe to test)
```

Or test with test API:
```python
from orchestrator.security import check_email_pwned

is_pwned, check_succeeded = check_email_pwned("test@example.com")
# Result: (True, True) - test email is known to be pwned
```

## Future Enhancements

Potential improvements:
1. Manual email verification retry button for admins
2. Email verification whitelisting (skip check for certain domains)
3. Metrics dashboard showing breach detection rate
4. Integration with password strength checkers
5. Support for additional OSINT APIs (leak detection, dark web monitoring)
6. Customizable response messages based on breach type
