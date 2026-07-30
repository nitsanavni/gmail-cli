"""Tests for the label and labels commands."""

import argparse
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import commands


def fake_service(existing=None, create_fails=False):
    """A Gmail service whose label list is `existing` (name -> id).

    Created labels are appended to the same dict, so a create followed by a
    lookup behaves the way the real API does.
    """
    existing = dict(existing or {})
    service = MagicMock()
    labels = service.users.return_value.labels.return_value

    labels.list.return_value.execute.return_value = {
        'labels': [{'name': name, 'id': label_id, 'type': 'user'}
                   for name, label_id in existing.items()]
    }

    def create(userId, body):
        name = body['name']
        label_id = f'Label_{len(existing) + 1}'
        existing[name] = label_id
        return MagicMock(execute=MagicMock(return_value={'id': label_id, 'name': name}))

    labels.create.side_effect = create
    service._labels = existing
    return service


def run(monkeypatch, service, add=None, remove=None, msg_id='m1'):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(account=None, id=msg_id, add=add, remove=remove)
    return commands.cmd_label(args)


def modify_body(service):
    return service.users.return_value.messages.return_value.modify.call_args.kwargs['body']


def test_add_creates_a_missing_label(monkeypatch):
    service = fake_service({'INBOX': 'INBOX'})

    assert run(monkeypatch, service, add=['factory/seen']) == 0

    created = service.users.return_value.labels.return_value.create.call_args.kwargs
    assert created['body']['name'] == 'factory/seen'
    assert modify_body(service) == {'addLabelIds': [service._labels['factory/seen']]}


def test_add_reuses_an_existing_label(monkeypatch):
    service = fake_service({'factory/seen': 'Label_7'})

    assert run(monkeypatch, service, add=['factory/seen']) == 0

    service.users.return_value.labels.return_value.create.assert_not_called()
    assert modify_body(service) == {'addLabelIds': ['Label_7']}


def test_add_and_remove_in_one_call(monkeypatch):
    service = fake_service({'factory/done': 'Label_3', 'UNREAD': 'UNREAD'})

    assert run(monkeypatch, service, add=['factory/done'], remove=['UNREAD']) == 0

    assert modify_body(service) == {
        'addLabelIds': ['Label_3'],
        'removeLabelIds': ['UNREAD'],
    }


def test_removing_an_unknown_label_is_a_no_op(monkeypatch, capsys):
    service = fake_service({'INBOX': 'INBOX'})

    assert run(monkeypatch, service, remove=['factory/never-existed']) == 0

    service.users.return_value.messages.return_value.modify.assert_not_called()
    assert 'nothing to remove' in capsys.readouterr().err


def test_requires_add_or_remove(monkeypatch, capsys):
    service = fake_service()

    assert run(monkeypatch, service) == 1
    assert '--add or --remove required' in capsys.readouterr().err


def test_unknown_message_id_exits_nonzero(monkeypatch, capsys):
    service = fake_service({'factory/seen': 'Label_1'})
    service.users.return_value.messages.return_value.modify.side_effect = HttpError(
        MagicMock(status=404, reason='Not Found'), b'{"error": "notFound"}')

    assert run(monkeypatch, service, add=['factory/seen'], msg_id='nope') == 1
    assert 'cannot modify message nope' in capsys.readouterr().err


def test_labels_lists_system_labels_first(monkeypatch, capsys):
    service = MagicMock()
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        'labels': [
            {'name': 'factory/seen', 'id': 'Label_1', 'type': 'user'},
            {'name': 'INBOX', 'id': 'INBOX', 'type': 'system'},
        ]
    }
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)

    assert commands.cmd_labels(argparse.Namespace(account=None)) == 0

    lines = capsys.readouterr().out.splitlines()
    assert lines == ['INBOX\tINBOX', 'factory/seen\tLabel_1']
