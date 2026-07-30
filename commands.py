"""Command handlers for Gmail CLI."""

import argparse
import base64
import itertools
import json
import mimetypes
import sys
from collections.abc import Callable, Iterator
from datetime import datetime, timezone
from email import encoders
from email.header import Header
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
from pathlib import Path

from googleapiclient.errors import HttpError

from auth import authenticate
from html_to_markdown import convert_to_markdown


def format_date(timestamp_ms: str) -> str:
    """Convert Gmail timestamp to readable format."""
    ts = int(timestamp_ms) / 1000
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def iso_timestamp(timestamp_ms: str) -> str:
    """Convert Gmail's internalDate (epoch milliseconds) to an ISO-8601 UTC instant.

    Split seconds from milliseconds instead of dividing by 1000: the float
    division of e.g. 1753876543123 is not exact, and rounding it back to
    microseconds can land a millisecond off.
    """
    ms = int(timestamp_ms)
    moment = datetime.fromtimestamp(ms // 1000, tz=timezone.utc)
    return moment.replace(microsecond=ms % 1000 * 1000).isoformat().replace('+00:00', 'Z')


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


def safe_filename(filename: str) -> str | None:
    """Reduce a sender-controlled attachment name to a bare filename.

    Attachment names arrive from the email, so a hostile sender picks them.
    Both '../../.ssh/authorized_keys' and '/etc/cron.d/pwn' are legal MIME
    filenames, and pathlib honors both: an absolute right-hand operand makes
    `output_dir / filename` discard output_dir entirely. Keep only the final
    path component so a download can never escape the output directory.

    Returns None when nothing usable survives sanitizing.
    """
    name = Path(filename).name
    if name in ('', '.', '..'):
        return None
    return name


def iter_attachment_parts(part: dict) -> Iterator[dict]:
    """Yield every part carrying an attachment, at any nesting depth.

    Real messages nest: multipart/mixed wrapping multipart/alternative, inline
    images under multipart/related, forwarded message/rfc822. Scanning only the
    top-level parts misses attachments that are plainly visible in Gmail.
    """
    if part.get('filename') and part.get('body', {}).get('attachmentId'):
        yield part

    for subpart in part.get('parts', []):
        yield from iter_attachment_parts(subpart)


def numbered_path(directory: Path, name: str, taken: Callable[[Path], bool]) -> Path:
    """Return directory/name, suffixed '-1', '-2', ... until `taken` says it is free."""
    candidate = directory / name
    if not taken(candidate):
        return candidate

    stem, suffix = Path(name).stem, Path(name).suffix
    for n in itertools.count(1):
        candidate = directory / f'{stem}-{n}{suffix}'
        if not taken(candidate):
            return candidate

    raise AssertionError('unreachable')  # pragma: no cover


def unique_path(directory: Path, name: str) -> Path:
    """Return a path in directory that does not overwrite an existing file."""
    return numbered_path(directory, name, lambda path: path.exists())


def run_scoped_path() -> Callable[[Path, str], Path]:
    """Build an allocator that de-dupes only against names it has already handed out.

    `unique_path` asks the filesystem, which is right for downloading into a
    directory someone else owns but wrong for a directory we rewrite: on a second
    run the first run's files are sitting there, so every name would slide to
    '-1', then '-2'. Same message in, same filenames out.
    """
    used: set[str] = set()

    def allocate(directory: Path, name: str) -> Path:
        path = numbered_path(directory, name, lambda candidate: candidate.name in used)
        used.add(path.name)
        return path

    return allocate


def save_attachments(
    service,
    message_id: str,
    payload: dict,
    output_dir: Path,
    allocate: Callable[[Path, str], Path] = unique_path,
) -> list[dict]:
    """Download every attachment in payload into output_dir.

    Returns one record per saved file: path, the name as written, mime type and
    byte size.
    """
    saved = []

    for part in iter_attachment_parts(payload):
        raw_name = part['filename']
        attachment_id = part['body']['attachmentId']

        name = safe_filename(raw_name)
        if name is None:
            print(f'Skipped unsafe attachment name: {raw_name!r}', file=sys.stderr)
            continue
        if name != raw_name:
            print(f'Sanitized attachment name {raw_name!r} -> {name!r}', file=sys.stderr)

        attachment = service.users().messages().attachments().get(
            userId='me', messageId=message_id, id=attachment_id
        ).execute()

        data = attachment.get('data')
        if not data:
            print(f'No data returned for attachment: {name}', file=sys.stderr)
            continue

        content = base64.urlsafe_b64decode(data)
        filepath = allocate(output_dir, name)
        filepath.write_bytes(content)

        saved.append({
            'path': filepath,
            'filename': filepath.name,
            'mime_type': part.get('mimeType', 'application/octet-stream'),
            'size': len(content),
        })

    return saved


def cmd_attachments(args: argparse.Namespace) -> int:
    """Download attachments from an email."""
    service = authenticate(args.account)

    output_dir = Path(args.output) if args.output else Path('.')
    output_dir.mkdir(parents=True, exist_ok=True)

    msg = service.users().messages().get(
        userId='me', id=args.id, format='full'
    ).execute()

    saved = save_attachments(service, args.id, msg.get('payload', {}), output_dir)
    for record in saved:
        print(f"Saved: {record['path']}")

    if not saved:
        print('No attachments found.')

    return 0


def build_envelope(msg: dict, attachments: list[dict]) -> dict:
    """Describe a message as the JSON an agent reads instead of the raw API shape."""
    payload = msg.get('payload', {})
    headers = payload.get('headers', [])
    body = get_body(payload)

    return {
        'source': 'gmail-cli',
        'id': msg['id'],
        'thread_id': msg['threadId'],
        'ts': iso_timestamp(msg.get('internalDate', '0')),
        'from': get_header(headers, 'From'),
        'to': get_header(headers, 'To'),
        'cc': get_header(headers, 'Cc'),
        'subject': get_header(headers, 'Subject'),
        'labels': msg.get('labelIds', []),
        'body_markdown': body.strip(),
        'attachments': [
            {'filename': a['filename'], 'mime_type': a['mime_type'], 'size': a['size']}
            for a in attachments
        ],
    }


def cmd_materialize(args: argparse.Namespace) -> int:
    """Write an email into a directory as envelope.json plus attachments/."""
    service = authenticate(args.account)

    try:
        msg = service.users().messages().get(
            userId='me', id=args.id, format='full'
        ).execute()
    except HttpError as exc:
        print(f'Error: cannot read message {args.id}: {exc}', file=sys.stderr)
        return 1

    output_dir = Path(args.output)
    attachments_dir = output_dir / 'attachments'
    attachments_dir.mkdir(parents=True, exist_ok=True)

    saved = save_attachments(
        service, args.id, msg.get('payload', {}), attachments_dir, run_scoped_path()
    )
    envelope = build_envelope(msg, saved)

    envelope_path = output_dir / 'envelope.json'
    envelope_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False) + '\n')

    print(f'Materialized {args.id} -> {output_dir}')
    print(f'  envelope.json, {len(saved)} attachment(s)')

    return 0


def cmd_archive(args: argparse.Namespace) -> int:
    """Archive emails by removing the INBOX label."""
    service = authenticate(args.account)

    for msg_id in args.ids:
        service.users().messages().modify(
            userId='me',
            id=msg_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        print(f'Archived: {msg_id}')

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

    # Non-ASCII display names (e.g. "Ana Cañadas <a@b.com>") must be encoded
    # separately from the address, or Gmail rejects the To header
    name, addr = parseaddr(original_from)
    reply_to = formataddr((str(Header(name, 'utf-8')), addr)) if name else addr

    message = build_message(body, args.attach)
    message['To'] = reply_to
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
