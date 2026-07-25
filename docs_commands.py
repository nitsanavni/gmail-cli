"""Google Docs command handlers for Gmail CLI.

The Docs API inserts plain text only, so markdown-ish source is parsed into
(plain text + styling ranges) and the styling is re-applied as batch requests.
"""

import argparse
import difflib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from googleapiclient.errors import HttpError

from auth import authenticate_docs
from drive_commands import extract_id

HEADING_PREFIXES = [('### ', 3), ('## ', 2), ('# ', 1)]

# Inline markers, longest first so '**' is not read as two '*'.
MARKERS = [('**', 'bold'), ('*', 'italic'), ('~', 'subscript'), ('^', 'superscript')]


def scan_inline(line: str) -> tuple[str, list[tuple[int, int, str]]]:
    """Strip inline markers, returning (clean_text, [(start, end, kind)]).

    A toggling scanner rather than paired regexes, so markers nest:
    '**A > B when m~2~ > m~1~**' keeps the subscripts inside the bold run.
    Unclosed markers are dropped.
    """
    out: list[str] = []
    open_at: dict[str, int] = {}
    ranges: list[tuple[int, int, str]] = []
    i = 0
    while i < len(line):
        for token, kind in MARKERS:
            if line.startswith(token, i):
                if kind in open_at:
                    ranges.append((open_at.pop(kind), len(out), kind))
                else:
                    open_at[kind] = len(out)
                i += len(token)
                break
        else:
            out.append(line[i])
            i += 1
    return ''.join(out), [r for r in ranges if r[1] > r[0]]


def unwrap(text: str) -> str:
    """Join soft-wrapped lines within a paragraph.

    Source files wrapped at a column width would otherwise become one Docs
    paragraph per line. Blank lines, headings and bullets stay as breaks.
    """
    def is_heading(line: str) -> bool:
        return any(line.startswith(p) for p, _ in HEADING_PREFIXES)

    out: list[str] = []
    for line in text.split('\n'):
        stripped = line.strip()
        # A line continues the previous one unless it starts a new block.
        continues = (stripped
                     and not is_heading(line)
                     and not line.startswith('- ')
                     and out and out[-1].strip()
                     and not is_heading(out[-1]))
        if continues:
            out[-1] = out[-1].rstrip() + ' ' + stripped
        else:
            out.append(line)
    return '\n'.join(out)


def parse_markdown(text: str) -> tuple[str, list[dict]]:
    """Convert markdown-lite to (plain_text, style_ops with char offsets).

    Supports ATX headings, '- ' bullets, and **bold**. Offsets are relative to
    the start of the returned text.
    """
    out: list[str] = []
    ops: list[dict] = []
    offset = 0

    for raw in text.split('\n'):
        line = raw
        level = 0
        bullet = False

        for prefix, lvl in HEADING_PREFIXES:
            if line.startswith(prefix):
                level = lvl
                line = line[len(prefix):]
                break
        else:
            if line.startswith('- '):
                bullet = True
                line = line[2:]

        clean, inline_ranges = scan_inline(line)

        # Paragraph range includes its trailing newline.
        para_end = offset + len(clean) + 1
        if level:
            ops.append({'kind': 'heading', 'start': offset, 'end': para_end,
                        'level': level})
        elif bullet:
            ops.append({'kind': 'bullet', 'start': offset, 'end': para_end})
        for i_start, i_end, kind in inline_ranges:
            ops.append({'kind': kind, 'start': offset + i_start,
                        'end': offset + i_end})

        out.append(clean + '\n')
        offset = para_end

    return ''.join(out), ops


def u16_offsets(text: str) -> list[int]:
    """Map each Python char offset to a UTF-16 code-unit offset.

    Docs indexes in UTF-16 units, so a non-BMP char (emoji, some symbols)
    counts as 2 there but 1 in Python. Without this, every range after the
    first such char is applied one position early.
    """
    offsets = [0]
    total = 0
    for ch in text:
        total += 2 if ord(ch) > 0xFFFF else 1
        offsets.append(total)
    return offsets


def build_requests(text: str, ops: list[dict], at: int,
                   font_size: float | None = None) -> list[dict]:
    """Build batchUpdate requests to insert text at `at` and style it.

    font_size (points) applies to body text only; headings keep the size from
    their named style.
    """
    u16 = u16_offsets(text)
    end = at + u16[-1]
    # baselineOffset matters: appending at a doc that ends in subscripted math
    # otherwise inherits SUBSCRIPT, rendering the whole section small and low.
    reset_style: dict = {'bold': False, 'italic': False,
                         'baselineOffset': 'NONE', 'underline': False,
                         'strikethrough': False}
    reset_fields = 'bold,italic,baselineOffset,underline,strikethrough'
    if font_size:
        reset_style['fontSize'] = {'magnitude': font_size, 'unit': 'PT'}
        reset_fields += ',fontSize'

    requests: list[dict] = [
        {'insertText': {'location': {'index': at}, 'text': text}},
        # Inserted text inherits style from the insertion point; reset first.
        {'updateParagraphStyle': {
            'range': {'startIndex': at, 'endIndex': end},
            'paragraphStyle': {'namedStyleType': 'NORMAL_TEXT'},
            'fields': 'namedStyleType'}},
        {'updateTextStyle': {
            'range': {'startIndex': at, 'endIndex': end},
            'textStyle': reset_style,
            'fields': reset_fields}},
    ]

    for op in ops:
        rng = {'startIndex': at + u16[op['start']], 'endIndex': at + u16[op['end']]}
        if op['kind'] == 'heading':
            requests.append({'updateParagraphStyle': {
                'range': rng,
                'paragraphStyle': {'namedStyleType': f"HEADING_{op['level']}"},
                'fields': 'namedStyleType'}})
            if font_size:
                # Clear the explicit size so the heading's named style wins.
                requests.append({'updateTextStyle': {
                    'range': rng, 'textStyle': {}, 'fields': 'fontSize'}})
        elif op['kind'] in ('bold', 'italic'):
            requests.append({'updateTextStyle': {
                'range': rng, 'textStyle': {op['kind']: True},
                'fields': op['kind']}})
        elif op['kind'] in ('subscript', 'superscript'):
            requests.append({'updateTextStyle': {
                'range': rng,
                'textStyle': {'baselineOffset': op['kind'].upper()},
                'fields': 'baselineOffset'}})

    # Bullets last: createParagraphBullets can shift indices.
    for op in ops:
        if op['kind'] == 'bullet':
            requests.append({'createParagraphBullets': {
                'range': {'startIndex': at + u16[op['start']],
                          'endIndex': at + u16[op['end']]},
                'bulletPreset': 'BULLET_DISC_CIRCLE_SQUARE'}})

    return requests


def read_content(args: argparse.Namespace) -> str:
    """Get append content from --body or --file."""
    if args.file:
        with open(args.file, encoding='utf-8') as handle:
            return handle.read()
    if args.body:
        return args.body
    print('Error: provide --body or --file', file=sys.stderr)
    sys.exit(1)


def cmd_docs_append(args: argparse.Namespace) -> int:
    """Append content to the end of a Google Doc."""
    service = authenticate_docs(args.account)
    doc_id = extract_id(args.doc_id)

    content = read_content(args).rstrip('\n')
    if args.plain:
        text, ops = content + '\n', []
    else:
        text, ops = parse_markdown(content if args.keep_breaks else unwrap(content))
    text = '\n' + text  # blank line separating from existing content

    try:
        doc = service.documents().get(documentId=doc_id).execute()
    except HttpError as exc:
        print(f'Error: cannot open {doc_id}: {exc}', file=sys.stderr)
        return 1

    if args.after:
        # Insert just past the anchor paragraph's newline, i.e. directly below it.
        matches = [el for el in doc['body']['content']
                   if el.get('paragraph') and args.after in ''.join(
                       r.get('textRun', {}).get('content', '')
                       for r in el['paragraph']['elements'])]
        if not matches:
            print(f'Error: no paragraph contains {args.after!r}', file=sys.stderr)
            return 1
        if len(matches) > 1:
            print(f'Error: {len(matches)} paragraphs contain {args.after!r}; '
                  'use a longer anchor', file=sys.stderr)
            return 1
        at = matches[0]['endIndex'] - 1
    else:
        # End of body; -1 stays inside the final paragraph's newline.
        at = doc['body']['content'][-1]['endIndex'] - 1
    ops = [{**op, 'start': op['start'] + 1, 'end': op['end'] + 1} for op in ops]

    requests = build_requests(text, ops, at, args.font_size)

    if args.dry_run:
        print(f"Would append {len(text)} chars to '{doc.get('title')}' at index {at}")
        print(f'{len(requests)} requests; text preview:')
        print(text[:500])
        return 0

    try:
        service.documents().batchUpdate(
            documentId=doc_id, body={'requests': requests}).execute()
    except HttpError as exc:
        print(f'Error: append failed: {exc}', file=sys.stderr)
        return 1

    sync_state(service, args.state, doc_id)

    print(f"Appended {len(text)} chars to '{doc.get('title')}'")
    print(f'https://docs.google.com/document/d/{doc_id}/edit')
    return 0


def write_state(path: str | None, doc_id: str, revision: str | None,
                text: str) -> None:
    """Record the last-seen state of a doc, for `watch --state`."""
    if path:
        Path(path).write_text(json.dumps(
            {'doc_id': doc_id, 'revision': revision, 'text': text}))


def sync_state(service, path: str | None, doc_id: str,
               ignore_prefix: str | None = None) -> None:
    """Re-baseline after our own write, so watch does not report it as a change.

    The Docs API exposes no author on a revision, so a watcher cannot tell our
    edits from the user's. Updating the baseline here is what keeps the loop
    from waking on its own output.
    """
    if not path:
        return
    doc = service.documents().get(documentId=doc_id).execute()
    write_state(path, doc_id, doc.get('revisionId'), doc_text(doc, ignore_prefix))


def orient(lines: list[str], index: int) -> str:
    """Name the section a line falls in, by scanning back for a heading.

    Line numbers orient the tool, not the reader. Docs has no line numbers, so
    a diff is far easier to place when each hunk says which section it is in.
    """
    for i in range(min(index, len(lines) - 1), -1, -1):
        if lines[i].strip() and lines[i].strip() == lines[i].strip().rstrip(':'):
            # Treat a short, title-ish line as a heading.
            candidate = lines[i].strip()
            if len(candidate) < 80 and not candidate.endswith('.'):
                return candidate
    return '(top of document)'


def annotate_diff(diff: list[str], before: list[str]) -> list[str]:
    """Replace @@ hunk headers with the section each hunk falls under."""
    out: list[str] = []
    for line in diff:
        if line.startswith('@@'):
            match = re.match(r'@@ -(\d+)', line)
            if not match:
                out.append(line)
                continue
            start = int(match.group(1))
            out.append(f'@@ in: {orient(before, max(start - 2, 0))}')
        else:
            out.append(line)
    return out


def stamp_receipt(service, doc_id: str, prefix: str) -> None:
    """Rewrite the doc's single receipt line in place, or create it at the end.

    Gives a doc-only collaborator proof that the change was seen, without
    waiting for the agent to compose a reply. Rewritten rather than appended so
    it never accumulates.
    """
    text = f'{prefix} {datetime.now().strftime("%H:%M:%S")}'
    doc = service.documents().get(documentId=doc_id).execute()
    body = doc['body']['content']

    existing = None
    for el in body:
        para = el.get('paragraph')
        if not para:
            continue
        content = ''.join(r.get('textRun', {}).get('content', '')
                          for r in para['elements'])
        if content.startswith(prefix):
            existing = el
            break

    if existing:
        el = existing
        # Stop short of the paragraph's newline: deleting it would merge this
        # paragraph with the next, and Docs rejects it outright on the last one.
        end = el['endIndex'] - 1
        requests = [
            {'deleteContentRange': {
                'range': {'startIndex': el['startIndex'], 'endIndex': end}}},
            {'insertText': {
                'location': {'index': el['startIndex']}, 'text': text}},
        ]
    else:
        at = body[-1]['endIndex'] - 1
        requests = [{'insertText': {'location': {'index': at},
                                    'text': '\n' + text}}]

    service.documents().batchUpdate(
        documentId=doc_id, body={'requests': requests}).execute()


def doc_text(doc: dict, ignore_prefix: str | None = None) -> str:
    """Flatten a document's body to plain text, one line per paragraph.

    Paragraphs starting with ignore_prefix are excluded, so a receipt line that
    a watcher maintains never registers as a change — that is what lets a fast
    receipt watcher and a slow reading watcher run over the same doc without
    triggering each other.
    """
    lines: list[str] = []
    for el in doc['body']['content']:
        para = el.get('paragraph')
        if not para:
            continue
        line = ''.join(
            r.get('textRun', {}).get('content', '') for r in para['elements']
        ).rstrip('\n')
        if ignore_prefix and line.startswith(ignore_prefix):
            continue
        lines.append(line)
    return '\n'.join(lines)


def cmd_docs_create(args: argparse.Namespace) -> int:
    """Create a new Google Doc, optionally seeded with content."""
    service = authenticate_docs(args.account)
    doc = service.documents().create(body={'title': args.title}).execute()
    doc_id = doc['documentId']

    if args.body or args.file:
        content = read_content(args).rstrip('\n')
        text, ops = parse_markdown(unwrap(content))
        service.documents().batchUpdate(
            documentId=doc_id,
            body={'requests': build_requests(text, ops, 1)}).execute()

    print(f"Created '{args.title}'")
    print(f'https://docs.google.com/document/d/{doc_id}/edit')
    print(doc_id)
    return 0


def cmd_docs_watch(args: argparse.Namespace) -> int:
    """Poll a doc and print a unified diff whenever its text changes.

    revisionId is the change signal; an edit that restores identical text still
    bumps the revision but yields an empty diff, which is suppressed.
    """
    service = authenticate_docs(args.account)
    doc_id = extract_id(args.doc_id)

    doc = service.documents().get(documentId=doc_id).execute()
    revision = doc.get('revisionId')
    previous = doc_text(doc, args.ignore_prefix)
    started = time.monotonic()

    # With --state, the baseline persists across runs, so edits made while no
    # watcher was running are still reported instead of being silently absorbed
    # into a fresh baseline.
    state_path = Path(args.state) if args.state else None
    if state_path and state_path.exists():
        saved = json.loads(state_path.read_text())
        if saved.get('doc_id') == doc_id:
            previous = saved.get('text', previous)
            revision = saved.get('revision')

    def save_state(rev: str | None, text: str) -> None:
        write_state(args.state, doc_id, rev, text)

    # Status goes to stderr: under a Monitor, every stdout line becomes a
    # notification, and the startup banner is not an event worth waking for.
    print(f"watching '{doc.get('title')}' every {args.interval}s",
          file=sys.stderr, flush=True)

    # Report anything missed since the saved baseline before polling.
    current = doc_text(doc, args.ignore_prefix)
    if current != previous:
        missed = list(difflib.unified_diff(
            previous.split('\n'), current.split('\n'),
            fromfile='before', tofile='after', lineterm='', n=args.context))
        if missed:
            print(f"\n=== {datetime.now().strftime('%H:%M:%S')} "
                  f"(missed while not watching) ===", flush=True)
            print('\n'.join(missed), flush=True)
        previous = current
        revision = doc.get('revisionId')
        save_state(revision, previous)
        if args.once:
            return 0
    save_state(revision, previous)

    pending: str | None = None   # text seen but not yet reported (debouncing)
    quiet_since = 0.0

    while True:
        if args.timeout and time.monotonic() - started >= args.timeout:
            print('watch: timeout reached', file=sys.stderr, flush=True)
            return 0
        time.sleep(args.interval)

        try:
            doc = service.documents().get(documentId=doc_id).execute()
        except HttpError as exc:
            print(f'watch: fetch failed, retrying: {exc}', file=sys.stderr, flush=True)
            continue

        # Re-read the state file each poll: a writer (our own `append --state`)
        # may have re-baselined it since we started. Without this a persistent
        # watcher keeps an in-memory baseline and wakes on our own writes.
        if state_path and state_path.exists():
            saved = json.loads(state_path.read_text())
            if saved.get('doc_id') == doc_id and saved.get('text') != previous:
                previous = saved.get('text', previous)
                revision = saved.get('revision')

        if doc.get('revisionId') != revision:
            # Change seen. With --debounce, hold it until the doc goes quiet, so
            # a diff is reported once the user stops typing rather than mid-word.
            revision = doc.get('revisionId')
            pending = doc_text(doc, args.ignore_prefix)
            quiet_since = time.monotonic()
            # Stamp on sight, before any debounce: proof of receipt should not
            # wait on the reading cadence.
            if args.receipt and pending != previous:
                try:
                    stamp_receipt(service, doc_id, args.receipt)
                    revision = service.documents().get(
                        documentId=doc_id).execute().get('revisionId')
                except HttpError as exc:
                    print(f'watch: receipt failed: {exc}',
                          file=sys.stderr, flush=True)
            if args.debounce:
                continue

        if pending is None:
            continue
        if args.debounce and time.monotonic() - quiet_since < args.debounce:
            continue

        current = pending
        pending = None
        previous_lines = previous.split('\n')

        diff = list(difflib.unified_diff(
            previous.split('\n'), current.split('\n'),
            fromfile='before', tofile='after', lineterm='', n=args.context))
        # A write that landed between our fetch and the writer's re-baseline
        # would otherwise surface as a spurious diff; drop it if the state file
        # already matches what we just read.
        if diff and state_path and state_path.exists():
            saved = json.loads(state_path.read_text())
            if saved.get('doc_id') == doc_id and saved.get('text') == current:
                diff = []

        previous = current
        save_state(revision, previous)
        if not diff:
            continue

        stamp = datetime.now().strftime('%H:%M:%S')
        print(f'\n=== {stamp} ===', flush=True)
        print('\n'.join(annotate_diff(diff, previous_lines)), flush=True)

        if args.once:
            return 0
