#!/usr/bin/env python3
"""Gmail CLI - Read, send, and reply to emails."""

import argparse
import base64
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from auth import authenticate
from html_to_markdown import convert_to_markdown


def format_date(timestamp_ms: str) -> str:
    """Convert Gmail timestamp to readable format."""
    ts = int(timestamp_ms) / 1000
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')


def get_header(headers: list, name: str) -> str:
    """Extract header value by name."""
    for header in headers:
        if header['name'].lower() == name.lower():
            return header['value']
    return ''


def get_body(payload: dict) -> str:
    """Extract plain text or HTML body from message payload."""
    # Check for simple body
    if 'body' in payload and payload['body'].get('data'):
        return decode_body(payload['body']['data'])

    # Check multipart
    parts = payload.get('parts', [])

    # Prefer plain text
    for part in parts:
        if part.get('mimeType') == 'text/plain':
            if part.get('body', {}).get('data'):
                return decode_body(part['body']['data'])

    # Fall back to HTML
    for part in parts:
        if part.get('mimeType') == 'text/html':
            if part.get('body', {}).get('data'):
                html = decode_body(part['body']['data'])
                return convert_to_markdown(html)

    # Recurse into nested multipart
    for part in parts:
        if part.get('mimeType', '').startswith('multipart/'):
            result = get_body(part)
            if result:
                return result

    return ''


def decode_body(data: str) -> str:
    """Decode base64url encoded body."""
    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')


def cmd_list(args) -> int:
    """List emails matching query."""
    service = authenticate()

    query = args.query or ''
    limit = args.limit or 10

    results = service.users().messages().list(
        userId='me',
        q=query,
        maxResults=limit
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


def cmd_read(args) -> int:
    """Read full email content."""
    service = authenticate()

    message_ids = args.ids

    # If query mode, fetch IDs first
    if args.query:
        results = service.users().messages().list(
            userId='me',
            q=args.query,
            maxResults=args.limit or 10
        ).execute()
        message_ids = [m['id'] for m in results.get('messages', [])]

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
        print(f"Subject: {get_header(headers, 'Subject')}")
        print(f"Date: {format_date(msg.get('internalDate', '0'))}")
        print('\n---\n')

        body = get_body(msg.get('payload', {}))
        print(body.strip() if body else '(No body content)')

    return 0


def cmd_send(args) -> int:
    """Send a new email."""
    service = authenticate()

    # Get body from args or file
    if args.file:
        body = Path(args.file).read_text()
    elif args.body:
        body = args.body
    else:
        print('Error: --body or --file required')
        return 1

    message = MIMEText(body)
    message['To'] = args.to
    message['Subject'] = args.subject or ''

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

    result = service.users().messages().send(
        userId='me',
        body={'raw': raw}
    ).execute()

    print('Message sent successfully.')
    print(f"Message-ID: {result['id']}")
    if 'threadId' in result:
        print(f"Thread-ID: {result['threadId']}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Gmail CLI - Read, send, and reply to emails'
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # list command
    list_parser = subparsers.add_parser('list', help='List emails')
    list_parser.add_argument('--query', '-q', help='Gmail search query')
    list_parser.add_argument('--limit', '-n', type=int, default=10,
                            help='Max messages to return (default: 10)')
    list_parser.set_defaults(func=cmd_list)

    # read command
    read_parser = subparsers.add_parser('read', help='Read email content')
    read_parser.add_argument('ids', nargs='*', help='Message IDs to read')
    read_parser.add_argument('--query', '-q', help='Gmail search query')
    read_parser.add_argument('--limit', '-n', type=int, default=10,
                            help='Max messages when using query (default: 10)')
    read_parser.set_defaults(func=cmd_read)

    # send command
    send_parser = subparsers.add_parser('send', help='Send an email')
    send_parser.add_argument('--to', required=True, help='Recipient email')
    send_parser.add_argument('--subject', '-s', help='Email subject')
    send_parser.add_argument('--body', '-b', help='Email body text')
    send_parser.add_argument('--file', '-f', help='Read body from file')
    send_parser.set_defaults(func=cmd_send)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
