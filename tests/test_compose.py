"""Tests for message composition with attachments."""

import base64
import email
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from compose import (
    MAX_MESSAGE_BYTES,
    attachment_errors,
    build_message,
    encode_message,
    oversize_error,
)


def parse(message):
    return email.message_from_bytes(base64.urlsafe_b64decode(encode_message(message)))


def test_no_attachments_stays_plain_text():
    """The pre-existing send path must be untouched when nothing is attached."""
    message = build_message('hello', None)
    assert not message.is_multipart()
    assert message.get_payload() == 'hello'


def test_attachment_bytes_and_type_round_trip(tmp_path):
    pdf = tmp_path / 'report.pdf'
    pdf.write_bytes(b'%PDF-1.4 body')

    parsed = parse(build_message('see attached', [str(pdf)]))
    part = next(p for p in parsed.walk() if p.get_filename() == 'report.pdf')

    assert part.get_payload(decode=True) == b'%PDF-1.4 body'
    assert part.get_content_type() == 'application/pdf'
    assert 'see attached' in parsed.get_payload(0).get_payload()


def test_unknown_extension_falls_back_to_octet_stream(tmp_path):
    odd = tmp_path / 'notes.xyzzy'
    odd.write_bytes(b'payload')

    parsed = parse(build_message('body', [str(odd)]))
    part = next(p for p in parsed.walk() if p.get_filename() == 'notes.xyzzy')

    assert part.get_content_type() == 'application/octet-stream'


def test_reports_every_bad_attachment(tmp_path):
    good = tmp_path / 'ok.txt'
    good.write_text('fine')

    errors = attachment_errors([str(good), str(tmp_path / 'missing.pdf'), str(tmp_path)])

    assert len(errors) == 2
    assert any('not found' in e for e in errors)
    assert any('is a directory' in e for e in errors)


def test_no_errors_for_readable_file_or_no_attachments(tmp_path):
    good = tmp_path / 'ok.txt'
    good.write_text('fine')

    assert attachment_errors([str(good)]) == []
    assert attachment_errors(None) == []


def test_small_message_is_not_flagged():
    assert oversize_error(build_message('tiny', None)) is None


@pytest.mark.parametrize('megabytes,rejected', [
    (17, False),   # ~23MB message: legal, though its base64url 'raw' exceeds 25MB
    (20, True),    # ~26.7MB message: genuinely over the limit
])
def test_size_guard_measures_the_message_not_the_raw_field(tmp_path, megabytes, rejected):
    """Attachments are base64-encoded inside the message, so 'raw' runs ~1.8x the
    original file. Measuring 'raw' would reject sends Gmail would have accepted."""
    blob = tmp_path / 'blob.bin'
    blob.write_bytes(b'\0' * (megabytes * 1024 * 1024))

    message = build_message('body', [str(blob)])
    assert (oversize_error(message) is not None) is rejected

    if not rejected:
        assert len(message.as_bytes()) <= MAX_MESSAGE_BYTES
        assert len(encode_message(message)) > MAX_MESSAGE_BYTES, (
            'this case is only meaningful if raw exceeds the limit while the '
            'message does not'
        )
