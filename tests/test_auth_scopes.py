"""Tests for detecting tokens that predate a required scope."""

import json
from unittest.mock import MagicMock

import pytest

import auth

EMAIL = 'user@example.com'


@pytest.fixture
def token_dir(tmp_path, monkeypatch):
    """Point token storage at a temp dir so tests never touch real tokens."""
    monkeypatch.setattr(auth, 'BASE_DIR', tmp_path)
    return tmp_path


def write_token(scopes, extra=None):
    """Write a token file granting the given scopes."""
    data = {
        'refresh_token': 'refresh',
        'client_id': 'id',
        'client_secret': 'secret',
        'scopes': scopes,
    }
    data.update(extra or {})
    auth.get_token_path(EMAIL).write_text(json.dumps(data))


def test_stored_scopes_reads_granted_scopes(token_dir):
    write_token(['scope-a', 'scope-b'])
    assert auth.stored_scopes(EMAIL) == {'scope-a', 'scope-b'}


def test_stored_scopes_accepts_space_delimited_string(token_dir):
    write_token('scope-a scope-b')
    assert auth.stored_scopes(EMAIL) == {'scope-a', 'scope-b'}


def test_stored_scopes_empty_without_token(token_dir):
    assert auth.stored_scopes(EMAIL) == set()


def test_no_missing_scopes_when_all_granted(token_dir):
    write_token(list(auth.SCOPES))
    assert auth.missing_scopes(EMAIL) == []


def test_missing_scopes_reports_scope_added_after_token_was_minted(token_dir):
    """A token minted before a scope was added must be reported as short."""
    added_later = auth.SCOPES[-1]
    write_token([s for s in auth.SCOPES if s != added_later])

    assert auth.missing_scopes(EMAIL) == [added_later]


def test_missing_scopes_not_fooled_by_credentials_object(token_dir):
    """The reason this reads the file: creds.scopes reports what we asked for.

    Credentials.from_authorized_user_info() overwrites the token's own scopes
    with the ones passed in, so a short token still claims the full set.
    """
    granted = [auth.SCOPES[0]]
    write_token(granted)

    creds = auth.load_token(EMAIL)

    assert set(creds.scopes) == set(auth.SCOPES), 'precondition: creds.scopes lies'
    assert auth.missing_scopes(EMAIL) == sorted(set(auth.SCOPES) - set(granted))


def test_valid_but_short_token_forces_reconsent(token_dir, monkeypatch, capsys):
    """A short token refreshes cleanly, so only an explicit check catches it."""
    write_token([auth.SCOPES[0]])
    monkeypatch.setattr(auth, 'resolve_account', lambda account: EMAIL)
    monkeypatch.setattr(auth, 'load_token', lambda email: MagicMock(valid=True))

    reconsented = MagicMock(valid=True)
    monkeypatch.setattr(auth, 'run_oauth_flow', lambda: (reconsented, EMAIL))

    assert auth.get_credentials() is reconsented
    assert 'missing required scope' in capsys.readouterr().err


def test_complete_token_is_used_without_reconsent(token_dir, monkeypatch):
    write_token(list(auth.SCOPES))
    stored = MagicMock(valid=True)
    monkeypatch.setattr(auth, 'resolve_account', lambda account: EMAIL)
    monkeypatch.setattr(auth, 'load_token', lambda email: stored)

    def fail():
        raise AssertionError('re-consent must not be triggered')

    monkeypatch.setattr(auth, 'run_oauth_flow', fail)

    assert auth.get_credentials() is stored
