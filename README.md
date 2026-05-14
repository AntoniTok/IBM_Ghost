# Email Service - Quick Start

Fetches recent emails via IMAP. Works with Gmail, Outlook, Yahoo, and any IMAP provider.

## Setup

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Get Gmail App Password
1. Go to https://myaccount.google.com/security
2. Enable 2-Step Verification
3. Go to App Passwords → Mail → Other (IBM Ghost)
4. Copy the 16-character password

### 3. Configure
Create `.env` file:
```bash
EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=your-app-password
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
```

### 4. Run
```bash
python email_service.py
```

## Usage

### Get Emails
```bash
curl http://localhost:5002/email/?max_results=5
```

### Response Format
```json
{
  "service": "email",
  "status": "success",
  "timestamp": "2026-05-14T13:18:24Z",
  "data": {
    "content": "You have 5 recent emails, with 2 unread. From John Smith, subject: Meeting tomorrow, unread...",
    "raw_data": {
      "total_count": 5,
      "unread_count": 2,
      "emails": [
        {
          "from": "John Smith <john@example.com>",
          "subject": "Meeting tomorrow",
          "date": "Wed, 14 May 2026 10:30:00 +0000",
          "snippet": "Hi, just confirming our meeting...",
          "unread": true
        }
      ]
    }
  },
  "metadata": {
    "cache_ttl": 300,
    "priority": "normal",
    "provider": "IMAP (imap.gmail.com)"
  },
  "error": null
}
```

## IMAP Settings

**Gmail:**
```
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
```

**Outlook:**
```
IMAP_SERVER=outlook.office365.com
IMAP_PORT=993
```

**Yahoo:**
```
IMAP_SERVER=imap.mail.yahoo.com
IMAP_PORT=993
```

## Integration

Add to service aggregator:
```python
def _get_email_data(self) -> Dict[str, Any]:
    from email_service import fetch_recent_emails, format_email_summary
    
    emails = fetch_recent_emails(max_results=5)
    summary = format_email_summary(emails)
    
    return {
        'status': 'success',
        'voice_response': summary,
        'data': {'emails': emails},
        'error': None
    }
```

## Troubleshooting

**"Email credentials not configured"**
- Create `.env` file with EMAIL_ADDRESS and EMAIL_PASSWORD

**"IMAP login failed"**
- Use App Password, not regular password
- Enable 2-Step Verification first

**"Could not connect"**
- Check IMAP_SERVER and IMAP_PORT
- Verify internet connection