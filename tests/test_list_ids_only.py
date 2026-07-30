"""Tests for `list --ids-only`, the machine-readable mode poll loops consume."""

import argparse
from unittest.mock import MagicMock

import commands


def fake_service(ids):
    """A Gmail service whose messages.list returns `ids`."""
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.list.return_value.execute.return_value = {
        'messages': [{'id': i, 'threadId': f't-{i}'} for i in ids]
    }
    return service


def run(monkeypatch, service, ids_only=True, query='has:attachment'):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(account=None, query=query, limit=10, ids_only=ids_only)
    return commands.cmd_list(args)


def test_prints_one_id_per_line(monkeypatch, capsys):
    service = fake_service(['m1', 'm2', 'm3'])

    assert run(monkeypatch, service) == 0

    assert capsys.readouterr().out == 'm1\nm2\nm3\n'


def test_no_matches_prints_nothing(monkeypatch, capsys):
    """A `for id in $(...)` loop must iterate zero times, not once over prose."""
    service = fake_service([])

    assert run(monkeypatch, service) == 0

    assert capsys.readouterr().out == ''


def test_skips_the_per_message_metadata_fetch(monkeypatch):
    """The whole point: N ids cost one round-trip, not N + 1."""
    service = fake_service(['m1', 'm2'])

    assert run(monkeypatch, service) == 0

    service.users.return_value.messages.return_value.get.assert_not_called()


def test_default_mode_is_unchanged(monkeypatch, capsys):
    service = fake_service([])

    assert run(monkeypatch, service, ids_only=False) == 0

    assert 'No messages found.' in capsys.readouterr().out
