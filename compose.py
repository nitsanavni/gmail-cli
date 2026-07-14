"""Message building helpers for Gmail CLI send/reply."""

import argparse
import base64
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def get_body_content(args: argparse.Namespace) -> str | None:
    """Get message body from args (--body or --file)."""
    if args.file:
        return Path(args.file).read_text()
    if args.body:
        return args.body
    return None


def set_optional_recipients(message: MIMEText, args: argparse.Namespace) -> None:
    """Set CC and BCC headers on a message if provided in args."""
    if args.cc:
        message['Cc'] = ', '.join(args.cc)
    if args.bcc:
        message['Bcc'] = ', '.join(args.bcc)


def build_message(body: str, attachments: list[str] | None) -> MIMEText | MIMEMultipart:
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


def encode_message(message: MIMEText) -> str:
    """Encode a MIME message for Gmail API."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
