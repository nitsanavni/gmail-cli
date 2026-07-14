"""Attachment download command handler for Gmail CLI."""

import argparse
import base64
import itertools
import sys
from collections.abc import Iterator
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


def unique_path(directory: Path, name: str) -> Path:
    """Return a path in directory that does not overwrite an existing file."""
    candidate = directory / name
    if not candidate.exists():
        return candidate

    stem, suffix = Path(name).stem, Path(name).suffix
    for n in itertools.count(1):
        candidate = directory / f'{stem}-{n}{suffix}'
        if not candidate.exists():
            return candidate

    raise AssertionError('unreachable')  # pragma: no cover


def cmd_attachments(args: argparse.Namespace) -> int:
    """Download attachments from an email."""
    service = authenticate(args.account)

    output_dir = Path(args.output) if args.output else Path('.')
    output_dir.mkdir(parents=True, exist_ok=True)

    msg = service.users().messages().get(
        userId='me', id=args.id, format='full'
    ).execute()

    found = 0
    for part in iter_attachment_parts(msg.get('payload', {})):
        raw_name = part['filename']
        attachment_id = part['body']['attachmentId']

        name = safe_filename(raw_name)
        if name is None:
            print(f'Skipped unsafe attachment name: {raw_name!r}', file=sys.stderr)
            continue
        if name != raw_name:
            print(f'Sanitized attachment name {raw_name!r} -> {name!r}', file=sys.stderr)

        attachment = service.users().messages().attachments().get(
            userId='me', messageId=args.id, id=attachment_id
        ).execute()

        data = attachment.get('data')
        if not data:
            print(f'No data returned for attachment: {name}', file=sys.stderr)
            continue

        filepath = unique_path(output_dir, name)
        filepath.write_bytes(base64.urlsafe_b64decode(data))
        print(f'Saved: {filepath}')
        found += 1

    if not found:
        print('No attachments found.')
    return 0
