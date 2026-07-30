"""Gmail OAuth authentication with compose and readonly scopes."""

import json
import os
import re
import sys
import webbrowser
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/calendar',
    # Full drive (supersedes drive.readonly): comment replies need write access,
    # and drive.file would not reach pre-existing docs.
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents',
]

BASE_DIR = Path(__file__).parent
CREDENTIALS_PATH = BASE_DIR / 'credentials.json'
TOKEN_PREFIX = 'token-'
TOKEN_SUFFIX = '.json'

# Port 1 is privileged and never listening, so the browser fails fast with
# "connection refused" while still putting the code in the address bar.
HEADLESS_REDIRECT_URI = 'http://localhost:1/'

# Google auth codes are URL-safe base64 plus '/', and run ~70+ characters. The
# length floor is what tells a pasted code apart from a typed "yes" or "nope",
# which are otherwise indistinguishable from one.
BARE_CODE_RE = re.compile(r'[A-Za-z0-9._~%/-]{20,}')


def get_token_path(email: str) -> Path:
    """Get token path for a specific email account."""
    return BASE_DIR / f'{TOKEN_PREFIX}{email}{TOKEN_SUFFIX}'


def list_accounts() -> list[str]:
    """Return list of authenticated email addresses from token files."""
    accounts = []
    for token_file in BASE_DIR.glob(f'{TOKEN_PREFIX}*{TOKEN_SUFFIX}'):
        # Extract email from filename: token-user@example.com.json -> user@example.com
        email = token_file.name[len(TOKEN_PREFIX):-len(TOKEN_SUFFIX)]
        if email:
            accounts.append(email)
    return sorted(accounts)


def print_available_accounts(accounts: list[str]) -> None:
    """Print list of available accounts to stderr."""
    print('Available accounts:', file=sys.stderr)
    for email in accounts:
        print(f'  - {email}', file=sys.stderr)


def resolve_account(account: str | None) -> str | None:
    """Resolve account specification to an email address.

    Returns the email to use, or None if OAuth flow needed for new account.
    Exits with error if account is ambiguous or not found.
    """
    accounts = list_accounts()

    # Explicit account specified
    if account:
        if account in accounts:
            return account
        print(f"Error: No account matches '{account}'", file=sys.stderr)
        if accounts:
            print_available_accounts(accounts)
        else:
            print('No accounts configured. Run: uv run gmail_cli.py accounts add', file=sys.stderr)
        sys.exit(1)

    # No account specified - check environment variable
    env_account = os.environ.get('GMAIL_CLI_ACCOUNT')
    if env_account:
        if env_account in accounts:
            return env_account
        print(f"Error: GMAIL_CLI_ACCOUNT='{env_account}' not found", file=sys.stderr)
        print_available_accounts(accounts)
        sys.exit(1)

    # No account specified, no env var - use single account or error
    if len(accounts) == 1:
        return accounts[0]
    if len(accounts) > 1:
        print('Error: Multiple accounts available. Specify one with --account:', file=sys.stderr)
        print_available_accounts(accounts)
        print('\nOr set GMAIL_CLI_ACCOUNT environment variable.', file=sys.stderr)
        sys.exit(1)

    # No accounts exist - will need OAuth flow
    return None


def get_email_from_service(service: Any) -> str:
    """Fetch email address from Gmail API profile."""
    profile = service.users().getProfile(userId='me').execute()
    return profile['emailAddress']


def load_token(email: str) -> Credentials | None:
    """Load credentials from token file for specified email."""
    token_path = get_token_path(email)
    if not token_path.exists():
        return None

    token_data = json.loads(token_path.read_text())
    return Credentials.from_authorized_user_info(token_data, SCOPES)


def stored_scopes(email: str) -> set[str]:
    """Read the scopes actually granted to an account's stored token.

    Credentials.from_authorized_user_info() overrides the token's own scopes
    with the ones we pass it, so creds.scopes reports what we asked for rather
    than what was granted. Read the file directly to see the truth.
    """
    token_path = get_token_path(email)
    if not token_path.exists():
        return set()

    scopes = json.loads(token_path.read_text()).get('scopes') or []
    if isinstance(scopes, str):
        scopes = scopes.split(' ')
    return set(scopes)


def missing_scopes(email: str) -> list[str]:
    """Return required scopes the stored token does not grant."""
    return sorted(set(SCOPES) - stored_scopes(email))


def save_token(email: str, creds: Credentials) -> None:
    """Save credentials to token file for specified email."""
    token_path = get_token_path(email)
    token_path.write_text(creds.to_json())


def refresh_credentials(email: str, creds: Credentials) -> Credentials | None:
    """Attempt to refresh expired credentials."""
    if not (creds.expired and creds.refresh_token):
        return None

    try:
        creds.refresh(Request())
    except Exception:
        return None
    save_token(email, creds)
    return creds


def require_credentials_file() -> None:
    """Fail early and legibly when the OAuth client secrets are absent."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_PATH}. "
            "Copy from gmail_to_md or create new OAuth credentials."
        )


def browser_available() -> bool:
    """Whether a browser on this machine could serve the loopback redirect.

    The browser flow only works if the browser runs here — it has to reach the
    local server we spin up. A remote browser (devcontainer, ssh box) cannot.
    """
    if sys.platform in ('darwin', 'win32'):
        return True
    if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        return False
    try:
        webbrowser.get()
    except webbrowser.Error:
        return False
    return True


def parse_redirect_response(pasted: str) -> tuple[str | None, str | None]:
    """Extract (code, state) from a pasted redirect URL or a bare code.

    Accepts the full address-bar URL, a bare query string, or just the code.
    """
    text = pasted.strip().strip('\'"')
    if not text:
        return None, None

    if '=' in text:
        # urlparse only fills .query when a '?' is present; a pasted bare query
        # string lands in .path instead.
        query = urlparse(text).query or text.lstrip('?')
        params = parse_qs(query)
        code = params.get('code', [None])[0]
        state = params.get('state', [None])[0]
        if code:
            return code, state
        if error := params.get('error', [None])[0]:
            print(f'Google reported an authorization error: {error}', file=sys.stderr)
        return None, state

    if BARE_CODE_RE.fullmatch(text):
        return unquote(text), None
    return None, None


def build_headless_flow() -> Flow:
    """Build an OAuth flow whose redirect the local browser cannot intercept."""
    return Flow.from_client_secrets_file(
        str(CREDENTIALS_PATH), SCOPES, redirect_uri=HEADLESS_REDIRECT_URI
    )


def print_headless_instructions(auth_url: str) -> None:
    """Explain the copy-paste dance, including the failure that means success."""
    print('\nNo browser here — authorize from any other machine:\n')
    print('1. Open this URL in a browser:\n')
    print(f'   {auth_url}\n')
    print('2. Grant access. The browser then tries to load a "localhost:1" page')
    print('   and fails with "connection refused" — that is expected.\n')
    print('3. Copy the FULL URL from the address bar of that failed page')
    print('   and paste it below.\n')


def prompt_for_code(
    expected_state: str | None,
    input_fn: Callable[[str], str] = input,
) -> str:
    """Read the pasted redirect URL (or bare code) and return the auth code.

    Re-prompts once when nothing code-shaped is pasted, then gives up.
    """
    prompt = 'Paste the redirect URL (or just the code): '
    for attempt in range(2):
        code, state = parse_redirect_response(input_fn(prompt))
        if code:
            if expected_state and state and state != expected_state:
                print(
                    'Warning: state mismatch — this response may belong to a '
                    'different authorization attempt.',
                    file=sys.stderr,
                )
            return code
        if attempt == 0:
            print('No authorization code found in that text.', file=sys.stderr)
            prompt = 'Try again — paste the whole URL from the address bar: '

    print(
        'Error: no authorization code provided. Re-run the command to start over.',
        file=sys.stderr,
    )
    sys.exit(1)


def finish_authorization(creds: Credentials) -> tuple[Credentials, str]:
    """Name the token file after the account that actually authorized."""
    service = build('gmail', 'v1', credentials=creds)
    email = get_email_from_service(service)

    save_token(email, creds)
    print(f'Authenticated as: {email}')

    return creds, email


def run_headless_oauth_flow(
    input_fn: Callable[[str], str] = input,
) -> tuple[Credentials, str]:
    """Authorize by pasting the redirect URL back from a browser elsewhere."""
    require_credentials_file()

    flow = build_headless_flow()
    # offline + consent so a refresh token comes back even on re-authorization.
    auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')

    print_headless_instructions(auth_url)
    code = prompt_for_code(state, input_fn)

    try:
        flow.fetch_token(code=code)
    except Exception as exc:
        print(f'Error: token exchange failed: {exc}', file=sys.stderr)
        sys.exit(1)

    return finish_authorization(flow.credentials)


def run_browser_oauth_flow() -> tuple[Credentials, str]:
    """Authorize via a browser on this machine, catching the loopback redirect."""
    require_credentials_file()

    print('Opening browser for authentication...')
    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    return finish_authorization(creds)


def run_oauth_flow(headless: bool | None = None) -> tuple[Credentials, str]:
    """Run interactive OAuth flow to obtain new credentials.

    headless=None auto-selects: the browser flow where a usable browser exists,
    the paste-the-URL flow otherwise.

    Returns tuple of (credentials, email_address).
    """
    if headless is None:
        headless = not browser_available()
    if headless:
        return run_headless_oauth_flow()
    return run_browser_oauth_flow()


def get_credentials(account: str | None = None) -> Any:
    """Resolve account and return valid credentials, running OAuth flow if needed."""
    email = resolve_account(account)

    if email is None:
        # No accounts exist, need OAuth flow
        creds, email = run_oauth_flow()
        return creds

    # Load existing credentials
    creds = load_token(email)

    # A token minted before a scope was added still refreshes cleanly, but the
    # API then rejects the new operation with an opaque 403
    # (ACCESS_TOKEN_SCOPE_INSUFFICIENT). Force re-consent instead.
    if creds and (missing := missing_scopes(email)):
        print(f'Token for {email} is missing required scope(s):', file=sys.stderr)
        for scope in missing:
            print(f'  - {scope}', file=sys.stderr)
        print('Re-authorizing...', file=sys.stderr)
        creds = None

    if not (creds and creds.valid):
        refreshed = creds and refresh_credentials(email, creds)
        if not refreshed:
            creds, new_email = run_oauth_flow()
            if new_email != email:
                print(
                    f"Warning: Expected {email}, authenticated as {new_email}",
                    file=sys.stderr
                )

    return creds


def authenticate(account: str | None = None) -> Any:
    """Authenticate with Gmail API and return service object.

    Args:
        account: Email address of account to use, or None for default behavior.
    """
    return build('gmail', 'v1', credentials=get_credentials(account))


def authenticate_calendar(account: str | None = None) -> Any:
    """Authenticate with Calendar API and return service object."""
    return build('calendar', 'v3', credentials=get_credentials(account))


def authenticate_drive(account: str | None = None) -> Any:
    """Authenticate with Drive API and return service object."""
    return build('drive', 'v3', credentials=get_credentials(account))


def authenticate_docs(account: str | None = None) -> Any:
    """Authenticate with Docs API and return service object."""
    return build('docs', 'v1', credentials=get_credentials(account))
