"""Drive command handlers for Gmail CLI."""

import argparse
import io
import re
import sys

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from auth import authenticate_drive

# Google-native types must be exported, not downloaded directly.
EXPORT_FORMATS = {
    'application/vnd.google-apps.document': 'text/markdown',
    'application/vnd.google-apps.spreadsheet': 'text/csv',
    'application/vnd.google-apps.presentation': 'text/plain',
    'application/vnd.google-apps.script': 'application/vnd.google-apps.script+json',
}

FIELDS = 'id, name, mimeType, modifiedTime, owners(emailAddress), webViewLink, size'

# Matches /d/<id>, /file/d/<id>, and ?id=<id> forms.
ID_IN_URL = re.compile(r'/d/([A-Za-z0-9_-]{10,})|[?&]id=([A-Za-z0-9_-]{10,})')


def extract_id(value: str) -> str:
    """Accept a bare file ID or any Drive/Docs URL and return the file ID."""
    match = ID_IN_URL.search(value)
    if match:
        return match.group(1) or match.group(2)
    return value


def short_type(mime: str) -> str:
    """Human-readable label for a mime type."""
    if mime.startswith('application/vnd.google-apps.'):
        return mime.rsplit('.', 1)[-1]
    return mime


def format_file(item: dict) -> str:
    """Format a file as a one-line summary."""
    modified = item.get('modifiedTime', '?')[:10]
    owner = (item.get('owners') or [{}])[0].get('emailAddress', '')
    return (f"[{item['id']}] {modified}  {short_type(item['mimeType']):<12} "
            f"{item.get('name', '(untitled)')}" + (f"  <{owner}>" if owner else ''))


def run_query(args: argparse.Namespace, query: str | None) -> int:
    """Shared list/search implementation."""
    service = authenticate_drive(args.account)
    result = service.files().list(
        q=query,
        pageSize=args.limit,
        orderBy='modifiedTime desc',
        fields=f'files({FIELDS})',
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()

    files = result.get('files', [])
    if not files:
        print('No files found.')
        return 0

    for item in files:
        print(format_file(item))
    return 0


def cmd_drive_list(args: argparse.Namespace) -> int:
    """List recently modified files."""
    clauses = ['trashed = false']
    if args.shared:
        clauses.append('sharedWithMe')
    return run_query(args, ' and '.join(clauses))


def cmd_drive_search(args: argparse.Namespace) -> int:
    """Search files by name and full text."""
    escaped = args.query.replace("'", "\\'")
    clauses = [
        'trashed = false',
        f"(name contains '{escaped}' or fullText contains '{escaped}')",
    ]
    return run_query(args, ' and '.join(clauses))


def cmd_drive_read(args: argparse.Namespace) -> int:
    """Print a file's content as text (exporting Google-native formats)."""
    service = authenticate_drive(args.account)
    file_id = extract_id(args.file_id)

    try:
        meta = service.files().get(
            fileId=file_id, fields=FIELDS, supportsAllDrives=True
        ).execute()
    except HttpError as exc:
        print(f'Error: cannot access {file_id}: {exc}', file=sys.stderr)
        return 1

    mime = meta['mimeType']
    if mime in EXPORT_FORMATS:
        export_mime = args.mime or EXPORT_FORMATS[mime]
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    data = buffer.getvalue()

    if args.output:
        with open(args.output, 'wb') as handle:
            handle.write(data)
        print(f"Saved {meta.get('name')} -> {args.output} ({len(data)} bytes)")
        return 0

    try:
        print(data.decode('utf-8'))
    except UnicodeDecodeError:
        print(f"Error: {meta.get('name')} is binary ({short_type(mime)}). "
              f"Use --output to save it.", file=sys.stderr)
        return 1
    return 0


def cmd_drive_info(args: argparse.Namespace) -> int:
    """Show metadata for a file."""
    service = authenticate_drive(args.account)
    meta = service.files().get(
        fileId=extract_id(args.file_id), fields=FIELDS, supportsAllDrives=True
    ).execute()
    for key, value in meta.items():
        print(f'{key}: {value}')
    return 0
