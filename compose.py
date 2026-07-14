"""Message building helpers for Gmail CLI send/reply."""

import argparse
import base64
import mimetypes
import os
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

# Either shape a composed message can take: plain text, or text plus attachments.
Message = MIMEText | MIMEMultipart

# Gmail refuses to send a message larger than this, however it was submitted.
MAX_MESSAGE_BYTES = 25 * 1024 * 1024


def attachment_errors(attachments: list[str] | None) -> list[str]:
    """Return a readable problem for each attachment that cannot be sent."""
    errors = []
    for filepath in attachments or []:
        path = Path(filepath)
        if not path.exists():
            errors.append(f'Attachment not found: {filepath}')
        elif path.is_dir():
            errors.append(f'Attachment is a directory: {filepath}')
        elif not os.access(path, os.R_OK):
            errors.append(f'Attachment is not readable: {filepath}')
    return errors


def oversize_error(message: Message) -> str | None:
    """Return an error if the message exceeds what Gmail will send.

    Measure the RFC822 message, not the base64url `raw` field we transmit:
    attachments are already base64-encoded inside the message, so `raw` is
    roughly 1.8x the original file and would over-report the real size.
    """
    size = len(message.as_bytes())
    if size <= MAX_MESSAGE_BYTES:
        return None

    return (
        f'Message is {size / 1024 / 1024:.1f}MB, over Gmail\'s '
        f'{MAX_MESSAGE_BYTES // 1024 // 1024}MB limit. Attachments are base64-encoded, '
        'which adds roughly a third to their size.'
    )


def get_body_content(args: argparse.Namespace) -> str | None:
    """Get message body from args (--body or --file)."""
    if args.file:
        return Path(args.file).read_text()
    if args.body:
        return args.body
    return None


def set_optional_recipients(message: Message, args: argparse.Namespace) -> None:
    """Set CC and BCC headers on a message if provided in args."""
    if args.cc:
        message['Cc'] = ', '.join(args.cc)
    if args.bcc:
        message['Bcc'] = ', '.join(args.bcc)


def build_message(body: str, attachments: list[str] | None) -> Message:
    """Build a MIME message, with attachments if provided."""
    if not attachments:
        return MIMEText(body)

    msg = MIMEMultipart()
    msg.attach(MIMEText(body))

    for filepath in attachments:
        path = Path(filepath)
        content_type, _ = mimetypes.guess_type(str(path))
        if content_type is None:
            content_type = 'application/octet-stream'
        maintype, subtype = content_type.split('/', 1)

        part = MIMEBase(maintype, subtype)
        part.set_payload(path.read_bytes())
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=path.name)
        msg.attach(part)

    return msg


def encode_message(message: Message) -> str:
    """Encode a MIME message for Gmail API."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
