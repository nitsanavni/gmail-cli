"""Tests for the filters and forwarding commands."""

import argparse
from unittest.mock import MagicMock

import pytest
from googleapiclient.errors import HttpError

import settings_commands


def fake_service(filters=None, forwarding=None, labels=None):
    """A Gmail service with canned filters, forwarding addresses, and labels.

    `forwarding` is address -> verificationStatus; `labels` is name -> id.
    """
    service = MagicMock()

    settings = service.users.return_value.settings.return_value
    settings.filters.return_value.list.return_value.execute.return_value = {
        'filter': list(filters or [])
    }
    settings.filters.return_value.create.return_value.execute.return_value = {
        'id': 'new-filter'
    }
    settings.forwardingAddresses.return_value.list.return_value.execute.return_value = {
        'forwardingAddresses': [
            {'forwardingEmail': email, 'verificationStatus': status}
            for email, status in (forwarding or {}).items()
        ]
    }

    label_map = dict(labels or {})
    service.users.return_value.labels.return_value.list.return_value.execute.return_value = {
        'labels': [{'name': name, 'id': label_id, 'type': 'user'}
                   for name, label_id in label_map.items()]
    }
    service._labels = label_map
    return service


def add_args(**overrides):
    """Namespace for `filters add` with every flag defaulted to unset."""
    args = argparse.Namespace(
        account=None, from_=None, to=None, subject=None, query=None,
        not_query=None, has_attachment=False, forward=None, label=None,
        archive=False, mark_read=False,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


@pytest.fixture
def authed(monkeypatch):
    """Install a fake service as the authenticated one; return the installer."""
    def install(service):
        monkeypatch.setattr(settings_commands, 'authenticate', lambda account: service)
        return service
    return install


def created_body(service):
    settings = service.users.return_value.settings.return_value
    return settings.filters.return_value.create.call_args.kwargs['body']


def test_repeated_from_is_or_joined_into_one_criterion(authed):
    """Gmail stores multiple senders as one query string, as its own UI does."""
    service = authed(fake_service(forwarding={'lihu@askeffi.ai': 'accepted'}))

    args = add_args(from_=['a@x.com', 'b@y.com'], has_attachment=True,
                    forward='lihu@askeffi.ai')
    assert settings_commands.cmd_filters_add(args) == 0

    assert created_body(service)['criteria'] == {
        'from': 'a@x.com OR b@y.com',
        'hasAttachment': True,
    }


def test_forward_to_pending_address_is_refused_before_the_api_call(authed, capsys):
    """A pending address yields a 400 from Gmail; say why instead."""
    service = authed(fake_service(forwarding={'lihu@askeffi.ai': 'pending'}))

    args = add_args(from_=['a@x.com'], forward='lihu@askeffi.ai')
    assert settings_commands.cmd_filters_add(args) == 1

    settings = service.users.return_value.settings.return_value
    settings.filters.return_value.create.assert_not_called()
    assert 'pending' in capsys.readouterr().err


def test_forward_to_unregistered_address_is_refused(authed, capsys):
    service = authed(fake_service(forwarding={}))

    args = add_args(from_=['a@x.com'], forward='nobody@askeffi.ai')
    assert settings_commands.cmd_filters_add(args) == 1
    assert 'gmail forwarding add nobody@askeffi.ai' in capsys.readouterr().err


def test_filter_without_criteria_is_refused(authed, capsys):
    service = authed(fake_service(forwarding={'lihu@askeffi.ai': 'accepted'}))

    assert settings_commands.cmd_filters_add(add_args(archive=True)) == 1

    settings = service.users.return_value.settings.return_value
    settings.filters.return_value.create.assert_not_called()
    assert 'at least one criterion' in capsys.readouterr().err


def test_filter_without_action_is_refused(authed, capsys):
    service = authed(fake_service())

    assert settings_commands.cmd_filters_add(add_args(from_=['a@x.com'])) == 1

    settings = service.users.return_value.settings.return_value
    settings.filters.return_value.create.assert_not_called()
    assert 'at least one action' in capsys.readouterr().err


def test_label_action_resolves_names_to_ids_and_creates_missing(authed):
    service = authed(fake_service(labels={'accounting': 'Label_9'}))

    args = add_args(from_=['a@x.com'], label=['accounting'], archive=True,
                    mark_read=True)
    assert settings_commands.cmd_filters_add(args) == 0

    action = created_body(service)['action']
    assert action['addLabelIds'] == ['Label_9']
    assert action['removeLabelIds'] == ['INBOX', 'UNREAD']


def test_list_renders_label_ids_by_name(authed, capsys):
    service = authed(fake_service(
        filters=[{
            'id': 'f1',
            'criteria': {'from': 'a@x.com', 'hasAttachment': True},
            'action': {'forward': 'lihu@askeffi.ai', 'addLabelIds': ['Label_9']},
        }],
        labels={'accounting': 'Label_9'},
    ))

    assert settings_commands.cmd_filters_list(argparse.Namespace(account=None)) == 0

    out = capsys.readouterr().out
    assert 'f1' in out
    assert '+accounting' in out
    assert 'forward->lihu@askeffi.ai' in out


def test_forwarding_list_reports_verification_status(authed, capsys):
    authed(fake_service(forwarding={'lihu@askeffi.ai': 'pending'}))

    assert settings_commands.cmd_forwarding_list(argparse.Namespace(account=None)) == 0
    assert 'lihu@askeffi.ai\tpending' in capsys.readouterr().out


def test_forwarding_add_403_points_at_the_settings_ui(authed, capsys):
    """Google allows this write only from a domain-wide-delegated service account.

    Re-consenting cannot fix it, so the error has to name the manual path.
    """
    service = authed(fake_service())
    settings = service.users.return_value.settings.return_value
    settings.forwardingAddresses.return_value.create.return_value.execute.side_effect = (
        HttpError(MagicMock(status=403), b'domain-wide authority')
    )

    args = argparse.Namespace(account=None, email='lihu@askeffi.ai')
    assert settings_commands.cmd_forwarding_add(args) == 1

    err = capsys.readouterr().err
    assert 'Forwarding and POP/IMAP' in err
    assert 'lihu@askeffi.ai' in err


def test_forwarding_add_says_the_link_must_be_clicked(authed, capsys):
    service = authed(fake_service())
    settings = service.users.return_value.settings.return_value
    settings.forwardingAddresses.return_value.create.return_value.execute.return_value = {
        'forwardingEmail': 'lihu@askeffi.ai', 'verificationStatus': 'pending'
    }

    args = argparse.Namespace(account=None, email='lihu@askeffi.ai')
    assert settings_commands.cmd_forwarding_add(args) == 0
    assert 'confirmation link' in capsys.readouterr().out
