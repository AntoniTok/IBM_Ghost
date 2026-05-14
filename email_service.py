"""
Email Service for IBM Ghost - Elderly Companion Device
Uses IMAP to fetch recent emails (works with Gmail, Outlook, etc.)
"""
import os
import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
PORT = int(os.getenv("EMAIL_SERVICE_PORT", "5002"))
MAX_EMAILS = int(os.getenv("MAX_EMAILS", "5"))
CACHE_TTL = int(os.getenv("CACHE_TTL", "300"))  # 5 minutes

# Email credentials (from environment or .env file)
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# Simple in-memory cache
_cache = {}
_cache_timestamp = None

# Create router (can be included in main app)
router = APIRouter(prefix="/email", tags=["email"])


def decode_mime_words(s: str) -> str:
    """Decode MIME encoded-word strings"""
    if not s:
        return ""
    
    decoded_parts = []
    for part, encoding in decode_header(s):
        if isinstance(part, bytes):
            decoded_parts.append(
                part.decode(encoding or 'utf-8', errors='ignore')
            )
        else:
            decoded_parts.append(part)
    
    return ''.join(decoded_parts)


def get_email_body(msg) -> str:
    """Extract plain text body from email message"""
    body = ""
    
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                        break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode('utf-8', errors='ignore')
        except Exception:
            body = ""
    
    # Clean up whitespace and line breaks
    body = body.replace('\r\n', ' ').replace('\r', ' ').replace('\n', ' ')
    
    # Remove multiple spaces
    body = ' '.join(body.split())
    
    # Truncate to first 200 characters for snippet
    if len(body) > 200:
        body = body[:200].strip() + "..."
    
    return body.strip()


def connect_to_imap() -> imaplib.IMAP4_SSL:
    """Connect to IMAP server and login"""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        raise ValueError(
            "Email credentials not configured. "
            "Set EMAIL_ADDRESS and EMAIL_PASSWORD in .env file"
        )
    
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        return mail
    except imaplib.IMAP4.error as e:
        raise ConnectionError(f"IMAP login failed: {str(e)}")
    except Exception as e:
        raise ConnectionError(f"Could not connect to IMAP server: {str(e)}")


def fetch_recent_emails(max_results: int = MAX_EMAILS) -> List[Dict[str, Any]]:
    """Fetch recent emails via IMAP"""
    global _cache, _cache_timestamp
    
    # Check cache
    if _cache and _cache_timestamp:
        age = (datetime.now() - _cache_timestamp).total_seconds()
        if age < CACHE_TTL:
            return _cache
    
    mail = connect_to_imap()
    
    try:
        # Select inbox
        mail.select('INBOX')
        
        # Search for all emails
        status, messages = mail.search(None, 'ALL')
        
        if status != 'OK':
            raise Exception("Failed to search emails")
        
        # Get message IDs
        message_ids = messages[0].split()
        
        # Get the most recent emails (last N messages)
        recent_ids = message_ids[-max_results:] if len(message_ids) > max_results else message_ids
        recent_ids = reversed(recent_ids)  # Most recent first
        
        emails = []
        
        for msg_id in recent_ids:
            # Fetch email
            status, msg_data = mail.fetch(msg_id, '(RFC822 FLAGS)')
            
            if status != 'OK':
                continue
            
            # Parse email
            raw_email = msg_data[0][1]
            msg = email.message_from_bytes(raw_email)
            
            # Get flags to check if unread
            flags = msg_data[1].decode() if len(msg_data) > 1 else ""
            is_unread = '\\Seen' not in flags
            
            # Extract email data
            from_header = decode_mime_words(msg.get('From', ''))
            subject = decode_mime_words(msg.get('Subject', '(no subject)'))
            date_str = msg.get('Date', '')
            snippet = get_email_body(msg)
            
            email_data = {
                'id': msg_id.decode(),
                'from': from_header,
                'subject': subject,
                'date': date_str,
                'snippet': snippet,
                'unread': is_unread
            }
            
            emails.append(email_data)
        
        # Cache results
        _cache = emails
        _cache_timestamp = datetime.now()
        
        return emails
    
    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass


def format_email_summary(emails: List[Dict[str, Any]]) -> str:
    """Create a human-readable summary of emails"""
    if not emails:
        return "You have no recent emails."
    
    unread_count = sum(1 for e in emails if e['unread'])
    
    if unread_count == 0:
        intro = f"You have {len(emails)} recent emails, all read."
    elif unread_count == 1:
        intro = f"You have {len(emails)} recent emails, with 1 unread."
    else:
        intro = f"You have {len(emails)} recent emails, with {unread_count} unread."
    
    # Describe first 3 emails
    descriptions = []
    for email_item in emails[:3]:
        # Extract sender name (before email address if present)
        sender = email_item['from']
        if '<' in sender:
            sender = sender.split('<')[0].strip()
        if not sender:
            sender = email_item['from']
        
        subject = email_item['subject'] if email_item['subject'] else "no subject"
        status = "unread" if email_item['unread'] else "read"
        
        descriptions.append(
            f"From {sender}, subject: {subject}, {status}"
        )
    
    if len(emails) > 3:
        descriptions.append(f"and {len(emails) - 3} more")
    
    return intro + " " + ". ".join(descriptions) + "."


@router.get("/health")
def health():
    """Health check endpoint"""
    try:
        # Try to connect
        mail = connect_to_imap()
        mail.logout()
        return {
            "status": "healthy",
            "service": "email",
            "provider": f"IMAP ({IMAP_SERVER})"
        }
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Email service unavailable: {str(e)}"
        )


@router.get("/")
def get_emails(max_results: int = MAX_EMAILS):
    """
    Get recent emails from inbox via IMAP.
    
    Args:
        max_results: Number of emails to fetch (default: 5, max: 20)
    
    Returns:
        Standardized email response with human-readable content
    """
    
    # Validate max_results
    max_results = min(max(1, max_results), 20)
    
    try:
        # Fetch emails
        emails = fetch_recent_emails(max_results)
        
        # Create standardized response
        return {
            "service": "email",
            "status": "success",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "data": {
                "content": format_email_summary(emails),
                "raw_data": {
                    "total_count": len(emails),
                    "unread_count": sum(1 for e in emails if e['unread']),
                    "emails": [
                        {
                            "from": e['from'],
                            "subject": e['subject'],
                            "date": e['date'],
                            "snippet": e['snippet'],
                            "unread": e['unread']
                        }
                        for e in emails
                    ]
                }
            },
            "metadata": {
                "cache_ttl": CACHE_TTL,
                "priority": "normal",
                "provider": f"IMAP ({IMAP_SERVER})"
            },
            "error": None
        }
        
    except ValueError as e:
        # Configuration error
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    
    except ConnectionError as e:
        # IMAP connection error
        raise HTTPException(
            status_code=503,
            detail=str(e)
        )
    
    except Exception as e:
        # Other errors
        raise HTTPException(
            status_code=500,
            detail=f"Email service error: {str(e)}"
        )


if __name__ == "__main__":
    # For standalone running, create a FastAPI app
    from fastapi import FastAPI
    import uvicorn
    
    app = FastAPI(title="Email Service")
    app.include_router(router)
    
    print("=" * 60)
    print("📧  IBM Ghost - Email Service (IMAP)")
    print("=" * 60)
    print(f"📬 Provider: IMAP ({IMAP_SERVER})")
    print(f"📧 Email: {EMAIL_ADDRESS if EMAIL_ADDRESS else 'NOT CONFIGURED'}")
    print(f"🔌 Port: {PORT}")
    print(f"📊 Max emails: {MAX_EMAILS}")
    print(f"⏱️  Cache TTL: {CACHE_TTL} seconds")
    print(f"📚 API Docs: http://localhost:{PORT}/docs")
    print("=" * 60)
    
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        print("\n⚠️  WARNING: Email credentials not configured!")
        print("Set EMAIL_ADDRESS and EMAIL_PASSWORD in .env file")
        print("=" * 60)
    
    print()
    
    uvicorn.run(app, host="0.0.0.0", port=PORT)

# Made with Bob