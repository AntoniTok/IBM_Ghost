"""
Email Service for Granite Ghost - Elderly Companion Device
Fetches recent emails via IMAP and writes output to emails.json
"""
import imaplib
import email
import json
from email.header import decode_header
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any

from config import (
    EMAIL_ADDRESS, EMAIL_PASSWORD, IMAP_SERVER, IMAP_PORT,
    EMAIL_MAX_FETCH, EMAIL_LOOKBACK_DAYS, EMAIL_OUTPUT,
)


def decode_mime_words(s: str) -> str:
    if not s:
        return ""
    decoded_parts = []
    for part, encoding in decode_header(s):
        if isinstance(part, bytes):
            decoded_parts.append(part.decode(encoding or "utf-8", errors="ignore"))
        else:
            decoded_parts.append(part)
    return "".join(decoded_parts)


def get_email_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")
                        break
                except Exception:
                    continue
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode("utf-8", errors="ignore")
        except Exception:
            body = ""

    body = " ".join(body.replace("\r\n", " ").replace("\r", " ").replace("\n", " ").split())
    if len(body) > 200:
        body = body[:200].strip() + "..."
    return body.strip()


def fetch_recent_emails() -> List[Dict[str, Any]]:
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        raise ValueError("EMAIL_ADDRESS and EMAIL_PASSWORD must be set in config.py")

    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)

    try:
        mail.select("INBOX")

        if EMAIL_LOOKBACK_DAYS > 0:
            since_date = (datetime.now() - timedelta(days=EMAIL_LOOKBACK_DAYS)).strftime("%d-%b-%Y")
            _, messages = mail.search(None, f'SINCE "{since_date}"')
        else:
            _, messages = mail.search(None, "ALL")

        message_ids = messages[0].split()
        recent_ids = list(reversed(
            message_ids[-EMAIL_MAX_FETCH:] if len(message_ids) > EMAIL_MAX_FETCH else message_ids
        ))

        _, unseen_data = mail.search(None, "UNSEEN")
        unseen_ids = set(unseen_data[0].split())

        emails = []
        for msg_id in recent_ids:
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            emails.append({
                "id":      msg_id.decode(),
                "from":    decode_mime_words(msg.get("From", "")),
                "subject": decode_mime_words(msg.get("Subject", "(no subject)")),
                "date":    msg.get("Date", ""),
                "snippet": get_email_body(msg),
                "unread":  msg_id in unseen_ids,
            })

        return emails

    finally:
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass


def format_email_summary(emails: List[Dict[str, Any]]) -> str:
    if not emails:
        return "You have no recent emails."

    unread_count = sum(1 for e in emails if e["unread"])

    if unread_count == 0:
        intro = f"You have {len(emails)} recent emails, all read."
    elif unread_count == 1:
        intro = f"You have {len(emails)} recent emails, with 1 unread."
    else:
        intro = f"You have {len(emails)} recent emails, with {unread_count} unread."

    descriptions = []
    for e in emails[:3]:
        sender  = e["from"].split("<")[0].strip() or e["from"]
        subject = e["subject"] or "no subject"
        status  = "unread" if e["unread"] else "read"
        descriptions.append(f"From {sender}, subject: {subject}, {status}")

    if len(emails) > 3:
        descriptions.append(f"and {len(emails) - 3} more")

    return intro + " " + ". ".join(descriptions) + "."


def main():
    try:
        emails  = fetch_recent_emails()
        summary = format_email_summary(emails)

        output = {
            "service":   "email",
            "status":    "success",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {
                "content": summary,
                "raw_data": {
                    "total_count":  len(emails),
                    "unread_count": sum(1 for e in emails if e["unread"]),
                    "emails": [
                        {
                            "from":    e["from"],
                            "subject": e["subject"],
                            "date":    e["date"],
                            "snippet": e["snippet"],
                            "unread":  e["unread"],
                        }
                        for e in emails
                    ],
                },
            },
            "error": None,
        }

    except Exception as e:
        output = {
            "service":   "email",
            "status":    "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data":      None,
            "error":     str(e),
        }

    EMAIL_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    EMAIL_OUTPUT.write_text(json.dumps(output, indent=2))
    print(f"Done — written to {EMAIL_OUTPUT}")


if __name__ == "__main__":
    main()
