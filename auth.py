"""Gmail OAuth authentication with compose and readonly scopes."""

import json
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
TOKEN_PATH = BASE_DIR / 'token.json'
CREDENTIALS_PATH = BASE_DIR / 'credentials.json'


def load_token() -> Credentials | None:
    """Load credentials from token file."""
    if not TOKEN_PATH.exists():
        return None

    token_data = json.loads(TOKEN_PATH.read_text())
    return Credentials.from_authorized_user_info(token_data, SCOPES)


def save_token(creds: Credentials) -> None:
    """Save credentials to token file."""
    TOKEN_PATH.write_text(creds.to_json())


def refresh_credentials(creds: Credentials) -> Credentials | None:
    """Attempt to refresh expired credentials."""
    if not (creds.expired and creds.refresh_token):
        return None

    creds.refresh(Request())
    save_token(creds)
    return creds


def run_oauth_flow() -> Credentials:
    """Run interactive OAuth flow to obtain new credentials."""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {CREDENTIALS_PATH}. "
            "Copy from gmail_to_md or create new OAuth credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds)
    return creds


def authenticate() -> Any:
    """Authenticate with Gmail API and return service object."""
    creds = load_token()

    if creds and creds.valid:
        pass
    elif creds and refresh_credentials(creds):
        pass
    else:
        creds = run_oauth_flow()

    return build('gmail', 'v1', credentials=creds)
