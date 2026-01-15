"""Gmail OAuth authentication with compose and readonly scopes."""

import json
import os
import sys
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',
]

BASE_DIR = Path(__file__).parent
CREDENTIALS_PATH = BASE_DIR / 'credentials.json'
TOKEN_PREFIX = 'token-'
TOKEN_SUFFIX = '.json'


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
            print('No accounts configured. Run: gmail-cli accounts add', file=sys.stderr)
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


def save_token(email: str, creds: Credentials) -> None:
    """Save credentials to token file for specified email."""
    token_path = get_token_path(email)
    token_path.write_text(creds.to_json())


def refresh_credentials(email: str, creds: Credentials) -> Credentials | None:
    """Attempt to refresh expired credentials."""
    if not (creds.expired and creds.refresh_token):
        return None

    creds.refresh(Request())
    save_token(email, creds)
    return creds


def run_oauth_flow() -> tuple[Credentials, str]:
    """Run interactive OAuth flow to obtain new credentials.

    Returns tuple of (credentials, email_address).
    """
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_PATH}. "
            "Copy from gmail_to_md or create new OAuth credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    # Fetch email to name the token file
    service = build('gmail', 'v1', credentials=creds)
    email = get_email_from_service(service)

    save_token(email, creds)
    print(f'Authenticated as: {email}')

    return creds, email


def authenticate(account: str | None = None) -> Any:
    """Authenticate with Gmail API and return service object.

    Args:
        account: Email address of account to use, or None for default behavior.
    """
    email = resolve_account(account)

    if email is None:
        # No accounts exist, need OAuth flow
        creds, email = run_oauth_flow()
        return build('gmail', 'v1', credentials=creds)

    # Load existing credentials
    creds = load_token(email)

    if not (creds and creds.valid):
        refreshed = creds and refresh_credentials(email, creds)
        if not refreshed:
            creds, _ = run_oauth_flow()

    return build('gmail', 'v1', credentials=creds)
