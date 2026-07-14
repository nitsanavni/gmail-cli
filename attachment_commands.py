"""Attachment download command handler for Gmail CLI."""

import argparse
import base64
import sys
from pathlib import Path

from auth import authenticate


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
        raw_name = part.get('filename')
        if not raw_name:
            continue
        attachment_id = part.get('body', {}).get('attachmentId')
        if not attachment_id:
            continue

        name = safe_filename(raw_name)
        if name is None:
            print(f'Skipped unsafe attachment name: {raw_name!r}', file=sys.stderr)
            continue
        if name != raw_name:
            print(f'Sanitized attachment name {raw_name!r} -> {name!r}', file=sys.stderr)

        attachment = service.users().messages().attachments().get(
            userId='me', messageId=args.id, id=attachment_id
        ).execute()

        data = base64.urlsafe_b64decode(attachment['data'])
        filepath = output_dir / name
        filepath.write_bytes(data)
        print(f'Saved: {filepath}')
        found += 1

    if not found:
        print('No attachments found.')
    return 0
