"""Tests for what `read` discloses beyond the body: thread position, attachments."""

import argparse
import base64
from unittest.mock import MagicMock

import commands


def part(filename='', attachment_id=None, mime='application/octet-stream',
         parts=None, body_text=None, size=None):
    node = {'filename': filename, 'mimeType': mime, 'body': {}}
    if attachment_id:
        node['body']['attachmentId'] = attachment_id
    if size is not None:
        node['body']['size'] = size
    if body_text is not None:
        node['body']['data'] = base64.urlsafe_b64encode(body_text.encode()).decode()
    if parts:
        node['parts'] = parts
    return node


def message(msg_id='m1', thread_id='t1', payload=None, date_ms=1_700_000_000_000):
    node = payload or part(mime='text/plain', body_text='Body text.')
    node.setdefault('headers', [
        {'name': 'From', 'value': 'Alice <alice@example.com>'},
        {'name': 'To', 'value': 'bob@example.com'},
        {'name': 'Subject', 'value': 'Subject'},
    ])
    return {
        'id': msg_id,
        'threadId': thread_id,
        'internalDate': str(date_ms),
        'payload': node,
    }


def sibling(msg_id, date_ms):
    return {'id': msg_id, 'internalDate': str(date_ms)}


def fake_service(messages, siblings=None):
    """messages: {msg_id: full message}. siblings: {thread_id: [metadata message]}."""
    service = MagicMock()

    service.users.return_value.messages.return_value.get.side_effect = (
        lambda userId, id, format, metadataHeaders=None: MagicMock(
            execute=MagicMock(return_value=messages[id]))
    )
    service.users.return_value.threads.return_value.get.side_effect = (
        lambda userId, id, format, metadataHeaders=None: MagicMock(
            execute=MagicMock(
                return_value={'id': id, 'messages': (siblings or {}).get(id, [])}))
    )
    return service


def run(monkeypatch, service, ids, *, show_parts=False, part_number=None, query=None):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(
        account=None,
        ids=ids,
        query=query,
        limit=10,
        parts=show_parts,
        part=part_number,
    )
    return commands.cmd_read(args)


def alternative_payload():
    return part(mime='multipart/mixed', size=0, parts=[
        part(mime='multipart/alternative', size=0, parts=[
            part(mime='text/plain', body_text='The old plain text.', size=902),
            part(mime='text/html', body_text='<p>The changed HTML.</p>', size=47_309),
        ]),
        part('Invoice-WHOTRWQL-0028.pdf', 'pdf1', mime='application/pdf', size=32_768),
    ])


def test_thread_id_line_carries_the_position(monkeypatch, capsys):
    siblings = {'t1': [sibling(f'm{n}', 1_700_000_000_000 + n) for n in range(1, 7)]}
    service = fake_service({'m5': message('m5')}, siblings)

    assert run(monkeypatch, service, ['m5']) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == 'Thread-ID: t1 (message 5 of 6 · 1 newer)'
    assert lines[2] == '→ gmail thread t1'


def test_newest_message_reads_as_latest(monkeypatch, capsys):
    siblings = {'t1': [sibling('m1', 1), sibling('m2', 2)]}
    service = fake_service({'m2': message('m2')}, siblings)

    run(monkeypatch, service, ['m2'])

    assert 'Thread-ID: t1 (message 2 of 2 · latest)' in capsys.readouterr().out


def test_single_message_thread_prints_the_old_header(monkeypatch, capsys):
    """A message with no conversation around it must read exactly as before."""
    service = fake_service({'m1': message('m1')}, {'t1': [sibling('m1', 1)]})

    run(monkeypatch, service, ['m1'])

    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == 'Thread-ID: t1'
    assert lines[2].startswith('From: ')
    assert 'gmail thread' not in capsys.readouterr().out


def test_one_thread_fetch_per_distinct_thread(monkeypatch):
    siblings = {'t1': [sibling('m1', 1), sibling('m2', 2)]}
    service = fake_service({'m1': message('m1'), 'm2': message('m2')}, siblings)

    run(monkeypatch, service, ['m1', 'm2'])

    assert service.users.return_value.threads.return_value.get.call_count == 1


def test_the_position_lookup_is_a_metadata_fetch(monkeypatch):
    """One line of output must not cost every body in the thread."""
    service = fake_service({'m1': message('m1')}, {'t1': [sibling('m1', 1)]})

    run(monkeypatch, service, ['m1'])

    kwargs = service.users.return_value.threads.return_value.get.call_args.kwargs
    assert kwargs['format'] == 'metadata'
    assert kwargs['metadataHeaders'] == ['From', 'Subject', 'Date']


def test_attachments_are_named_after_the_body(monkeypatch, capsys):
    payload = part(mime='multipart/mixed', parts=[
        part(mime='text/plain', body_text='See attached.'),
        part('image.png', 'a1', mime='image/png', size=53000),
        part('image.png', 'a2', mime='image/png', size=18500),
    ])
    service = fake_service({'m1': message('m1', payload=payload)},
                           {'t1': [sibling('m1', 1)]})

    run(monkeypatch, service, ['m1'])

    lines = capsys.readouterr().out.splitlines()
    assert lines[-3] == '---'
    # Same names materialize would write, so the listing predicts the directory.
    assert lines[-2] == (
        'Attachments (2): image.png (52KB image/png), image-1.png (18KB image/png)')
    assert lines[-1] == '→ gmail materialize m1 -o <dir>'


def test_finds_a_nested_inline_image(monkeypatch, capsys):
    payload = part(mime='multipart/mixed', parts=[
        part(mime='multipart/related', parts=[
            part(mime='text/plain', body_text='see below'),
            part('screenshot.png', 'img1', mime='image/png', size=812),
        ]),
    ])
    service = fake_service({'m1': message('m1', payload=payload)},
                           {'t1': [sibling('m1', 1)]})

    run(monkeypatch, service, ['m1'])

    assert 'Attachments (1): screenshot.png (812B image/png)' in capsys.readouterr().out


def test_clean_email_prints_no_attachment_block(monkeypatch, capsys):
    service = fake_service({'m1': message('m1')}, {'t1': [sibling('m1', 1)]})

    run(monkeypatch, service, ['m1'])

    out = capsys.readouterr().out
    assert 'Attachments' not in out
    assert out.rstrip().endswith('Body text.')


def test_human_size_reads_like_a_file_listing():
    assert commands.human_size(0) == '0B'
    assert commands.human_size(812) == '812B'
    assert commands.human_size(53000) == '52KB'
    assert commands.human_size(5300) == '5.2KB'
    assert commands.human_size(1_500_000) == '1.4MB'


def test_parts_renders_the_nested_tree_in_preorder(monkeypatch, capsys):
    service = fake_service(
        {'m1': message('m1', payload=alternative_payload())},
        {'t1': [sibling('m1', 1)]},
    )

    assert run(monkeypatch, service, ['m1'], show_parts=True) == 0

    tree = capsys.readouterr().out.split('---\n\n', 1)[1]
    assert tree == (
        '  1  multipart/mixed\n'
        '  2    multipart/alternative\n'
        '  3      text/plain  902B\n'
        '  4      text/html  46KB\n'
        '  5    application/pdf  32KB  Invoice-WHOTRWQL-0028.pdf\n'
        '\n'
        '→ gmail read m1 --part 3\n'
    )


def test_part_decodes_the_html_sibling_without_rendering_it(monkeypatch, capsys):
    service = fake_service({'m1': message('m1', payload=alternative_payload())})

    assert run(monkeypatch, service, ['m1'], part_number=4) == 0

    captured = capsys.readouterr()
    assert captured.out == '<p>The changed HTML.</p>'
    assert captured.err == ''


def test_part_out_of_range_names_the_valid_range(monkeypatch, capsys):
    service = fake_service({'m1': message('m1', payload=alternative_payload())})

    assert run(monkeypatch, service, ['m1'], part_number=6) == 1

    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'valid range is 1-5' in captured.err


def test_part_rejects_an_attachment_and_names_the_command(monkeypatch, capsys):
    service = fake_service({'m1': message('m1', payload=alternative_payload())})

    assert run(monkeypatch, service, ['m1'], part_number=5) == 1

    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'part 5 is application/pdf, not text' in captured.err
    assert 'gmail attachments m1' in captured.err


def test_parts_and_part_are_mutually_exclusive(monkeypatch, capsys):
    service = fake_service({'m1': message('m1', payload=alternative_payload())})

    assert run(
        monkeypatch, service, ['m1'], show_parts=True, part_number=3
    ) == 1

    assert '--parts and --part cannot be used together' in capsys.readouterr().err


def test_part_rejects_query_reads_as_ambiguous(monkeypatch, capsys):
    service = fake_service({})

    assert run(monkeypatch, service, [], part_number=1, query='is:unread') == 1

    error = capsys.readouterr().err
    assert 'require exactly one message ID' in error
    assert 'cannot be used with --query' in error
    service.users.return_value.messages.return_value.list.assert_not_called()


def test_parts_rejects_multiple_message_ids(monkeypatch, capsys):
    service = fake_service({})

    assert run(monkeypatch, service, ['m1', 'm2'], show_parts=True) == 1

    assert 'require exactly one message ID' in capsys.readouterr().err
