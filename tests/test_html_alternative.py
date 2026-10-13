"""Messages carry an HTML alternative so Gmail doesn't hard-wrap them.

A plain-text-only draft opens in Gmail's plain-text compose mode, which
hard-wraps lines at ~78 columns when sent.
"""

import email

import commands

LONG = 'Hola Virginia, ' + 'una línea muy larga ' * 10 + '<fin> & más'
BODY = f'{LONG}\n\n- punto uno\n- punto dos'


def parts(msg):
    return {p.get_content_type(): p for p in msg.walk()}


def test_plain_message_has_html_alternative():
    msg = email.message_from_string(commands.build_message(BODY, None).as_string())
    assert msg.get_content_type() == 'multipart/alternative'
    found = parts(msg)
    plain = found['text/plain'].get_payload(decode=True).decode('utf-8')
    html = found['text/html'].get_payload(decode=True).decode('utf-8')
    assert plain == BODY
    assert '&lt;fin&gt; &amp; más' in html
    assert 'punto uno<br>' in html


def test_html_part_keeps_long_lines_unbroken():
    msg = email.message_from_string(commands.build_message(BODY, None).as_string())
    html = parts(msg)['text/html'].get_payload(decode=True).decode('utf-8')
    assert 'una línea muy larga ' * 10 in html


def test_attachments_wrap_the_alternative(tmp_path):
    f = tmp_path / 'a.pdf'
    f.write_bytes(b'%PDF-1.4')
    msg = email.message_from_string(
        commands.build_message(BODY, [str(f)]).as_string())
    assert msg.get_content_type() == 'multipart/mixed'
    found = parts(msg)
    assert 'multipart/alternative' in found
    assert 'text/html' in found
    assert found['application/pdf'].get_filename() == 'a.pdf'
