"""Attachment download command handler for Gmail CLI."""

import argparse
import base64
from pathlib import Path

from auth import authenticate


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
