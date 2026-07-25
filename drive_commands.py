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


def mark_comment_seen(state: str | None, file_id: str, *ids: str) -> None:
    """Record ids as already-seen in a watch-comments state file.

    The agent's own comments are authored by the user (their token), so a
    comment watcher cannot filter them out by author. The writer must claim
    them, exactly as `docs append --state` does for body text.
    """
    import json
    from pathlib import Path

    if not state:
        return
    path = Path(state)
    seen: set[str] = set()
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get('file_id') == file_id:
            seen = set(saved.get('seen', []))
    seen.update(ids)
    path.write_text(json.dumps({'file_id': file_id, 'seen': sorted(seen)}))


COMMENT_FIELDS = ('comments(id,author(displayName),content,quotedFileContent(value),'
                  'resolved,createdTime,replies(id,author(displayName),content,createdTime))')


def cmd_drive_comments(args: argparse.Namespace) -> int:
    """List comment threads on a file.

    Comments are anchored to a selection, so they carry their own context: the
    quoted text says exactly what the commenter meant, with no inference.
    """
    service = authenticate_drive(args.account)
    result = service.comments().list(
        fileId=extract_id(args.file_id),
        fields=COMMENT_FIELDS,
        includeDeleted=False,
        pageSize=100,
    ).execute()

    threads = [c for c in result.get('comments', [])
               if args.all or not c.get('resolved')]
    if not threads:
        print('No open comments.' if not args.all else 'No comments.')
        return 0

    for comment in threads:
        mark = 'resolved' if comment.get('resolved') else 'open'
        author = comment.get('author', {}).get('displayName', '?')
        quoted = (comment.get('quotedFileContent') or {}).get('value', '')
        print(f"[{comment['id']}] ({mark}) {author}: {comment.get('content', '')}")
        if quoted:
            print(f'    on: {quoted!r}')
        for reply in comment.get('replies', []):
            r_author = reply.get('author', {}).get('displayName', '?')
            print(f"    ↳ [{reply['id']}] {r_author}: {reply.get('content', '')}")
    return 0


def cmd_drive_comment_reply(args: argparse.Namespace) -> int:
    """Reply to a comment thread, optionally resolving it."""
    service = authenticate_drive(args.account)
    file_id = extract_id(args.file_id)

    body = {'content': args.body}
    if args.resolve:
        body['action'] = 'resolve'

    try:
        reply = service.replies().create(
            fileId=file_id, commentId=args.comment_id,
            body=body, fields='id,content').execute()
    except HttpError as exc:
        print(f'Error: reply failed: {exc}', file=sys.stderr)
        return 1

    mark_comment_seen(getattr(args, 'state', None), file_id, reply['id'])
    print(f"Replied [{reply['id']}]" + (' and resolved' if args.resolve else ''))
    return 0


def build_anchor(account: str | None, file_id: str, target: str) -> str | None:
    """Build a Drive anchor JSON for the first occurrence of `target`.

    Uses the undocumented legacy shape {"r": revision, "a":[{"txt":{"o","l"}}]}.
    The offset is the Docs index minus one, since a document body starts at
    index 1 while anchor offsets are zero-based.
    """
    import json

    from auth import authenticate_docs

    drive = authenticate_drive(account)
    revisions = drive.revisions().list(
        fileId=file_id, fields='revisions(id)').execute().get('revisions', [])
    if not revisions:
        return None

    doc = authenticate_docs(account).documents().get(documentId=file_id).execute()
    for el in doc['body']['content']:
        para = el.get('paragraph')
        if not para:
            continue
        for run in para['elements']:
            text_run = run.get('textRun')
            if not text_run:
                continue
            pos = text_run['content'].find(target)
            if pos >= 0:
                index = run['startIndex'] + pos
                return json.dumps({'r': revisions[-1]['id'],
                                   'a': [{'txt': {'o': index - 1,
                                                  'l': len(target)}}]})
    return None


def cmd_drive_comment_add(args: argparse.Namespace) -> int:
    """Create a comment, optionally anchored to a piece of text.

    Anchor it whenever possible: an unanchored comment frequently does not
    render in the Docs UI at all, so the user never sees it.
    """
    service = authenticate_drive(args.account)
    file_id = extract_id(args.file_id)

    body = {'content': args.body}
    if args.anchor_text:
        anchor = build_anchor(args.account, file_id, args.anchor_text)
        if not anchor:
            print(f'Error: text not found to anchor to: {args.anchor_text!r}',
                  file=sys.stderr)
            return 1
        body['anchor'] = anchor

    try:
        comment = service.comments().create(
            fileId=file_id, body=body, fields='id,content').execute()
    except HttpError as exc:
        print(f'Error: comment failed: {exc}', file=sys.stderr)
        return 1
    mark_comment_seen(getattr(args, 'state', None), file_id, comment['id'])
    where = f' anchored to {args.anchor_text!r}' if args.anchor_text else ' (unanchored)'
    print(f"Created comment [{comment['id']}]{where}")
    return 0


def cmd_drive_comment_delete(args: argparse.Namespace) -> int:
    """Delete a comment thread."""
    service = authenticate_drive(args.account)
    service.comments().delete(
        fileId=extract_id(args.file_id), commentId=args.comment_id).execute()
    print(f'Deleted comment [{args.comment_id}]')
    return 0


def cmd_drive_watch_comments(args: argparse.Namespace) -> int:
    """Poll comment threads and emit each new comment or reply.

    Document text and comments are different APIs: a `docs watch` sees none of
    this. Collaborating over comments needs its own watcher.
    """
    import json
    import time
    from datetime import datetime
    from pathlib import Path

    service = authenticate_drive(args.account)
    file_id = extract_id(args.file_id)
    state_path = Path(args.state) if args.state else None

    seen: set[str] = set()
    if state_path and state_path.exists():
        saved = json.loads(state_path.read_text())
        if saved.get('file_id') == file_id:
            seen = set(saved.get('seen', []))

    def save() -> None:
        if state_path:
            state_path.write_text(json.dumps(
                {'file_id': file_id, 'seen': sorted(seen)}))

    def snapshot() -> list[dict]:
        return service.comments().list(
            fileId=file_id, fields=COMMENT_FIELDS,
            includeDeleted=False, pageSize=100).execute().get('comments', [])

    first_pass = not seen
    started = time.monotonic()
    print(f'watching comments on {file_id} every {args.interval}s',
          file=sys.stderr, flush=True)

    while True:
        if args.timeout and time.monotonic() - started >= args.timeout:
            print('watch-comments: timeout reached', file=sys.stderr, flush=True)
            return 0

        # Re-read state each poll: a writer (our own comment/reply --state) may
        # have claimed ids since we started. Holding `seen` only in memory makes
        # the watcher report the agent's own writes back to it.
        if state_path and state_path.exists():
            saved = json.loads(state_path.read_text())
            if saved.get('file_id') == file_id:
                seen |= set(saved.get('seen', []))

        try:
            threads = snapshot()
        except HttpError as exc:
            print(f'watch-comments: fetch failed: {exc}', file=sys.stderr, flush=True)
            time.sleep(args.interval)
            continue

        events: list[tuple[str, str]] = []   # (id, rendered line)
        for comment in threads:
            quoted = (comment.get('quotedFileContent') or {}).get('value', '')
            author = comment.get('author', {}).get('displayName', '?')
            if comment['id'] not in seen:
                seen.add(comment['id'])
                if not first_pass:
                    events.append((comment['id'],
                        f"NEW THREAD [{comment['id']}] {author}: "
                        f"{comment.get('content', '')}"
                        + (f'\n    on: {quoted!r}' if quoted else '')))
            for reply in comment.get('replies', []):
                if reply['id'] in seen:
                    continue
                seen.add(reply['id'])
                if first_pass:
                    continue
                r_author = reply.get('author', {}).get('displayName', '?')
                events.append((reply['id'],
                    f"REPLY in [{comment['id']}] {r_author}: "
                    f"{reply.get('content', '')}"
                    + (f'\n    thread on: {quoted!r}' if quoted else '')))

        # Re-check state after the fetch: a write that landed between the
        # state read and the network round-trip would otherwise be reported as
        # if it came from the user.
        if events and state_path and state_path.exists():
            saved = json.loads(state_path.read_text())
            if saved.get('file_id') == file_id:
                claimed = set(saved.get('seen', []))
                seen |= claimed
                events = [(eid, text) for eid, text in events
                          if eid not in claimed]

        save()
        if events:
            stamp = datetime.now().strftime('%H:%M:%S')
            print(f'\n=== comments {stamp} ===', flush=True)
            print('\n'.join(text for _, text in events), flush=True)
            if args.once:
                return 0

        first_pass = False
        time.sleep(args.interval)
