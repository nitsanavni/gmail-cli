from unittest import mock

import auth


class FakeResp:
    status_code = 200
    text = ''

    def json(self):
        return {'access_token': 'at', 'refresh_token': 'rt', 'expires_in': 3600}


def test_exchange_and_refresh_omit_client_secret(monkeypatch):
    monkeypatch.setenv('GMAIL_CLI_PROXY_SECRET', '1')
    monkeypatch.setenv('GMAIL_CLI_CLIENT_ID', 'cid')
    with mock.patch('auth.requests.post', return_value=FakeResp()) as post:
        creds = auth.proxy_exchange_code('the-code')
        auth.proxy_refresh(creds)
    assert post.call_count == 2
    for call in post.call_args_list:
        assert call.args[0] == 'https://oauth2.googleapis.com/token'
        assert 'client_secret' not in call.kwargs['data']
        assert call.kwargs['data']['client_id'] == 'cid'
    assert creds.token == 'at' and creds.refresh_token == 'rt'


def test_headless_flow_needs_no_credentials_file(monkeypatch):
    monkeypatch.setenv('GMAIL_CLI_PROXY_SECRET', '1')
    monkeypatch.setenv('GMAIL_CLI_CLIENT_ID', 'cid')
    monkeypatch.setattr(auth, 'CREDENTIALS_PATH', auth.BASE_DIR / 'nonexistent.json')
    auth.require_credentials_file()
    url, _ = auth.build_headless_flow().authorization_url(access_type='offline')
    assert 'client_id=cid' in url
