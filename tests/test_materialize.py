"""Tests for materializing an email into a directory."""

import argparse
import base64
import json
from unittest.mock import MagicMock

from googleapiclient.errors import HttpError

import commands


def make_part(filename='', attachment_id=None, mime='application/octet-stream',
              parts=None, body_text=None):
    part = {'filename': filename, 'mimeType': mime, 'body': {}}
    if attachment_id:
        part['body']['attachmentId'] = attachment_id
    if body_text is not None:
        part['body']['data'] = base64.urlsafe_b64encode(body_text.encode()).decode()
    if parts:
        part['parts'] = parts
    return part


def make_message(payload, msg_id='m1', thread_id='t1', internal_date='1753876543000',
                 labels=None):
    return {
        'id': msg_id,
        'threadId': thread_id,
        'internalDate': internal_date,
        'labelIds': labels if labels is not None else ['INBOX', 'UNREAD'],
        'payload': payload,
    }


def fake_service(message, data=None):
    data = data or {}
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = message
    messages.attachments.return_value.get.side_effect = (
        lambda userId, messageId, id: MagicMock(
            execute=MagicMock(
                return_value={'data': base64.urlsafe_b64encode(data[id]).decode()})
        )
    )
    return service


def run(monkeypatch, message, data, output, service=None):
    service = service or fake_service(message, data)
    monkeypatch.setattr(commands, 'authenticate', lambda account: service)
    args = argparse.Namespace(account=None, id='m1', output=str(output))
    return commands.cmd_materialize(args)


def headers(**pairs):
    return [{'name': name, 'value': value} for name, value in pairs.items()]


def test_writes_complete_envelope(tmp_path, monkeypatch):
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='text/plain', body_text='Hello there.'),
        make_part('report.pdf', 'a1', mime='application/pdf'),
    ])
    payload['headers'] = headers(**{
        'From': 'Alice <alice@example.com>',
        'To': 'bob@example.com',
        'Cc': 'carol@example.com',
        'Subject': 'Quarterly numbers',
    })
    outdir = tmp_path / 'event'

    assert run(monkeypatch, make_message(payload), {'a1': b'PDF'}, outdir) == 0

    envelope = json.loads((outdir / 'envelope.json').read_text())
    assert envelope == {
        'source': 'gmail-cli',
        'id': 'm1',
        'thread_id': 't1',
        'ts': '2025-07-30T11:55:43Z',
        'from': 'Alice <alice@example.com>',
        'to': 'bob@example.com',
        'cc': 'carol@example.com',
        'subject': 'Quarterly numbers',
        'labels': ['INBOX', 'UNREAD'],
        'body_markdown': 'Hello there.',
        'attachments': [
            {'filename': 'report.pdf', 'mime_type': 'application/pdf', 'size': 3},
        ],
    }
    assert (outdir / 'attachments' / 'report.pdf').read_bytes() == b'PDF'


def test_body_falls_back_to_html_as_markdown(tmp_path, monkeypatch):
    payload = make_part(mime='multipart/alternative', parts=[
        make_part(mime='text/html', body_text='<h1>Title</h1><p>Body <b>text</b>.</p>'),
    ])
    payload['headers'] = headers(Subject='HTML only')
    outdir = tmp_path / 'event'

    run(monkeypatch, make_message(payload), {}, outdir)

    body = json.loads((outdir / 'envelope.json').read_text())['body_markdown']
    assert 'Title\n=====' in body
    assert '**text**' in body


def test_downloads_nested_inline_image(tmp_path, monkeypatch):
    """The pasted-screenshot shape: image nested under multipart/related."""
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='multipart/related', parts=[
            make_part(mime='multipart/alternative', parts=[
                make_part(mime='text/plain', body_text='see below'),
                make_part(mime='text/html', body_text='<p>see below</p>'),
            ]),
            make_part('screenshot.png', 'img1', mime='image/png'),
        ]),
        make_part('report.pdf', 'a1', mime='application/pdf'),
    ])
    payload['headers'] = headers(Subject='With a screenshot')
    outdir = tmp_path / 'event'

    run(monkeypatch, make_message(payload), {'img1': b'PNG', 'a1': b'PDF'}, outdir)

    assert (outdir / 'attachments' / 'screenshot.png').read_bytes() == b'PNG'
    assert (outdir / 'attachments' / 'report.pdf').read_bytes() == b'PDF'
    names = [a['filename']
             for a in json.loads((outdir / 'envelope.json').read_text())['attachments']]
    assert names == ['screenshot.png', 'report.pdf']


def test_rerun_is_idempotent(tmp_path, monkeypatch):
    """Re-materializing overwrites in place instead of accumulating '-1' copies."""
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='text/plain', body_text='body'),
        make_part('report.pdf', 'a1', mime='application/pdf'),
        make_part('report.pdf', 'a2', mime='application/pdf'),
    ])
    payload['headers'] = headers(Subject='Twice')
    outdir = tmp_path / 'event'

    run(monkeypatch, make_message(payload), {'a1': b'first', 'a2': b'second'}, outdir)
    first = (outdir / 'envelope.json').read_text()

    run(monkeypatch, make_message(payload), {'a1': b'first', 'a2': b'second'}, outdir)

    assert (outdir / 'envelope.json').read_text() == first
    assert sorted(p.name for p in (outdir / 'attachments').iterdir()) == [
        'report-1.pdf', 'report.pdf']
    assert (outdir / 'attachments' / 'report.pdf').read_bytes() == b'first'
    assert (outdir / 'attachments' / 'report-1.pdf').read_bytes() == b'second'


def test_creates_missing_parent_directories(tmp_path, monkeypatch):
    payload = make_part(mime='text/plain', body_text='hi')
    payload['headers'] = headers(Subject='Plain')
    outdir = tmp_path / 'does' / 'not' / 'exist'

    run(monkeypatch, make_message(payload), {}, outdir)

    assert (outdir / 'envelope.json').exists()
    assert (outdir / 'attachments').is_dir()


def test_unknown_message_id_exits_nonzero(tmp_path, monkeypatch, capsys):
    service = MagicMock()
    service.users.return_value.messages.return_value.get.return_value.execute.side_effect = (
        HttpError(MagicMock(status=404, reason='Not Found'), b'{"error": "notFound"}')
    )
    outdir = tmp_path / 'event'

    assert run(monkeypatch, None, {}, outdir, service=service) == 1
    assert 'cannot read message m1' in capsys.readouterr().err
    assert not outdir.exists()


def test_iso_timestamp_keeps_milliseconds():
    assert commands.iso_timestamp('1753876543123') == '2025-07-30T11:55:43.123000Z'
    assert commands.iso_timestamp('0') == '1970-01-01T00:00:00Z'
