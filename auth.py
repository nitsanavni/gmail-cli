"""Gmail OAuth authentication with compose and readonly scopes."""

import json
from pathlib import Path
from typing import Any, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.compose',  # drafts + send
]


def load_token(token_path: Path) -> Optional[Credentials]:
    """Load credentials from token file."""
    if not token_path.exists():
        return None
    try:
        token_data = json.loads(token_path.read_text())
        return Credentials.from_authorized_user_info(token_data, SCOPES)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error loading token: {e}")
        print(f"Delete {token_path} and reauthenticate.")
        return None


def save_token(creds: Credentials, token_path: Path) -> None:
    """Save credentials to token file."""
    token_path.write_text(creds.to_json())


def authenticate() -> Any:
    """Authenticate with Gmail API.

    Returns:
        Authenticated Gmail service object.
    """
    token_path = Path(__file__).parent / 'token.json'
    credentials_path = Path(__file__).parent / 'credentials.json'

    creds = load_token(token_path)

    if creds and creds.valid:
        return build('gmail', 'v1', credentials=creds)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            save_token(creds, token_path)
            return build('gmail', 'v1', credentials=creds)
        except Exception as e:
            print(f"Error refreshing credentials: {e}")

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json not found at {credentials_path}. "
            "Copy from gmail_to_md or create new OAuth credentials."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(creds, token_path)

    return build('gmail', 'v1', credentials=creds)
