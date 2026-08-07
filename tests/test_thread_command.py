"""Tests for `gmail thread` — the structure level between list and read."""

import argparse
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import commands


def part(filename='', attachment_id=None, mime='application/octet-stream', parts=None):
    node = {'filename': filename, 'mimeType': mime, 'body': {}}
    if attachment_id:
        node['body']['attachmentId'] = attachment_id
    if parts:
        node['parts'] = parts
    return node


def message(msg_id, thread_id='t1', sender='Alice <alice@example.com>',
            subject='Subject', date_ms=1_700_000_000_000, snippet='',
            labels=None, payload=None):
    node = payload or part()
    node['headers'] = [
        {'name': 'From', 'value': sender},
        {'name': 'Subject', 'value': subject},
    ]
    return {
        'id': msg_id,
        'threadId': thread_id,
        'internalDate': str(date_ms),
        'snippet': snippet,
        'labelIds': labels or [],
        'payload': node,
    }


def not_found():
    return HttpError(MagicMock(status=404, reason='Not Found'), b'{"error": "notFound"}')


def fake_service(threads, message_lookup=None):
    """threads: {thread_id: [message, ...]}. message_lookup: {msg_id: {'threadId': ...}}."""
    service = MagicMock()

    def get_thread(userId, id, format, metadataHeaders=None):
        if id not in threads:
            raise not_found()
        return MagicMock(
            execute=MagicMock(return_value={'id': id, 'messages': threads[id]}))

    def get_message(userId, id, format, metadataHeaders=None):
        if id not in (message_lookup or {}):
            raise not_found()
        return MagicMock(execute=MagicMock(return_value=message_lookup[id]))

    service.users.return_value.threads.return_value.get.side_effect = get_thread
    service.users.return_value.messages.return_value.get.side_effect = get_message
    return service


def run(monkeypatch, service, ident='t1'):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    return commands.cmd_thread(argparse.Namespace(account=None, id=ident))


def test_prints_header_lines_and_the_next_step(monkeypatch, capsys):
    service = fake_service({'t1': [
        message('m1', subject='AskEffi Feedback', date_ms=1_700_000_000_000,
                sender='Guy <guy@askeffi.ai>', snippet='Team - can you have a look?'),
        message('m2', subject='Re: AskEffi Feedback', date_ms=1_700_000_100_000,
                sender='Lihu <lihu@askeffi.ai>', snippet='On it.'),
    ]})

    assert run(monkeypatch, service) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == 'Thread: t1 · "AskEffi Feedback" · 2 messages'
    assert lines[1].startswith('[1] m1 · ')
    assert lines[1].endswith(' · Guy <guy@askeffi.ai>')
    assert lines[2] == '    "Team - can you have a look?"'
    assert lines[3].startswith('[2] m2 · ')
    # The hint carries a real id, not a placeholder — the last message's.
    assert lines[-1] == '→ gmail read m2 · gmail materialize m2 -o <dir>'


def test_bodies_are_never_printed(monkeypatch, capsys):
    """Structure level: snippets only, however full the payload we fetched is."""
    payload = part(mime='multipart/mixed', parts=[part(mime='text/plain')])
    payload['parts'][0]['body'] = {'data': 'aGlkZGVuIGJvZHkgdGV4dA=='}
    service = fake_service({'t1': [message('m1', payload=payload, snippet='visible')]})

    run(monkeypatch, service)

    out = capsys.readouterr().out
    assert 'hidden body text' not in out
    assert '"visible"' in out


def test_attachment_and_unread_badges(monkeypatch, capsys):
    payload = part(mime='multipart/mixed', parts=[
        part(mime='multipart/related', parts=[
            part('screenshot.png', 'a1', mime='image/png'),
        ]),
        part('report.pdf', 'a2', mime='application/pdf'),
    ])
    service = fake_service({'t1': [
        message('m1', payload=payload, labels=['INBOX', 'UNREAD']),
        message('m2', date_ms=1_700_000_100_000, labels=['INBOX']),
    ]})

    run(monkeypatch, service)

    lines = capsys.readouterr().out.splitlines()
    assert lines[1].endswith(' · 📎 2 · unread')
    assert '📎' not in lines[2]
    assert 'unread' not in lines[2]


def test_orders_messages_by_time(monkeypatch, capsys):
    service = fake_service({'t1': [
        message('m2', date_ms=1_700_000_100_000),
        message('m1', date_ms=1_700_000_000_000),
    ]})

    run(monkeypatch, service)

    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith('[1] m1 · ')
    assert lines[2].startswith('[2] m2 · ')


def test_accepts_a_message_id(monkeypatch, capsys):
    """Every other command prints message ids, so that is what a caller holds."""
    service = fake_service(
        {'t1': [message('m1'), message('m9', date_ms=1_700_000_100_000)]},
        message_lookup={'m9': {'id': 'm9', 'threadId': 't1'}},
    )

    assert run(monkeypatch, service, ident='m9') == 0

    assert capsys.readouterr().out.startswith('Thread: t1 · ')


def test_unknown_id_exits_nonzero(monkeypatch, capsys):
    service = fake_service({})

    assert run(monkeypatch, service, ident='nope') == 1
    assert 'no thread or message with id nope' in capsys.readouterr().err
