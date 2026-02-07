#!/usr/bin/env python3
"""Gmail CLI - Read, send, and reply to emails."""

import argparse
import sys

from account_commands import (
    cmd_accounts,
    cmd_accounts_add,
    cmd_accounts_list,
    cmd_accounts_remove,
)
from commands import cmd_list, cmd_read, cmd_reply, cmd_send


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Gmail CLI - Read, send, and reply to emails'
    )

    # Global account flag
    parser.add_argument(
        '--account', '-a',
        help='Email account to use (e.g., user@example.com)'
    )

    subparsers = parser.add_subparsers(dest='command', required=True)

    # list command
    list_parser = subparsers.add_parser('list', help='List emails')
    list_parser.add_argument('--query', '-q', help='Gmail search query')
    list_parser.add_argument('--limit', '-n', type=int, default=10,
                            help='Max messages to return (default: 10)')
    list_parser.set_defaults(func=cmd_list)

    # read command
    read_parser = subparsers.add_parser('read', help='Read email content')
    read_parser.add_argument('ids', nargs='*', help='Message IDs to read')
    read_parser.add_argument('--query', '-q', help='Gmail search query')
    read_parser.add_argument('--limit', '-n', type=int, default=10,
                            help='Max messages when using query (default: 10)')
    read_parser.set_defaults(func=cmd_read)

    # send command
    send_parser = subparsers.add_parser('send', help='Send an email')
    send_parser.add_argument('--to', required=True, help='Recipient email')
    send_parser.add_argument('--subject', '-s', help='Email subject')
    send_parser.add_argument('--body', '-b', help='Email body text')
    send_parser.add_argument('--file', '-f', help='Read body from file')
    send_parser.add_argument('--draft', '-d', action='store_true',
                            help='Create draft instead of sending')
    send_parser.add_argument('--cc', action='append', help='CC recipient (repeatable)')
    send_parser.add_argument('--bcc', action='append', help='BCC recipient (repeatable)')
    send_parser.set_defaults(func=cmd_send)

    # reply command
    reply_parser = subparsers.add_parser('reply', help='Reply to an email')
    reply_parser.add_argument('message_id', help='Message ID to reply to')
    reply_parser.add_argument('--body', '-b', help='Reply body text')
    reply_parser.add_argument('--file', '-f', help='Read body from file')
    reply_parser.add_argument('--draft', '-d', action='store_true',
                            help='Create draft instead of sending')
    reply_parser.add_argument('--cc', action='append', help='CC recipient (repeatable)')
    reply_parser.add_argument('--bcc', action='append', help='BCC recipient (repeatable)')
    reply_parser.set_defaults(func=cmd_reply)

    # accounts command
    accounts_parser = subparsers.add_parser('accounts', help='Manage Gmail accounts')
    accounts_parser.set_defaults(func=cmd_accounts)
    accounts_subparsers = accounts_parser.add_subparsers(dest='accounts_action')

    # accounts list
    accounts_subparsers.add_parser(
        'list', help='List accounts'
    ).set_defaults(accounts_func=cmd_accounts_list)

    # accounts add
    accounts_subparsers.add_parser(
        'add', help='Add new account'
    ).set_defaults(accounts_func=cmd_accounts_add)

    # accounts remove
    remove_parser = accounts_subparsers.add_parser('remove', help='Remove account')
    remove_parser.add_argument('email', help='Email address to remove')
    remove_parser.add_argument('--yes', '-y', action='store_true',
                               help='Skip confirmation prompt')
    remove_parser.set_defaults(accounts_func=cmd_accounts_remove)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
