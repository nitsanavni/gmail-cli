"""Calendar command handlers for Gmail CLI."""

import argparse
import sys
from datetime import datetime, timedelta

from auth import authenticate_calendar

DATETIME_FORMATS = ['%Y-%m-%d %H:%M', '%Y-%m-%dT%H:%M', '%Y-%m-%d']


def parse_when(value: str) -> tuple[datetime, bool]:
    """Parse a date/datetime string. Returns (dt, is_all_day)."""
    for fmt in DATETIME_FORMATS:
        try:
            dt = datetime.strptime(value, fmt)
            return dt, fmt == '%Y-%m-%d'
        except ValueError:
            continue
    print(f"Error: Can't parse date '{value}'. Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM'.",
          file=sys.stderr)
    sys.exit(1)


def format_event(event: dict) -> str:
    """Format an event as a one-line summary."""
    start = event.get('start', {})
    when = start.get('dateTime', start.get('date', '?'))
    summary = event.get('summary', '(no title)')
    return f"[{event['id']}] {when}  {summary}"


def cmd_cal_list(args: argparse.Namespace) -> int:
    """List upcoming events."""
    service = authenticate_calendar(args.account)

    time_min = datetime.now()
    time_max = time_min + timedelta(days=args.days)

    result = service.events().list(
        calendarId=args.calendar,
        timeMin=time_min.astimezone().isoformat(),
        timeMax=time_max.astimezone().isoformat(),
        singleEvents=True,
        orderBy='startTime',
        maxResults=args.limit,
    ).execute()

    events = result.get('items', [])
    if not events:
        print(f'No events in the next {args.days} day(s).')
        return 0

    for event in events:
        print(format_event(event))
    return 0


def cmd_cal_add(args: argparse.Namespace) -> int:
    """Create an event."""
    service = authenticate_calendar(args.account)

    start_dt, all_day = parse_when(args.when)

    body: dict = {'summary': args.title}
    if args.description:
        body['description'] = args.description
    if args.location:
        body['location'] = args.location

    if all_day:
        end_date = start_dt + timedelta(days=1)
        body['start'] = {'date': start_dt.strftime('%Y-%m-%d')}
        body['end'] = {'date': end_date.strftime('%Y-%m-%d')}
    else:
        end_dt = start_dt + timedelta(minutes=args.duration)
        tz = start_dt.astimezone().tzinfo
        body['start'] = {'dateTime': start_dt.replace(tzinfo=tz).isoformat()}
        body['end'] = {'dateTime': end_dt.replace(tzinfo=tz).isoformat()}

    if args.reminder is not None:
        body['reminders'] = {
            'useDefault': False,
            'overrides': [{'method': 'popup', 'minutes': args.reminder}],
        }

    if args.attendee:
        body['attendees'] = [{'email': email} for email in args.attendee]

    event = service.events().insert(
        calendarId=args.calendar, body=body,
        sendUpdates='all' if args.attendee else 'none',
    ).execute()
    print(f"Created: {format_event(event)}")
    print(event.get('htmlLink', ''))
    return 0


def cmd_cal_invite(args: argparse.Namespace) -> int:
    """Add attendees to an existing event (sends invite emails)."""
    service = authenticate_calendar(args.account)
    event = service.events().get(calendarId=args.calendar, eventId=args.event_id).execute()

    attendees = event.get('attendees', [])
    existing = {a['email'].lower() for a in attendees}
    added = [e for e in args.attendee if e.lower() not in existing]
    if not added:
        print('All given attendees are already invited.')
        return 0
    attendees.extend({'email': email} for email in added)

    event = service.events().patch(
        calendarId=args.calendar, eventId=args.event_id,
        body={'attendees': attendees}, sendUpdates='all',
    ).execute()
    print(f"Invited {', '.join(added)} to: {format_event(event)}")
    return 0


def cmd_cal_delete(args: argparse.Namespace) -> int:
    """Delete an event by ID."""
    service = authenticate_calendar(args.account)
    event = service.events().get(calendarId=args.calendar, eventId=args.event_id).execute()
    if not args.yes:
        answer = input(f"Delete '{event.get('summary', '(no title)')}'? [y/N] ")
        if answer.strip().lower() != 'y':
            print('Aborted.')
            return 1
    service.events().delete(calendarId=args.calendar, eventId=args.event_id).execute()
    print(f"Deleted: {format_event(event)}")
    return 0


def cmd_cal_calendars(args: argparse.Namespace) -> int:
    """List available calendars."""
    service = authenticate_calendar(args.account)
    result = service.calendarList().list().execute()
    for cal in result.get('items', []):
        marker = '*' if cal.get('primary') else ' '
        print(f"  {marker} {cal['id']}  ({cal.get('summary', '')})")
    return 0
