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
from commands import (
    cmd_archive,
    cmd_attachments,
    cmd_label,
    cmd_labels,
    cmd_list,
    cmd_materialize,
    cmd_read,
    cmd_reply,
    cmd_send,
)
from docs_commands import cmd_docs_append, cmd_docs_create, cmd_docs_watch
from guide_commands import cmd_guide, guide_hint
from drive_commands import (
    cmd_drive_comment_add,
    cmd_drive_comment_delete,
    cmd_drive_comment_reply,
    cmd_drive_watch_comments,
    cmd_drive_comments,
    cmd_drive_info,
    cmd_drive_list,
    cmd_drive_read,
    cmd_drive_search,
)


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
        description='Gmail CLI - email, calendar, Drive and Docs',
        epilog=guide_hint(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
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

    # materialize command
    materialize_parser = subparsers.add_parser(
        'materialize', help='Write an email to a directory an agent can read')
    materialize_parser.add_argument('id', help='Message ID')
    materialize_parser.add_argument('--output', '-o', required=True,
                                    help='Output directory (created if missing)')
    materialize_parser.set_defaults(func=cmd_materialize)

    # label command
    label_parser = subparsers.add_parser('label', help='Add/remove labels on a message')
    label_parser.add_argument('id', help='Message ID')
    label_parser.add_argument('--add', action='append',
                              help='Label to apply, created if missing (repeatable)')
    label_parser.add_argument('--remove', action='append',
                              help='Label to remove (repeatable)')
    label_parser.set_defaults(func=cmd_label)

    # labels command
    subparsers.add_parser(
        'labels', help='List labels on the account'
    ).set_defaults(func=cmd_labels)

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

    # drive command
    drive_parser = subparsers.add_parser('drive', help='Google Drive (read-only)')
    drive_subparsers = drive_parser.add_subparsers(dest='drive_action', required=True)

    drive_list_parser = drive_subparsers.add_parser(
        'list', help='List recently modified files')
    drive_list_parser.add_argument('--limit', '-n', type=int, default=25,
                                   help='Max files to return (default: 25)')
    drive_list_parser.add_argument('--shared', action='store_true',
                                   help='Only files shared with me')
    drive_list_parser.set_defaults(func=cmd_drive_list)

    drive_search_parser = drive_subparsers.add_parser(
        'search', help='Search files by name and content')
    drive_search_parser.add_argument('query', help='Search text')
    drive_search_parser.add_argument('--limit', '-n', type=int, default=25,
                                     help='Max files to return (default: 25)')
    drive_search_parser.add_argument('--shared', action='store_true',
                                     help='Only files shared with me')
    drive_search_parser.set_defaults(func=cmd_drive_search)

    drive_read_parser = drive_subparsers.add_parser(
        'read', help='Print file content (gdocs export as markdown)')
    drive_read_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_read_parser.add_argument('--mime', help='Override export mime type')
    drive_read_parser.add_argument('--output', '-o', help='Save to file instead of stdout')
    drive_read_parser.set_defaults(func=cmd_drive_read)

    drive_info_parser = drive_subparsers.add_parser('info', help='Show file metadata')
    drive_info_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_info_parser.set_defaults(func=cmd_drive_info)

    drive_comments_parser = drive_subparsers.add_parser(
        'comments', help='List comment threads on a file')
    drive_comments_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_comments_parser.add_argument('--all', action='store_true',
                                       help='Include resolved comments')
    drive_comments_parser.set_defaults(func=cmd_drive_comments)

    drive_reply_parser = drive_subparsers.add_parser(
        'reply', help='Reply to a comment thread')
    drive_reply_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_reply_parser.add_argument('comment_id', help='Comment thread ID')
    drive_reply_parser.add_argument('--body', '-b', required=True, help='Reply text')
    drive_reply_parser.add_argument('--resolve', action='store_true',
                                    help='Resolve the thread with this reply')
    drive_reply_parser.add_argument('--state', '-s',
                                      help='Mark this write as seen in a '
                                           'watch-comments state file')
    drive_reply_parser.set_defaults(func=cmd_drive_comment_reply)

    drive_comment_parser = drive_subparsers.add_parser(
        'comment', help='Add an unanchored comment (agents cannot anchor)')
    drive_comment_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_comment_parser.add_argument('--body', '-b', required=True, help='Comment text')
    drive_comment_parser.add_argument('--state', '-s',
                                      help='Mark this write as seen in a '
                                           'watch-comments state file')
    drive_comment_parser.set_defaults(func=cmd_drive_comment_add)

    drive_uncomment_parser = drive_subparsers.add_parser(
        'uncomment', help='Delete a comment thread')
    drive_uncomment_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_uncomment_parser.add_argument('comment_id', help='Comment thread ID')
    drive_uncomment_parser.set_defaults(func=cmd_drive_comment_delete)

    guide_parser = subparsers.add_parser(
        'guide', help='List or print the bundled guides')
    guide_parser.add_argument('name', nargs='?',
                              help='Guide to print (omit to list)')
    guide_parser.set_defaults(func=cmd_guide)

    drive_wc_parser = drive_subparsers.add_parser(
        'watch-comments', help='Poll comment threads, emit new comments/replies')
    drive_wc_parser.add_argument('file_id', help='File ID or Drive/Docs URL')
    drive_wc_parser.add_argument('--interval', '-i', type=float, default=5,
                                 help='Seconds between polls (default: 5)')
    drive_wc_parser.add_argument('--timeout', '-t', type=float, help='Stop after N seconds')
    drive_wc_parser.add_argument('--once', action='store_true',
                                 help='Exit after the first new activity')
    drive_wc_parser.add_argument('--state', '-s',
                                 help='Track seen comment/reply IDs across runs')
    drive_wc_parser.set_defaults(func=cmd_drive_watch_comments)

    # docs command
    docs_parser = subparsers.add_parser(
        'docs', help='Google Docs (write)',
        epilog=guide_hint(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    docs_subparsers = docs_parser.add_subparsers(dest='docs_action', required=True)

    docs_append_parser = docs_subparsers.add_parser(
        'append', help='Append content to the end of a doc')
    docs_append_parser.add_argument('doc_id', help='Doc ID or Docs URL')
    docs_append_parser.add_argument('--body', '-b', help='Content to append')
    docs_append_parser.add_argument('--file', '-f', help='Read content from file')
    docs_append_parser.add_argument('--after',
                                    help='Insert below the paragraph containing '
                                         'this text, instead of at the end')
    docs_append_parser.add_argument('--font-size', type=float,
                                    help='Body font size in points (headings unaffected)')
    docs_append_parser.add_argument('--keep-breaks', action='store_true',
                                    help='Keep source line breaks (default: unwrap)')
    docs_append_parser.add_argument('--plain', action='store_true',
                                    help='Insert literally, no markdown styling')
    docs_append_parser.add_argument('--dry-run', action='store_true',
                                    help='Preview without modifying the doc')
    docs_append_parser.add_argument('--state', '-s',
                                    help="Re-baseline this watch state file, so "
                                         "watch does not report our own write")
    docs_append_parser.add_argument('--ignore-prefix',
                                    help='Exclude paragraphs with this prefix '
                                         'when re-baselining (must match the '
                                         "watcher's --ignore-prefix)")
    docs_append_parser.set_defaults(func=cmd_docs_append)

    docs_create_parser = docs_subparsers.add_parser('create', help='Create a new doc')
    docs_create_parser.add_argument('title', help='Document title')
    docs_create_parser.add_argument('--body', '-b', help='Initial content')
    docs_create_parser.add_argument('--file', '-f', help='Initial content from file')
    docs_create_parser.set_defaults(func=cmd_docs_create)

    docs_watch_parser = docs_subparsers.add_parser(
        'watch', help='Poll a doc and print a diff on each change',
        epilog=guide_hint(),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    docs_watch_parser.add_argument('doc_id', help='Doc ID or Docs URL')
    docs_watch_parser.add_argument('--interval', '-i', type=float, default=10,
                                   help='Seconds between polls (default: 10)')
    docs_watch_parser.add_argument('--debounce', '-d', type=float, default=0,
                                   help='Report only after the doc has been '
                                        'quiet this many seconds (avoids '
                                        'reporting mid-sentence)')
    docs_watch_parser.add_argument('--timeout', '-t', type=float,
                                   help='Stop after N seconds')
    docs_watch_parser.add_argument('--once', action='store_true',
                                   help='Exit after the first change')
    docs_watch_parser.add_argument('--receipt',
                                   help='Stamp/refresh a receipt line with this '
                                        'prefix in the doc on every change seen')
    docs_watch_parser.add_argument('--ignore-prefix',
                                   help='Ignore paragraphs starting with this '
                                        'text (e.g. another watcher\'s receipt)')
    docs_watch_parser.add_argument('--state', '-s',
                                   help='Persist the baseline here so restarts '
                                        'report edits made while not watching')
    docs_watch_parser.add_argument('--context', '-C', type=int, default=1,
                                   help='Diff context lines (default: 1)')
    docs_watch_parser.set_defaults(func=cmd_docs_watch)

    # accounts command
    accounts_parser = subparsers.add_parser('accounts', help='Manage Gmail accounts')
    accounts_parser.set_defaults(func=cmd_accounts)
    accounts_subparsers = accounts_parser.add_subparsers(dest='accounts_action')

    # accounts list
    accounts_subparsers.add_parser(
        'list', help='List accounts'
    ).set_defaults(accounts_func=cmd_accounts_list)

    # accounts add
    headless_help = 'Authorize by pasting a URL back (no browser on this machine)'
    add_parser = accounts_subparsers.add_parser('add', help='Add new account')
    add_parser.add_argument('--headless', action='store_true', help=headless_help)
    add_parser.set_defaults(accounts_func=cmd_accounts_add)

    # accounts reauth
    reauth_parser = accounts_subparsers.add_parser(
        'reauth', help='Re-authenticate account (fix expired/revoked tokens)'
    )
    reauth_parser.add_argument('--headless', action='store_true', help=headless_help)
    reauth_parser.set_defaults(accounts_func=cmd_accounts_reauth)

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
