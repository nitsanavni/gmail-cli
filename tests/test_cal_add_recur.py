"""Tests for cal add --recur."""

import argparse
from unittest.mock import MagicMock

import calendar_commands


def run_add(monkeypatch, **kw):
    service = MagicMock()
    service.events.return_value.insert.return_value.execute.return_value = {
        'id': 'e1', 'summary': 'x', 'start': {'dateTime': '2026-09-30T18:00:00+02:00'}}
    monkeypatch.setattr(calendar_commands, 'authenticate_calendar', lambda a: service)
    args = argparse.Namespace(
        account=None, title='Piano', when='2026-09-30 18:00', duration=60,
        description=None, location=None, reminder=None, attendee=None,
        calendar='primary', recur=None, timezone='Europe/Madrid')
    for k, v in kw.items():
        setattr(args, k, v)
    calendar_commands.cmd_cal_add(args)
    return service.events.return_value.insert.call_args.kwargs['body']


def test_no_recurrence_by_default(monkeypatch):
    body = run_add(monkeypatch)
    assert 'recurrence' not in body
    assert 'timeZone' not in body['start']


def test_weekly_recurrence(monkeypatch):
    body = run_add(monkeypatch, recur='FREQ=WEEKLY;BYDAY=WE')
    assert body['recurrence'] == ['RRULE:FREQ=WEEKLY;BYDAY=WE']
    assert body['start']['timeZone'] == 'Europe/Madrid'
    assert body['end']['timeZone'] == 'Europe/Madrid'


def test_rrule_prefix_not_doubled(monkeypatch):
    body = run_add(monkeypatch, recur='RRULE:FREQ=WEEKLY')
    assert body['recurrence'] == ['RRULE:FREQ=WEEKLY']
