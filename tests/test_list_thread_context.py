"""Tests for the thread context `list` prints under each row."""

import argparse
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import commands


def message(msg_id, thread_id, sender='Alice <alice@example.com>',
            subject='Subject', date_ms=1_700_000_000_000, snippet=''):
    return {
        'id': msg_id,
        'threadId': thread_id,
        'internalDate': str(date_ms),
        'snippet': snippet,
        'payload': {'headers': [
            {'name': 'From', 'value': sender},
            {'name': 'Subject', 'value': subject},
        ]},
    }


def fake_service(rows, threads):
    """rows: [(msg_id, thread_id)] as messages.list returns them.

    threads: {thread_id: [message, ...]} as threads.get returns them.
    """
    service = MagicMock()

    service.users.return_value.messages.return_value.list.return_value.execute.return_value = {
        'messages': [{'id': msg_id, 'threadId': tid} for msg_id, tid in rows]
    }

    def get_thread(userId, id, format, metadataHeaders=None):
        return MagicMock(
            execute=MagicMock(return_value={'id': id, 'messages': threads[id]}))

    service.users.return_value.threads.return_value.get.side_effect = get_thread
    return service


def run(monkeypatch, service, ids_only=False):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(account=None, query='', limit=10, ids_only=ids_only)
    return commands.cmd_list(args)


def test_row_reports_its_place_in_the_thread(monkeypatch, capsys):
    thread = [
        message('m1', 't1', date_ms=1_700_000_000_000),
        message('m2', 't1', date_ms=1_700_000_100_000),
        message('m3', 't1', date_ms=1_700_000_200_000),
    ]
    service = fake_service([('m1', 't1')], {'t1': thread})

    assert run(monkeypatch, service) == 0

    out = capsys.readouterr().out
    assert 'Thread: t1 · 3 msgs · 2 newer in thread' in out
    assert '→ gmail thread t1' in out


def test_newest_message_says_so(monkeypatch, capsys):
    thread = [
        message('m1', 't1', date_ms=1_700_000_000_000),
        message('m2', 't1', date_ms=1_700_000_100_000),
    ]
    service = fake_service([('m2', 't1')], {'t1': thread})

    run(monkeypatch, service)

    assert 'Thread: t1 · 2 msgs · this is the latest' in capsys.readouterr().out


def test_position_comes_from_time_not_api_order(monkeypatch, capsys):
    """The claim is about time, so an out-of-order thread must not invert it."""
    thread = [
        message('m2', 't1', date_ms=1_700_000_100_000),
        message('m1', 't1', date_ms=1_700_000_000_000),
    ]
    service = fake_service([('m1', 't1')], {'t1': thread})

    run(monkeypatch, service)

    assert '1 newer in thread' in capsys.readouterr().out


def test_single_message_thread_stays_quiet(monkeypatch, capsys):
    """Most of an inbox is threads of one; a Thread line on each buries the rest."""
    service = fake_service(
        [('m1', 't1')], {'t1': [message('m1', 't1', snippet='Just the one.')]})

    run(monkeypatch, service)

    out = capsys.readouterr().out
    assert 'Thread:' not in out
    assert 'gmail thread' not in out
    assert '"Just the one."' in out


def test_snippet_is_unescaped_and_truncated(monkeypatch, capsys):
    long_snippet = 'It doesn&#39;t fit &amp; ' + 'x' * 200
    service = fake_service(
        [('m1', 't1')], {'t1': [message('m1', 't1', snippet=long_snippet)]})

    run(monkeypatch, service)

    quoted = [line for line in capsys.readouterr().out.splitlines()
              if line.strip().startswith('"')][0].strip()
    assert quoted.startswith('"It doesn\'t fit & xxx')
    assert quoted.endswith('…"')
    assert len(quoted.strip('"')) == 81  # 80 characters plus the ellipsis


def test_one_thread_fetch_per_distinct_thread(monkeypatch):
    """Two rows of one conversation cost one call, and no per-message gets."""
    thread = [message('m1', 't1', date_ms=1), message('m2', 't1', date_ms=2)]
    service = fake_service([('m1', 't1'), ('m2', 't1')], {'t1': thread})

    run(monkeypatch, service)

    assert service.users.return_value.threads.return_value.get.call_count == 1
    service.users.return_value.messages.return_value.get.assert_not_called()


def test_falls_back_when_the_thread_is_unreadable(monkeypatch, capsys):
    """Losing the context must not lose the row."""
    service = fake_service([('m1', 't1')], {})
    service.users.return_value.threads.return_value.get.side_effect = HttpError(
        MagicMock(status=404, reason='Not Found'), b'{"error": "notFound"}')
    service.users.return_value.messages.return_value.get.return_value.execute.return_value = (
        message('m1', 't1', subject='Still listed'))

    assert run(monkeypatch, service) == 0

    captured = capsys.readouterr()
    assert 'Subject: Still listed' in captured.out
    assert 'Thread:' not in captured.out
    assert 'Could not read thread t1' in captured.err


def test_ids_only_makes_no_thread_calls(monkeypatch, capsys):
    service = fake_service([('m1', 't1')], {'t1': [message('m1', 't1')]})

    assert run(monkeypatch, service, ids_only=True) == 0

    assert capsys.readouterr().out == 'm1\n'
    service.users.return_value.threads.return_value.get.assert_not_called()
