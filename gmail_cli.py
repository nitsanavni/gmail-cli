#!/usr/bin/env python3
"""Gmail CLI - Read, send, and reply to emails."""

import argparse
import sys

from account_commands import (
    cmd_accounts,
    cmd_accounts_add,
    cmd_accounts_list,
    cmd_accounts_reauth,
    cmd_accounts_remove,
)
from calendar_commands import cmd_cal_add, cmd_cal_calendars, cmd_cal_delete, cmd_cal_list
from commands import cmd_archive, cmd_attachments, cmd_list, cmd_read, cmd_reply, cmd_send


def add_compose_args(parser: argparse.ArgumentParser) -> None:
    """Add shared compose arguments (body, file, draft, cc, bcc) to a parser."""
    parser.add_argument('--body', '-b', help='Email body text')
    parser.add_argument('--file', '-f', help='Read body from file')
    parser.add_argument('--draft', '-d', action='store_true',
                        help='Create draft instead of sending')
    parser.add_argument('--cc', action='append', help='CC recipient (repeatable)')
    parser.add_argument('--bcc', action='append', help='BCC recipient (repeatable)')
    parser.add_argument('--attach', action='append', help='File to attach (repeatable)')


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
    add_compose_args(send_parser)
    send_parser.set_defaults(func=cmd_send)

    # reply command
    reply_parser = subparsers.add_parser('reply', help='Reply to an email')
    reply_parser.add_argument('message_id', help='Message ID to reply to')
    add_compose_args(reply_parser)
    reply_parser.set_defaults(func=cmd_reply)

    # attachments command
    attach_parser = subparsers.add_parser('attachments', help='Download attachments')
    attach_parser.add_argument('id', help='Message ID')
    attach_parser.add_argument('--output', '-o', help='Output directory (default: current)')
    attach_parser.set_defaults(func=cmd_attachments)

    # archive command
    archive_parser = subparsers.add_parser('archive', help='Archive emails')
    archive_parser.add_argument('ids', nargs='+', help='Message IDs to archive')
    archive_parser.set_defaults(func=cmd_archive)

    # cal command
    cal_parser = subparsers.add_parser('cal', help='Google Calendar')
    cal_subparsers = cal_parser.add_subparsers(dest='cal_action', required=True)

    cal_list_parser = cal_subparsers.add_parser('list', help='List upcoming events')
    cal_list_parser.add_argument('--days', '-d', type=int, default=7,
                                 help='Days ahead to show (default: 7)')
    cal_list_parser.add_argument('--limit', '-n', type=int, default=25,
                                 help='Max events (default: 25)')
    cal_list_parser.add_argument('--calendar', '-c', default='primary',
                                 help='Calendar ID (default: primary)')
    cal_list_parser.set_defaults(func=cmd_cal_list)

    cal_add_parser = cal_subparsers.add_parser('add', help='Create an event')
    cal_add_parser.add_argument('title', help='Event title')
    cal_add_parser.add_argument('--when', '-w', required=True,
                                help="Start: 'YYYY-MM-DD HH:MM' or YYYY-MM-DD (all-day)")
    cal_add_parser.add_argument('--duration', type=int, default=30,
                                help='Duration in minutes (default: 30)')
    cal_add_parser.add_argument('--description', help='Event description')
    cal_add_parser.add_argument('--location', help='Event location')
    cal_add_parser.add_argument('--reminder', type=int,
                                help='Popup reminder N minutes before')
    cal_add_parser.add_argument('--calendar', '-c', default='primary',
                                help='Calendar ID (default: primary)')
    cal_add_parser.set_defaults(func=cmd_cal_add)

    cal_delete_parser = cal_subparsers.add_parser('delete', help='Delete an event')
    cal_delete_parser.add_argument('event_id', help='Event ID')
    cal_delete_parser.add_argument('--yes', '-y', action='store_true',
                                   help='Skip confirmation prompt')
    cal_delete_parser.add_argument('--calendar', '-c', default='primary',
                                   help='Calendar ID (default: primary)')
    cal_delete_parser.set_defaults(func=cmd_cal_delete)

    cal_subparsers.add_parser(
        'calendars', help='List available calendars'
    ).set_defaults(func=cmd_cal_calendars)

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

    # accounts reauth
    accounts_subparsers.add_parser(
        'reauth', help='Re-authenticate account (fix expired/revoked tokens)'
    ).set_defaults(accounts_func=cmd_accounts_reauth)

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
