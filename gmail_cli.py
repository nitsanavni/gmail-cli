#!/usr/bin/env python3
"""Gmail CLI - Read, send, and reply to emails."""

import argparse
import base64
import os
import sys
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

from auth import authenticate, get_token_path, list_accounts, run_oauth_flow
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


def get_body_content(args) -> str | None:
    """Get message body from args (--body or --file)."""
    if args.file:
        return Path(args.file).read_text()
    if args.body:
        return args.body
    return None


def encode_message(message: MIMEText) -> str:
    """Encode a MIMEText message for Gmail API."""
    return base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')


def cmd_list(args) -> int:
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


def cmd_read(args) -> int:
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
        bcc = get_header(headers, 'Bcc')
        if bcc:
            print(f"Bcc: {bcc}")
        print(f"Subject: {get_header(headers, 'Subject')}")
        print(f"Date: {format_date(msg.get('internalDate', '0'))}")
        print('\n---\n')

        body = get_body(msg.get('payload', {}))
        print(body.strip() if body else '(No body content)')

    return 0


def cmd_send(args) -> int:
    """Send a new email or create a draft."""
    body = get_body_content(args)
    if not body:
        print('Error: --body or --file required')
        return 1

    service = authenticate(args.account)

    message = MIMEText(body)
    message['To'] = args.to
    message['Subject'] = args.subject or ''
    if args.bcc:
        message['Bcc'] = args.bcc
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


def cmd_reply(args) -> int:
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

    message = MIMEText(body)
    message['To'] = original_from
    message['Subject'] = subject
    message['In-Reply-To'] = original_message_id
    message['References'] = original_message_id
    if args.bcc:
        message['Bcc'] = args.bcc
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


def cmd_accounts(args) -> int:
    """List or manage Gmail accounts."""
    if args.accounts_action:
        return args.accounts_func(args)
    return cmd_accounts_list(args)


def cmd_accounts_list(args) -> int:
    """List all authenticated accounts."""
    accounts = list_accounts()
    default = os.environ.get('GMAIL_CLI_ACCOUNT')

    if not accounts:
        print('No accounts configured.')
        print('Run: uv run gmail_cli.py accounts add')
        return 0

    print('Available accounts:')
    for email in accounts:
        marker = '*' if email == default else ' '
        print(f'  {marker} {email}')

    if default and default not in accounts:
        print(f"\nWarning: GMAIL_CLI_ACCOUNT='{default}' not found")

    return 0


def cmd_accounts_add(args) -> int:
    """Add new account via OAuth flow."""
    print('Opening browser for authentication...')
    run_oauth_flow()
    return 0


def cmd_accounts_remove(args) -> int:
    """Remove account token file."""
    accounts = list_accounts()

    if args.email not in accounts:
        print(f"Error: Account '{args.email}' not found")
        if accounts:
            print('Available accounts:')
            for email in accounts:
                print(f'  - {email}')
        return 1

    token_path = get_token_path(args.email)
    token_path.unlink()
    print(f'Removed account: {args.email}')
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Gmail CLI - Read, send, and reply to emails'
    )

    # Global account flag
    parser.add_argument(
        '--account', '-a',
        help='Email account to use (e.g., user@example.com)'
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
    send_parser.add_argument('--draft', '-d', action='store_true',
                            help='Create draft instead of sending')
    send_parser.add_argument('--bcc', help='BCC recipient email')
    send_parser.set_defaults(func=cmd_send)

    # reply command
    reply_parser = subparsers.add_parser('reply', help='Reply to an email')
    reply_parser.add_argument('message_id', help='Message ID to reply to')
    reply_parser.add_argument('--body', '-b', help='Reply body text')
    reply_parser.add_argument('--file', '-f', help='Read body from file')
    reply_parser.add_argument('--draft', '-d', action='store_true',
                            help='Create draft instead of sending')
    reply_parser.add_argument('--bcc', help='BCC recipient email')
    reply_parser.set_defaults(func=cmd_reply)

    # accounts command
    accounts_parser = subparsers.add_parser('accounts', help='Manage Gmail accounts')
    accounts_parser.set_defaults(func=cmd_accounts)
    accounts_subparsers = accounts_parser.add_subparsers(dest='accounts_action')

    # accounts list
    accounts_subparsers.add_parser(
        'list', help='List accounts'
    ).set_defaults(accounts_func=cmd_accounts_list)

    # accounts add
    accounts_subparsers.add_parser(
        'add', help='Add new account'
    ).set_defaults(accounts_func=cmd_accounts_add)

    # accounts remove
    remove_parser = accounts_subparsers.add_parser('remove', help='Remove account')
    remove_parser.add_argument('email', help='Email address to remove')
    remove_parser.set_defaults(accounts_func=cmd_accounts_remove)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
