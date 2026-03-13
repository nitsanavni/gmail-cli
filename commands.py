"""Command handlers for Gmail CLI."""

import argparse
import base64
import mimetypes
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from auth import authenticate
from html_to_markdown import convert_to_markdown


def format_date(timestamp_ms: str) -> str:
    """Convert Gmail timestamp to readable format."""
    ts = int(timestamp_ms) / 1000
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def get_header(headers: list, name: str) -> str:
    """Extract header value by name (case-insensitive)."""
    name_lower = name.lower()
    for header in headers:
        if header['name'].lower() == name_lower:
            return header['value']
    return ''


def decode_body(data: str) -> str:
    """Decode base64url encoded body."""
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')


def extract_part_body(part: dict, mime_type: str) -> str | None:
    """Extract body from a message part if it matches the mime type."""
    if part.get('mimeType') != mime_type:
        return None

    data = part.get('body', {}).get('data')
    if not data:
        return None

    content = decode_body(data)
    if mime_type == 'text/html':
        return convert_to_markdown(content)
    return content


def get_body(payload: dict) -> str:
    """Extract plain text or HTML body from message payload."""
    # Simple body (non-multipart)
    if payload.get('body', {}).get('data'):
        return decode_body(payload['body']['data'])

    parts = payload.get('parts', [])

    # Prefer plain text
    for part in parts:
        if body := extract_part_body(part, 'text/plain'):
            return body

    # Fall back to HTML
    for part in parts:
        if body := extract_part_body(part, 'text/html'):
            return body

    # Recurse into nested multipart
    for part in parts:
        if part.get('mimeType', '').startswith('multipart/'):
            if body := get_body(part):
                return body

    return ''


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


def cmd_list(args: argparse.Namespace) -> int:
    """List emails matching query."""
    service = authenticate(args.account)

    results = service.users().messages().list(
        userId='me',
        q=args.query or '',
        maxResults=args.limit
    ).execute()

    messages = results.get('messages', [])
    if not messages:
        print('No messages found.')
        return 0

    print(f'Found {len(messages)} message(s):\n')

    for i, msg in enumerate(messages, 1):
        msg_data = service.users().messages().get(
            userId='me',
            id=msg['id'],
            format='metadata',
            metadataHeaders=['From', 'Subject', 'Date']
        ).execute()

        headers = msg_data.get('payload', {}).get('headers', [])
        print(f"[{i}] ID: {msg['id']}")
        print(f"    From: {get_header(headers, 'From')}")
        print(f"    Subject: {get_header(headers, 'Subject')}")
        print(f"    Date: {format_date(msg_data.get('internalDate', '0'))}")
        print()

    return 0


def cmd_read(args: argparse.Namespace) -> int:
    """Read full email content."""
    service = authenticate(args.account)

    # Get message IDs from args or query
    if args.query:
        results = service.users().messages().list(
            userId='me',
            q=args.query,
            maxResults=args.limit
        ).execute()
        message_ids = [m['id'] for m in results.get('messages', [])]
    else:
        message_ids = args.ids

    if not message_ids:
        print('No messages found.')
        return 0

    for i, msg_id in enumerate(message_ids):
        if i > 0:
            print('\n' + '=' * 60 + '\n')

        msg = service.users().messages().get(
            userId='me',
            id=msg_id,
            format='full'
        ).execute()

        headers = msg.get('payload', {}).get('headers', [])
        print(f"Message-ID: {msg['id']}")
        print(f"Thread-ID: {msg['threadId']}")
        print(f"From: {get_header(headers, 'From')}")
        print(f"To: {get_header(headers, 'To')}")
        for header_name in ('Cc', 'Bcc'):
            value = get_header(headers, header_name)
            if value:
                print(f"{header_name}: {value}")
        print(f"Subject: {get_header(headers, 'Subject')}")
        print(f"Date: {format_date(msg.get('internalDate', '0'))}")
        print('\n---\n')

        body = get_body(msg.get('payload', {}))
        print(body.strip() if body else '(No body content)')

    return 0


def cmd_send(args: argparse.Namespace) -> int:
    """Send a new email or create a draft."""
    body = get_body_content(args)
    if not body:
        print('Error: --body or --file required')
        return 1

    service = authenticate(args.account)

    message = build_message(body, args.attach)
    message['To'] = args.to
    message['Subject'] = args.subject or ''
    set_optional_recipients(message, args)
    raw = encode_message(message)

    if args.draft:
        result = service.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw}}
        ).execute()
        print('Draft created successfully.')
        print(f"Draft-ID: {result['id']}")
        print(f"Message-ID: {result['message']['id']}")
    else:
        result = service.users().messages().send(
            userId='me',
            body={'raw': raw}
        ).execute()
        print('Message sent successfully.')
        print(f"Message-ID: {result['id']}")
        if 'threadId' in result:
            print(f"Thread-ID: {result['threadId']}")

    return 0


def cmd_attachments(args: argparse.Namespace) -> int:
    """Download attachments from an email."""
    service = authenticate(args.account)
    output_dir = Path(args.output) if args.output else Path('.')

    msg = service.users().messages().get(
        userId='me', id=args.id, format='full'
    ).execute()

    parts = msg.get('payload', {}).get('parts', [])
    found = 0
    for part in parts:
        filename = part.get('filename')
        if not filename:
            continue
        attachment_id = part.get('body', {}).get('attachmentId')
        if not attachment_id:
            continue

        attachment = service.users().messages().attachments().get(
            userId='me', messageId=args.id, id=attachment_id
        ).execute()

        data = base64.urlsafe_b64decode(attachment['data'])
        filepath = output_dir / filename
        filepath.write_bytes(data)
        print(f'Saved: {filepath}')
        found += 1

    if not found:
        print('No attachments found.')
    return 0


def cmd_reply(args: argparse.Namespace) -> int:
    """Reply to an existing email or create a draft reply."""
    body = get_body_content(args)
    if not body:
        print('Error: --body or --file required')
        return 1

    service = authenticate(args.account)

    # Fetch original message for threading info
    original = service.users().messages().get(
        userId='me',
        id=args.message_id,
        format='metadata',
        metadataHeaders=['From', 'Subject', 'Message-ID']
    ).execute()

    headers = original.get('payload', {}).get('headers', [])
    original_from = get_header(headers, 'From')
    original_subject = get_header(headers, 'Subject')
    original_message_id = get_header(headers, 'Message-ID')
    thread_id = original['threadId']

    # Build reply subject
    subject = original_subject
    if not subject.lower().startswith('re:'):
        subject = f'Re: {subject}'

    message = build_message(body, args.attach)
    message['To'] = original_from
    message['Subject'] = subject
    message['In-Reply-To'] = original_message_id
    message['References'] = original_message_id
    set_optional_recipients(message, args)
    raw = encode_message(message)

    if args.draft:
        result = service.users().drafts().create(
            userId='me',
            body={'message': {'raw': raw, 'threadId': thread_id}}
        ).execute()
        print('Draft reply created successfully.')
        print(f"Draft-ID: {result['id']}")
        print(f"Message-ID: {result['message']['id']}")
        print(f"Thread-ID: {thread_id}")
    else:
        result = service.users().messages().send(
            userId='me',
            body={'raw': raw, 'threadId': thread_id}
        ).execute()
        print('Reply sent successfully.')
        print(f"Message-ID: {result['id']}")
        print(f"Thread-ID: {result['threadId']}")

    return 0
