"""Tests for authorizing on a machine with no browser."""

import json
from unittest.mock import MagicMock

import pytest

import auth

EMAIL = 'user@example.com'
AUTH_URL = 'https://accounts.google.com/o/oauth2/auth?client_id=x'
STATE = 'state-abc'
CODE = '4/0AVMBsJj-oPaquExampleCode_-~.'


@pytest.fixture
def token_dir(tmp_path, monkeypatch):
    """Point token storage at a temp dir so tests never touch real tokens."""
    monkeypatch.setattr(auth, 'BASE_DIR', tmp_path)
    return tmp_path


@pytest.fixture
def flow(monkeypatch):
    """A stand-in Flow that hands back a canned auth URL and credentials."""
    fake = MagicMock()
    fake.authorization_url.return_value = (AUTH_URL, STATE)
    fake.credentials = MagicMock(to_json=lambda: json.dumps({'token': 'access'}))
    monkeypatch.setattr(auth, 'build_headless_flow', lambda: fake)
    monkeypatch.setattr(auth, 'require_credentials_file', lambda: None)
    monkeypatch.setattr(auth, 'build', lambda *a, **kw: MagicMock())
    monkeypatch.setattr(auth, 'get_email_from_service', lambda service: EMAIL)
    return fake


def scripted_input(*answers):
    """An input() replacement that returns each answer in turn."""
    remaining = list(answers)
    return lambda prompt: remaining.pop(0)


def test_bare_code_is_taken_as_is():
    assert auth.parse_redirect_response(CODE) == (CODE, None)


def test_code_extracted_from_full_redirect_url_with_extra_params():
    url = (
        f'http://localhost:1/?state={STATE}&code=4%2F0AVMBsJj-code'
        '&scope=https://www.googleapis.com/auth/gmail.readonly%20'
        'https://www.googleapis.com/auth/drive'
    )

    assert auth.parse_redirect_response(url) == ('4/0AVMBsJj-code', STATE)


def test_bare_query_string_is_accepted():
    assert auth.parse_redirect_response(f'code={CODE}&state={STATE}') == (CODE, STATE)


def test_surrounding_whitespace_and_quotes_are_stripped():
    assert auth.parse_redirect_response(f'  "{CODE}" \n') == (CODE, None)


def test_no_code_in_pasted_text():
    assert auth.parse_redirect_response('http://localhost:1/') == (None, None)
    assert auth.parse_redirect_response('') == (None, None)


def test_short_word_is_not_mistaken_for_a_code():
    """Codes run ~70 chars; a typed 'nope' is otherwise shaped just like one."""
    assert auth.parse_redirect_response('nope') == (None, None)


def test_google_error_response_is_reported(capsys):
    code, _ = auth.parse_redirect_response(
        f'http://localhost:1/?error=access_denied&state={STATE}'
    )

    assert code is None
    assert 'access_denied' in capsys.readouterr().err


def test_prompt_reprompts_once_then_accepts(capsys):
    code = auth.prompt_for_code(STATE, scripted_input('not a url', f'?code={CODE}'))

    assert code == CODE
    assert 'No authorization code found' in capsys.readouterr().err


def test_prompt_gives_up_after_second_failure(capsys):
    with pytest.raises(SystemExit) as exc:
        auth.prompt_for_code(STATE, scripted_input('nope', 'still nope'))

    assert exc.value.code == 1
    assert 'no authorization code provided' in capsys.readouterr().err


def test_state_mismatch_warns_but_proceeds(capsys):
    code = auth.prompt_for_code(STATE, scripted_input(f'?code={CODE}&state=other'))

    assert code == CODE
    assert 'state mismatch' in capsys.readouterr().err


def test_headless_flow_writes_token_where_accounts_expect_it(token_dir, flow):
    creds, email = auth.run_headless_oauth_flow(scripted_input(CODE))

    assert email == EMAIL
    assert creds is flow.credentials
    flow.fetch_token.assert_called_once_with(code=CODE)
    assert (token_dir / f'token-{EMAIL}.json').exists()
    assert auth.list_accounts() == [EMAIL]


def test_headless_flow_prints_the_url_to_open(token_dir, flow, capsys):
    auth.run_headless_oauth_flow(scripted_input(CODE))

    assert AUTH_URL in capsys.readouterr().out


def test_headless_flow_requests_offline_access(token_dir, flow):
    auth.run_headless_oauth_flow(scripted_input(CODE))

    flow.authorization_url.assert_called_once_with(
        access_type='offline', prompt='consent'
    )


def test_exchange_failure_reports_google_error(token_dir, flow, capsys):
    flow.fetch_token.side_effect = ValueError('invalid_grant: Bad Request')

    with pytest.raises(SystemExit) as exc:
        auth.run_headless_oauth_flow(scripted_input(CODE))

    assert exc.value.code == 1
    assert 'invalid_grant' in capsys.readouterr().err
    assert not list(token_dir.glob('token-*.json'))


def test_run_oauth_flow_falls_back_to_headless_without_a_browser(monkeypatch):
    monkeypatch.setattr(auth, 'browser_available', lambda: False)
    monkeypatch.setattr(auth, 'run_headless_oauth_flow', lambda: ('creds', EMAIL))

    def fail():
        raise AssertionError('browser flow must not run without a browser')

    monkeypatch.setattr(auth, 'run_browser_oauth_flow', fail)

    assert auth.run_oauth_flow() == ('creds', EMAIL)


def test_run_oauth_flow_prefers_the_browser_when_one_exists(monkeypatch):
    monkeypatch.setattr(auth, 'browser_available', lambda: True)
    monkeypatch.setattr(auth, 'run_browser_oauth_flow', lambda: ('creds', EMAIL))

    def fail():
        raise AssertionError('headless flow must not run when a browser exists')

    monkeypatch.setattr(auth, 'run_headless_oauth_flow', fail)

    assert auth.run_oauth_flow() == ('creds', EMAIL)


def test_headless_flag_overrides_an_available_browser(monkeypatch):
    monkeypatch.setattr(auth, 'browser_available', lambda: True)
    monkeypatch.setattr(auth, 'run_headless_oauth_flow', lambda: ('creds', EMAIL))

    assert auth.run_oauth_flow(headless=True) == ('creds', EMAIL)


def test_no_display_means_no_browser(monkeypatch):
    monkeypatch.setattr(auth.sys, 'platform', 'linux')
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)

    assert auth.browser_available() is False
