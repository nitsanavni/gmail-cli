"""Tests for the reply command's --to override."""

import argparse
import base64
from unittest.mock import MagicMock

import commands


def fake_service():
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = {
        'threadId': 't1',
        'payload': {'headers': [
            {'name': 'From', 'value': 'Nitsan Avni <nitsanav@gmail.com>'},
            {'name': 'Subject', 'value': 'Re: TEMA'},
            {'name': 'Message-ID', 'value': '<orig@mail>'},
        ]},
    }
    return service


def run_reply(monkeypatch, service, to=None):
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(
        account=None, message_id='m1', to=to, body='hola', file=None,
        draft=True, cc=None, bcc=None, attach=None)
    commands.cmd_reply(args)
    draft_call = service.users.return_value.drafts.return_value.create.call_args
    raw = draft_call.kwargs['body']['message']['raw']
    return base64.urlsafe_b64decode(raw).decode()


def test_reply_defaults_to_original_sender(monkeypatch):
    mime = run_reply(monkeypatch, fake_service())
    assert 'To: Nitsan Avni <nitsanav@gmail.com>' in mime


def test_reply_to_override(monkeypatch):
    mime = run_reply(monkeypatch, fake_service(),
                     to=['fiscal2@sftconsultores.com'])
    assert 'To: fiscal2@sftconsultores.com' in mime
    assert 'nitsanav@gmail.com' not in mime.split('\n\n')[0]
