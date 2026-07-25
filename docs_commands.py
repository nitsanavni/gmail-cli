"""Google Docs command handlers for Gmail CLI.

The Docs API inserts plain text only, so markdown-ish source is parsed into
(plain text + styling ranges) and the styling is re-applied as batch requests.
"""

import argparse
import sys

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
                'range': {'startIndex': at + op['start'],
                          'endIndex': at + op['end']},
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

    print(f"Appended {len(text)} chars to '{doc.get('title')}'")
    print(f'https://docs.google.com/document/d/{doc_id}/edit')
    return 0
