"""Gmail settings: filters and forwarding addresses.

Two APIs with two different scopes and one ordering constraint between them:
filters live under `gmail.settings.basic`, forwarding addresses under
`gmail.settings.sharing`, and a filter may only forward to an address the
account has already *accepted*. `cmd_filters_add` enforces that ordering itself
so a wrong order reads as an instruction rather than an opaque 400.
"""

import argparse
import sys

from googleapiclient.errors import HttpError

from auth import authenticate
from commands import ensure_label, label_ids_by_name

# Filter.criteria fields we expose, mapped from their argparse destination.
# Gmail stores multi-value criteria as one Gmail-query string, so `--from a
# --from b` becomes "a OR b" — the same thing the settings UI writes.
OR_JOINED = {'from': 'from_', 'to': 'to', 'subject': 'subject'}


def settings(service):
    """The users().settings() collection — filters and forwarding hang off it."""
    return service.users().settings()


def or_join(values: list[str]) -> str:
    """Join repeated criteria values the way Gmail's own settings UI does."""
    return ' OR '.join(values)


def build_criteria(args: argparse.Namespace) -> dict:
    """Assemble Filter.criteria from the parsed flags, omitting what is unset."""
    criteria = {}
    for field, dest in OR_JOINED.items():
        if values := getattr(args, dest, None):
            criteria[field] = or_join(values)
    if args.query:
        criteria['query'] = args.query
    if args.not_query:
        criteria['negatedQuery'] = args.not_query
    if args.has_attachment:
        criteria['hasAttachment'] = True
    return criteria


def build_action(service, args: argparse.Namespace) -> dict:
    """Assemble Filter.action, resolving label names to ids as `label` does."""
    action = {}
    if args.forward:
        action['forward'] = args.forward
    if args.label:
        known = label_ids_by_name(service)
        action['addLabelIds'] = [ensure_label(service, name, known)
                                 for name in args.label]
    remove = []
    if args.archive:
        remove.append('INBOX')
    if args.mark_read:
        remove.append('UNREAD')
    if remove:
        action['removeLabelIds'] = remove
    return action


def forwarding_addresses(service) -> dict[str, str]:
    """Map forwarding address -> verification status for this account."""
    result = settings(service).forwardingAddresses().list(userId='me').execute()
    return {entry['forwardingEmail']: entry.get('verificationStatus', 'unknown')
            for entry in result.get('forwardingAddresses', [])}


def describe_criteria(criteria: dict) -> str:
    """One-line rendering of a filter's criteria for `filters list`."""
    parts = [f'{key}:{value}' for key, value in sorted(criteria.items())]
    return ' '.join(parts) or '(no criteria)'


def describe_action(service, action: dict) -> str:
    """One-line rendering of a filter's action, with label ids named."""
    parts = []
    if forward := action.get('forward'):
        parts.append(f'forward->{forward}')
    names = {label_id: name for name, label_id in label_ids_by_name(service).items()}
    for key, verb in (('addLabelIds', '+'), ('removeLabelIds', '-')):
        for label_id in action.get(key, []):
            parts.append(f'{verb}{names.get(label_id, label_id)}')
    return ' '.join(parts) or '(no action)'


def cmd_filters_list(args: argparse.Namespace) -> int:
    """List the account's filters."""
    service = authenticate(args.account)

    result = settings(service).filters().list(userId='me').execute()
    filters = result.get('filter', [])
    if not filters:
        print('No filters found.')
        return 0

    for entry in filters:
        print(entry['id'])
        print(f"    match: {describe_criteria(entry.get('criteria', {}))}")
        print(f"    do:    {describe_action(service, entry.get('action', {}))}")

    return 0


def cmd_filters_add(args: argparse.Namespace) -> int:
    """Create a filter. Refuses to forward to an unaccepted address."""
    service = authenticate(args.account)

    criteria = build_criteria(args)
    if not criteria:
        print('Error: a filter needs at least one criterion.', file=sys.stderr)
        return 1

    if args.forward:
        status = forwarding_addresses(service).get(args.forward)
        if status != 'accepted':
            state = status or 'not registered on this account'
            print(f'Error: cannot forward to {args.forward} — {state}.',
                  file=sys.stderr)
            print('Gmail only forwards to a verified address. Register it with:',
                  file=sys.stderr)
            print(f'  gmail forwarding add {args.forward}', file=sys.stderr)
            print('then have the recipient click the confirmation Google mails them.',
                  file=sys.stderr)
            return 1

    action = build_action(service, args)
    if not action:
        print('Error: a filter needs at least one action.', file=sys.stderr)
        return 1

    body = {'criteria': criteria, 'action': action}
    created = settings(service).filters().create(userId='me', body=body).execute()

    print(f"Created filter: {created['id']}")
    print(f'    match: {describe_criteria(criteria)}')
    print(f'    do:    {describe_action(service, action)}')
    return 0


def cmd_filters_remove(args: argparse.Namespace) -> int:
    """Delete a filter by id."""
    service = authenticate(args.account)

    try:
        settings(service).filters().delete(userId='me', id=args.id).execute()
    except HttpError as exc:
        if exc.resp.status == 404:
            print(f"Error: no filter with id '{args.id}'.", file=sys.stderr)
            return 1
        raise

    print(f'Removed filter: {args.id}')
    return 0


def cmd_forwarding_list(args: argparse.Namespace) -> int:
    """List forwarding addresses and whether Gmail will actually forward to them."""
    service = authenticate(args.account)

    addresses = forwarding_addresses(service)
    if not addresses:
        print('No forwarding addresses configured.')
        return 0

    for email, status in sorted(addresses.items()):
        print(f'{email}\t{status}')

    return 0


def explain_domain_wide_only(email: str) -> None:
    """Point at the settings UI, the only path a user credential has left.

    Google restricts writes to forwardingAddresses to service accounts holding
    domain-wide delegation — the `gmail.settings.sharing` scope is necessary but
    not sufficient, and no amount of re-consent changes that.
    """
    print('Error: Google restricts adding a forwarding address to service accounts',
          file=sys.stderr)
    print('with domain-wide delegation. A user credential cannot do it, however',
          file=sys.stderr)
    print('broadly scoped. Add it by hand instead:', file=sys.stderr)
    print('  Gmail -> Settings -> Forwarding and POP/IMAP -> Add a forwarding address',
          file=sys.stderr)
    print(f'  -> {email}, then have them click the link Google mails.', file=sys.stderr)
    print('Leave "Forward a copy of incoming mail" OFF — a filter forwards per-message.',
          file=sys.stderr)


def cmd_forwarding_add(args: argparse.Namespace) -> int:
    """Register a forwarding address, which usually mails it a confirmation link."""
    service = authenticate(args.account)

    body = {'forwardingEmail': args.email}
    try:
        created = settings(service).forwardingAddresses().create(
            userId='me', body=body).execute()
    except HttpError as exc:
        if exc.resp.status == 403:
            explain_domain_wide_only(args.email)
            return 1
        raise

    status = created.get('verificationStatus', 'unknown')
    print(f"Added forwarding address: {created['forwardingEmail']} ({status})")
    if status == 'pending':
        print(f'Google mailed {args.email} a confirmation link. Nothing forwards')
        print('until the recipient clicks it.')
    return 0


def cmd_forwarding_remove(args: argparse.Namespace) -> int:
    """Unregister a forwarding address."""
    service = authenticate(args.account)

    try:
        settings(service).forwardingAddresses().delete(
            userId='me', forwardingEmail=args.email).execute()
    except HttpError as exc:
        if exc.resp.status == 404:
            print(f"Error: {args.email} is not a forwarding address here.",
                  file=sys.stderr)
            return 1
        raise

    print(f'Removed forwarding address: {args.email}')
    return 0
