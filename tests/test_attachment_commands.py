"""Regression tests for attachment download safety."""

import argparse
import base64
from unittest.mock import MagicMock

import pytest

import commands


def make_part(filename='', attachment_id=None, mime='application/octet-stream', parts=None):
    part = {'filename': filename, 'mimeType': mime, 'body': {}}
    if attachment_id:
        part['body']['attachmentId'] = attachment_id
    if parts:
        part['parts'] = parts
    return part


def fake_service(payload, data):
    service = MagicMock()
    messages = service.users.return_value.messages.return_value
    messages.get.return_value.execute.return_value = {'payload': payload}
    messages.attachments.return_value.get.side_effect = (
        lambda userId, messageId, id: MagicMock(
            execute=MagicMock(return_value={'data': base64.urlsafe_b64encode(data[id]).decode()})
        )
    )
    return service


def run(monkeypatch, payload, data, output):
    monkeypatch.setattr(commands, 'authenticate', lambda account: fake_service(payload, data))
    args = argparse.Namespace(account=None, id='m1', output=str(output))
    return commands.cmd_attachments(args)


@pytest.mark.parametrize('hostile,expected', [
    ('../../etc/passwd', 'passwd'),
    ('/etc/cron.d/pwn', 'pwn'),
    ('a/b/c.txt', 'c.txt'),
    ('ok.pdf', 'ok.pdf'),
    ('..', None),
    ('.', None),
    ('', None),
])
def test_safe_filename_strips_paths(hostile, expected):
    assert commands.safe_filename(hostile) == expected


def test_attachment_cannot_escape_output_dir(tmp_path, monkeypatch):
    """A sender-chosen filename must never write outside the output directory."""
    outside = tmp_path / 'outside.txt'
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(f'../../{outside.name}', 'a1'),
        make_part(str(outside), 'a2'),
    ])
    outdir = tmp_path / 'downloads'

    run(monkeypatch, payload, {'a1': b'one', 'a2': b'two'}, outdir)

    assert not outside.exists(), 'attachment escaped the output directory'
    assert {p.name for p in outdir.iterdir()} == {'outside.txt', 'outside-1.txt'}


def test_finds_attachments_nested_in_subparts(tmp_path, monkeypatch):
    """Attachments below the top level must still be found."""
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='multipart/related', parts=[
            make_part(mime='multipart/alternative', parts=[
                make_part('deep.pdf', 'a1'),
            ]),
        ]),
    ])
    outdir = tmp_path / 'out'

    run(monkeypatch, payload, {'a1': b'deep'}, outdir)

    assert (outdir / 'deep.pdf').read_bytes() == b'deep'


def test_finds_inline_image_under_multipart_related(tmp_path, monkeypatch):
    """A screenshot pasted into the body arrives as an inline image part.

    Gmail nests it as multipart/mixed -> multipart/related -> image/png, with the
    text body under a sibling multipart/alternative. Walking only the top level
    finds nothing at all here.
    """
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='multipart/related', parts=[
            make_part(mime='multipart/alternative', parts=[
                make_part(mime='text/plain'),
                make_part(mime='text/html'),
            ]),
            make_part('screenshot.png', 'img1', mime='image/png'),
        ]),
        make_part('report.pdf', 'a1', mime='application/pdf'),
    ])
    outdir = tmp_path / 'out'

    run(monkeypatch, payload, {'img1': b'PNG', 'a1': b'PDF'}, outdir)

    assert (outdir / 'screenshot.png').read_bytes() == b'PNG'
    assert (outdir / 'report.pdf').read_bytes() == b'PDF'


def test_finds_attachment_in_forwarded_message(tmp_path, monkeypatch):
    """An attachment inside a forwarded message/rfc822 is still an attachment."""
    payload = make_part(mime='multipart/mixed', parts=[
        make_part(mime='message/rfc822', parts=[
            make_part(mime='multipart/mixed', parts=[
                make_part('forwarded.docx', 'a1'),
            ]),
        ]),
    ])
    outdir = tmp_path / 'out'

    run(monkeypatch, payload, {'a1': b'fwd'}, outdir)

    assert (outdir / 'forwarded.docx').read_bytes() == b'fwd'


def test_duplicate_filenames_do_not_clobber(tmp_path, monkeypatch):
    payload = make_part(mime='multipart/mixed', parts=[
        make_part('report.pdf', 'a1'),
        make_part('report.pdf', 'a2'),
    ])
    outdir = tmp_path / 'out'

    run(monkeypatch, payload, {'a1': b'first', 'a2': b'second'}, outdir)

    assert (outdir / 'report.pdf').read_bytes() == b'first'
    assert (outdir / 'report-1.pdf').read_bytes() == b'second'


def test_creates_missing_output_dir(tmp_path, monkeypatch):
    payload = make_part(mime='multipart/mixed', parts=[make_part('a.txt', 'a1')])
    outdir = tmp_path / 'does' / 'not' / 'exist'

    run(monkeypatch, payload, {'a1': b'x'}, outdir)

    assert (outdir / 'a.txt').exists()


def test_simple_message_with_single_attachment(tmp_path, monkeypatch):
    """A non-multipart payload that is itself the attachment."""
    payload = make_part('lonely.txt', 'a1', mime='text/plain')
    outdir = tmp_path / 'out'

    run(monkeypatch, payload, {'a1': b'solo'}, outdir)

    assert (outdir / 'lonely.txt').read_bytes() == b'solo'
