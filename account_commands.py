"""Account management command handlers for Gmail CLI."""

import argparse
import os

from auth import get_token_path, list_accounts, resolve_account, run_oauth_flow


def cmd_accounts(args: argparse.Namespace) -> int:
    """List or manage Gmail accounts."""
    if args.accounts_action:
        return args.accounts_func(args)
    return cmd_accounts_list(args)


def cmd_accounts_list(args: argparse.Namespace) -> int:
    """List all authenticated accounts."""
    accounts = list_accounts()
    default = os.environ.get('GMAIL_CLI_ACCOUNT')

    if not accounts:
        print('No accounts configured.')
        print('Run: uv run gmail_cli.py accounts add')
        return 0

    print('Available accounts:')
    for email in accounts:
        marker = '*' if email == default else ' '
        print(f'  {marker} {email}')

    if default and default not in accounts:
        print(f"\nWarning: GMAIL_CLI_ACCOUNT='{default}' not found")

    return 0


def cmd_accounts_add(args: argparse.Namespace) -> int:
    """Add new account via OAuth flow."""
    print('Opening browser for authentication...')
    run_oauth_flow()
    return 0


def cmd_accounts_reauth(args: argparse.Namespace) -> int:
    """Re-authenticate an account (refresh expired/revoked tokens)."""
    email = resolve_account(args.account)
    if email is None:
        print('No accounts configured. Use: gmail accounts add')
        return 1

    print(f'Re-authenticating {email}...')
    token_path = get_token_path(email)
    if token_path.exists():
        token_path.unlink()
    print('Opening browser for authentication...')
    run_oauth_flow()
    return 0


def cmd_accounts_remove(args: argparse.Namespace) -> int:
    """Remove account token file."""
    accounts = list_accounts()

    if args.email not in accounts:
        print(f"Error: Account '{args.email}' not found")
        if accounts:
            print('Available accounts:')
            for email in accounts:
                print(f'  - {email}')
        return 1

    if not args.yes:
        response = input(f"Remove account '{args.email}'? [y/N] ").strip().lower()
        if response != 'y':
            print('Aborted.')
            return 0

    token_path = get_token_path(args.email)
    token_path.unlink()
    print(f'Removed account: {args.email}')
    return 0
