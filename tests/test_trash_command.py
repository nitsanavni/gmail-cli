"""Tests for the trash command."""

import argparse
import io
from unittest.mock import MagicMock

import commands


def run(monkeypatch, ids, stdin=''):
    service = MagicMock()
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    monkeypatch.setattr(commands.sys, 'stdin', io.StringIO(stdin))
    args = argparse.Namespace(account=None, ids=ids)
    assert commands.cmd_trash(args) == 0
    return service


def trashed_ids(service):
    messages = service.users.return_value.messages.return_value
    return [call.kwargs['id'] for call in messages.trash.call_args_list]


def test_trashes_each_id_on_argv(monkeypatch):
    service = run(monkeypatch, ['m1', 'm2'])

    assert trashed_ids(service) == ['m1', 'm2']


def test_reads_ids_from_stdin_when_argv_is_empty(monkeypatch):
    service = run(monkeypatch, [], stdin='m1\nm2\n\nm3\n')

    assert trashed_ids(service) == ['m1', 'm2', 'm3']


def test_argv_wins_over_stdin(monkeypatch):
    service = run(monkeypatch, ['m1'], stdin='m9\n')

    assert trashed_ids(service) == ['m1']


def test_trashes_rather_than_relabelling(monkeypatch):
    """Trash must hit users.messages.trash, not a modify that only unlabels."""
    service = run(monkeypatch, ['m1'])

    messages = service.users.return_value.messages.return_value
    assert messages.trash.called
    assert not messages.modify.called
