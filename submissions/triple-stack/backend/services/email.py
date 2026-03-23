"""
Email Service for NexDesk.

Provides email-to-ticket and notification functionality:
- Parse incoming emails and create tickets
- Send auto-reply confirmations
- Send ticket update notifications
- Reply to tickets via email
- Sync with IMAP inbox for incoming emails

Supports:
- SMTP for sending emails
- IMAP for receiving emails
- HTML and plain text emails
- Attachments handling
- Email threading (In-Reply-To, References headers)
"""

import os
import re
import uuid
import smtplib
import imaplib
import email
import email.header
import email.utils
from email.message import Message
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from email.utils import parseaddr, formataddr, make_msgid
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any, Tuple
from dataclasses import dataclass, field
import logging

try:
    import html2text
except ImportError:  # pragma: no cover - optional dependency
    html2text = None

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================


@dataclass
class EmailConfig:
    """Email service configuration."""

    # SMTP settings (sending)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True

    # IMAP settings (receiving)
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""
    imap_use_ssl: bool = True

    # From address
    from_address: str = ""
    from_name: str = "NexDesk Support"

    # Auto-reply settings
    auto_reply_enabled: bool = True
    auto_reply_template: str = """
Hello {customer_name},

Thank you for contacting NexDesk Support. We have received your request and created ticket #{ticket_id}.

Subject: {ticket_title}

Our team will review your request and respond as soon as possible. Based on the priority of your issue, you can expect a response within {sla_hours} hours.

You can track your ticket status at: {portal_url}/tickets/{ticket_id}

Best regards,
NexDesk Support Team
"""

    # Portal URL for tracking links
    portal_url: str = "https://support.nexdesk.com"

    @classmethod
    def from_env(cls) -> "EmailConfig":
        """Load configuration from environment variables."""
        return cls(
            smtp_host=os.getenv("SMTP_HOST", ""),
            smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_username=os.getenv("SMTP_USERNAME", ""),
            smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            imap_host=os.getenv("IMAP_HOST", ""),
            imap_port=int(os.getenv("IMAP_PORT", "993")),
            imap_username=os.getenv("IMAP_USERNAME", ""),
            imap_password=os.getenv("IMAP_PASSWORD", ""),
            imap_use_ssl=os.getenv("IMAP_USE_SSL", "true").lower() == "true",
            from_address=os.getenv("EMAIL_FROM_ADDRESS", "support@nexdesk.com"),
            from_name=os.getenv("EMAIL_FROM_NAME", "NexDesk Support"),
            auto_reply_enabled=os.getenv("EMAIL_AUTO_REPLY", "true").lower() == "true",
            portal_url=os.getenv("PORTAL_URL", "https://support.nexdesk.com"),
        )


@dataclass
class ParsedEmail:
    """Parsed email data."""

    message_id: str
    from_address: str
    from_name: str
    to_address: str
    subject: str
    body_text: str
    body_html: Optional[str]
    received_at: datetime
    in_reply_to: Optional[str] = None
    references: List[str] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)

    @property
    def is_reply(self) -> bool:
        """Check if this is a reply to an existing ticket."""
        return bool(self.in_reply_to or self.references)

    def extract_ticket_id(self) -> Optional[str]:
        """Try to extract ticket ID from subject or references."""
        # Check subject for ticket ID pattern: [Ticket #abc123] or #abc123
        patterns = [
            r"\[Ticket\s*#?([a-zA-Z0-9-]+)\]",
            r"#([a-zA-Z0-9-]{8,})",
            r"ticket[:\s]+([a-zA-Z0-9-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, self.subject, re.IGNORECASE)
            if match:
                return match.group(1)

        return None


# =============================================================================
# Email Service
# =============================================================================


class EmailService:
    """
    Email service for sending and receiving emails.

    Handles:
    - Sending ticket notifications
    - Auto-replies for new tickets
    - Parsing incoming emails
    - Creating tickets from emails
    """

    def __init__(self, config: Optional[EmailConfig] = None):
        self.config = config or EmailConfig.from_env()
        self._smtp_connection: Optional[smtplib.SMTP] = None
        self._imap_connection: Optional[imaplib.IMAP4_SSL] = None

    # =========================================================================
    # SMTP (Sending)
    # =========================================================================

    def _get_smtp_connection(self) -> smtplib.SMTP:
        """Get or create SMTP connection."""
        if not self.config.smtp_host:
            raise ValueError("SMTP host not configured")

        try:
            if self.config.smtp_use_tls:
                smtp = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)
                smtp.starttls()
            else:
                smtp = smtplib.SMTP(self.config.smtp_host, self.config.smtp_port)

            if self.config.smtp_username and self.config.smtp_password:
                smtp.login(self.config.smtp_username, self.config.smtp_password)

            return smtp

        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            raise

    def send_email(
        self,
        to_address: str,
        subject: str,
        body_text: str,
        body_html: Optional[str] = None,
        reply_to: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        references: Optional[List[str]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Send an email.

        Args:
            to_address: Recipient email address
            subject: Email subject
            body_text: Plain text body
            body_html: Optional HTML body
            reply_to: Optional reply-to address
            in_reply_to: Optional In-Reply-To header for threading
            references: Optional References header for threading
            attachments: Optional list of attachments

        Returns:
            Tuple of (success, message_id)
        """
        try:
            # Create message
            if body_html:
                msg = MIMEMultipart("alternative")
                msg.attach(MIMEText(body_text, "plain"))
                msg.attach(MIMEText(body_html, "html"))
            else:
                msg = MIMEMultipart()
                msg.attach(MIMEText(body_text, "plain"))

            # Set headers
            message_id = make_msgid(domain=self.config.from_address.split("@")[-1])
            msg["Message-ID"] = message_id
            msg["From"] = formataddr((self.config.from_name, self.config.from_address))
            msg["To"] = to_address
            msg["Subject"] = subject
            msg["Date"] = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S +0000")

            if reply_to:
                msg["Reply-To"] = reply_to

            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to

            if references:
                msg["References"] = " ".join(references)

            # Add attachments
            if attachments:
                for attachment in attachments:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.get("content", b""))
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f"attachment; filename={attachment.get('filename', 'attachment')}",
                    )
                    msg.attach(part)

            # Send
            with self._get_smtp_connection() as smtp:
                smtp.sendmail(self.config.from_address, [to_address], msg.as_string())

            logger.info(f"Email sent to {to_address}: {subject}")
            return True, message_id

        except Exception as e:
            logger.error(f"Failed to send email to {to_address}: {e}")
            return False, None

    def send_auto_reply(
        self,
        to_address: str,
        customer_name: str,
        ticket_id: str,
        ticket_title: str,
        sla_hours: int = 24,
    ) -> Tuple[bool, Optional[str]]:
        """
        Send an auto-reply for a new ticket.

        Args:
            to_address: Customer email
            customer_name: Customer name
            ticket_id: Created ticket ID
            ticket_title: Ticket title/subject
            sla_hours: Expected response time

        Returns:
            Tuple of (success, message_id)
        """
        if not self.config.auto_reply_enabled:
            return False, None

        # Format the template
        body_text = self.config.auto_reply_template.format(
            customer_name=customer_name or "Valued Customer",
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            sla_hours=sla_hours,
            portal_url=self.config.portal_url,
        )

        subject = f"[Ticket #{ticket_id}] {ticket_title} - Request Received"

        return self.send_email(
            to_address=to_address,
            subject=subject,
            body_text=body_text,
        )

    def send_ticket_update(
        self,
        to_address: str,
        ticket_id: str,
        ticket_title: str,
        update_type: str,
        update_message: str,
        original_message_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Send a ticket update notification.

        Args:
            to_address: Customer email
            ticket_id: Ticket ID
            ticket_title: Ticket title
            update_type: Type of update (e.g., "status_change", "new_reply")
            update_message: The update content
            original_message_id: Original email message ID for threading

        Returns:
            Tuple of (success, message_id)
        """
        subject = f"[Ticket #{ticket_id}] {ticket_title}"

        body_text = f"""
Hello,

There is an update on your support ticket #{ticket_id}:

{update_message}

---
You can view the full ticket at: {self.config.portal_url}/tickets/{ticket_id}

Best regards,
NexDesk Support Team
"""

        references = [original_message_id] if original_message_id else None

        return self.send_email(
            to_address=to_address,
            subject=subject,
            body_text=body_text,
            in_reply_to=original_message_id,
            references=references,
        )

    # =========================================================================
    # IMAP (Receiving)
    # =========================================================================

    def _get_imap_connection(self) -> imaplib.IMAP4:
        """Get or create IMAP connection."""
        if not self.config.imap_host:
            raise ValueError("IMAP host not configured")

        try:
            if self.config.imap_use_ssl:
                imap = imaplib.IMAP4_SSL(self.config.imap_host, self.config.imap_port)
            else:
                imap = imaplib.IMAP4(self.config.imap_host, self.config.imap_port)

            imap.login(self.config.imap_username, self.config.imap_password)
            return imap

        except Exception as e:
            logger.error(f"Failed to connect to IMAP server: {e}")
            raise

    def fetch_new_emails(
        self,
        folder: str = "INBOX",
        since: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[ParsedEmail]:
        """
        Fetch new emails from the inbox.

        Args:
            folder: IMAP folder to fetch from
            since: Only fetch emails since this datetime
            limit: Maximum number of emails to fetch

        Returns:
            List of parsed emails
        """
        emails = []

        try:
            imap = self._get_imap_connection()
            imap.select(folder)

            # Build search criteria
            search_criteria = ["UNSEEN"]
            if since:
                date_str = since.strftime("%d-%b-%Y")
                search_criteria.append(f'SINCE "{date_str}"')

            # Search for emails
            _, message_numbers = imap.search(None, *search_criteria)

            if not message_numbers[0]:
                return []

            # Fetch emails
            for num in message_numbers[0].split()[-limit:]:
                _, msg_data = imap.fetch(num, "(RFC822)")

                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        parsed = self._parse_email(msg)
                        if parsed:
                            emails.append(parsed)

            imap.close()
            imap.logout()

        except Exception as e:
            logger.error(f"Failed to fetch emails: {e}")

        return emails

    def _parse_email(self, msg: Message) -> Optional[ParsedEmail]:
        """Parse an email message into a ParsedEmail object."""
        try:
            # Extract headers
            message_id = msg.get("Message-ID", "")
            from_header = msg.get("From", "")
            from_name, from_address = parseaddr(from_header)
            to_address = parseaddr(msg.get("To", ""))[1]
            subject = msg.get("Subject", "").strip()

            # Decode subject if needed
            if subject.startswith("=?"):
                decoded = email.header.decode_header(subject)
                subject = "".join(
                    part.decode(encoding or "utf-8")
                    if isinstance(part, bytes)
                    else part
                    for part, encoding in decoded
                )

            # Get date
            date_str = msg.get("Date", "")
            try:
                received_at = email.utils.parsedate_to_datetime(date_str)
            except Exception:
                received_at = datetime.utcnow()

            # Threading headers
            in_reply_to = msg.get("In-Reply-To")
            references_str = msg.get("References", "")
            references = references_str.split() if references_str else []

            # Extract body
            body_text = ""
            body_html = None
            attachments = []

            if msg.is_multipart():
                for part in msg.walk():
                    content_type = part.get_content_type()
                    content_disposition = str(part.get("Content-Disposition", ""))

                    if "attachment" in content_disposition:
                        # Handle attachment
                        filename = part.get_filename() or "attachment"
                        attachments.append(
                            {
                                "filename": filename,
                                "content_type": content_type,
                                "size": len(part.get_payload(decode=True) or b""),
                            }
                        )
                    elif content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            if isinstance(payload, bytes):
                                body_text = payload.decode("utf-8", errors="ignore")
                            else:
                                body_text = str(payload)
                    elif content_type == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            if isinstance(payload, bytes):
                                body_html = payload.decode("utf-8", errors="ignore")
                            else:
                                body_html = str(payload)
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    if isinstance(payload, bytes):
                        body_text = payload.decode("utf-8", errors="ignore")
                    else:
                        body_text = str(payload)

            # Convert HTML to text if no plain text available
            if not body_text and body_html and html2text:
                h = html2text.HTML2Text()
                h.ignore_links = False
                body_text = h.handle(body_html)
            elif not body_text and body_html:
                body_text = body_html

            return ParsedEmail(
                message_id=message_id,
                from_address=from_address,
                from_name=from_name,
                to_address=to_address,
                subject=subject,
                body_text=body_text.strip(),
                body_html=body_html,
                received_at=received_at,
                in_reply_to=in_reply_to,
                references=references,
                attachments=attachments,
            )

        except Exception as e:
            logger.error(f"Failed to parse email: {e}")
            return None

    # =========================================================================
    # Ticket Integration
    # =========================================================================

    def create_ticket_from_email(
        self,
        parsed_email: ParsedEmail,
        db: Session,
    ) -> Dict[str, Any]:
        """
        Create a ticket from a parsed email.

        Args:
            parsed_email: The parsed email
            db: Database session

        Returns:
            Created ticket info
        """
        from database.models import Ticket, AiAuditLog
        from ai.classifier import classify_ticket
        from ai.triage import triage_engine

        # Check if this is a reply to existing ticket
        existing_ticket_id = parsed_email.extract_ticket_id()

        if existing_ticket_id:
            # This is a reply - add as comment to existing ticket
            return self._add_reply_to_ticket(parsed_email, existing_ticket_id, db)

        # Create new ticket
        try:
            # Classify the ticket
            classification = classify_ticket(
                title=parsed_email.subject,
                description=parsed_email.body_text,
            )

            # Triage for priority
            triage_result = triage_engine.analyze_ticket(
                title=parsed_email.subject,
                description=parsed_email.body_text,
                user_id=parsed_email.from_address,
                db=db,
            )

            # Create ticket
            ticket = Ticket(
                id=str(uuid.uuid4()),
                title=parsed_email.subject or "Email Support Request",
                description=parsed_email.body_text,
                category=classification.get("category", "other"),
                priority=triage_result.priority,
                status="open",
                user_id=parsed_email.from_address,
                ai_confidence=classification.get("confidence", 0.0),
                sentiment=classification.get("sentiment", "neutral"),
                sla_hours=triage_result.sla_hours,
            )

            db.add(ticket)

            # Log to audit
            audit_log = AiAuditLog(
                ticket_id=ticket.id,
                action_type="email_ticket_created",
                input_text=f"Email from {parsed_email.from_address}: {parsed_email.subject}",
                ai_output={
                    "category": classification.get("category"),
                    "priority": triage_result.priority,
                    "triage_score": triage_result.score,
                },
                confidence=classification.get("confidence", 0.0),
                model_used="email_classifier",
            )
            db.add(audit_log)
            db.commit()

            # Send auto-reply
            auto_reply_sent = False
            if self.config.auto_reply_enabled:
                success, _ = self.send_auto_reply(
                    to_address=parsed_email.from_address,
                    customer_name=parsed_email.from_name,
                    ticket_id=str(ticket.id),
                    ticket_title=str(ticket.title),
                    sla_hours=triage_result.sla_hours,
                )
                auto_reply_sent = success

            return {
                "success": True,
                "ticket_id": ticket.id,
                "title": ticket.title,
                "category": ticket.category,
                "priority": ticket.priority,
                "from_address": parsed_email.from_address,
                "auto_reply_sent": auto_reply_sent,
                "confidence": classification.get("confidence", 0.0),
            }

        except Exception as e:
            logger.error(f"Failed to create ticket from email: {e}")
            db.rollback()
            return {
                "success": False,
                "error": str(e),
            }

    def _add_reply_to_ticket(
        self,
        parsed_email: ParsedEmail,
        ticket_id: str,
        db: Session,
    ) -> Dict[str, Any]:
        """Add an email reply as a comment to an existing ticket."""
        from database.models import Ticket

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()

        if not ticket:
            # Ticket not found - create new one
            logger.warning(
                f"Ticket {ticket_id} not found for reply, creating new ticket"
            )
            return self.create_ticket_from_email(
                ParsedEmail(
                    message_id=parsed_email.message_id,
                    from_address=parsed_email.from_address,
                    from_name=parsed_email.from_name,
                    to_address=parsed_email.to_address,
                    subject=parsed_email.subject.replace(
                        f"Re: [Ticket #{ticket_id}]", ""
                    ).strip(),
                    body_text=parsed_email.body_text,
                    body_html=parsed_email.body_html,
                    received_at=parsed_email.received_at,
                ),
                db,
            )

        # Update ticket - in production, add to a comments table
        # For now, append to description
        ticket.description = (
            f"{ticket.description}\n\n---\nReply from {parsed_email.from_address}"
            f" ({parsed_email.received_at}):\n{parsed_email.body_text}"
        )
        ticket.updated_at = datetime.utcnow()

        # Reopen if closed
        if str(ticket.status) in [
            "closed",
            "resolved",
            "TicketStatus.closed",
            "TicketStatus.resolved",
        ]:
            ticket.status = "open"

        db.commit()

        return {
            "success": True,
            "ticket_id": ticket_id,
            "action": "reply_added",
            "from_address": parsed_email.from_address,
        }

    async def sync_inbox(self, db: Session) -> Dict[str, Any]:
        """
        Sync the inbox and process new emails.

        Should be called periodically (e.g., every 5 minutes).
        """
        results = {
            "processed": 0,
            "tickets_created": 0,
            "replies_added": 0,
            "errors": 0,
        }

        try:
            emails = self.fetch_new_emails(limit=50)
            results["processed"] = len(emails)

            for parsed_email in emails:
                try:
                    result = self.create_ticket_from_email(parsed_email, db)

                    if result.get("success"):
                        if result.get("action") == "reply_added":
                            results["replies_added"] += 1
                        else:
                            results["tickets_created"] += 1
                    else:
                        results["errors"] += 1

                except Exception as e:
                    logger.error(f"Error processing email: {e}")
                    results["errors"] += 1

        except Exception as e:
            logger.error(f"Inbox sync failed: {e}")
            results["sync_error"] = str(e)

        return results


# =============================================================================
# Global Instance
# =============================================================================

_email_service: Optional[EmailService] = None


def get_email_service() -> EmailService:
    """Get or create the global email service instance."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
