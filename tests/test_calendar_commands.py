"""Tests for Google Calendar commands."""

import argparse
import sys
from unittest.mock import MagicMock

import pytest

import calendar_commands
import gmail_cli


def delete_args(**overrides):
    """Namespace for `cal delete` with command defaults."""
    args = argparse.Namespace(
        account=None, calendar='primary', event_id='event-1', note=None, yes=True,
    )
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def fake_service(event):
    service = MagicMock()
    service.events.return_value.get.return_value.execute.return_value = event
    return service


def test_delete_with_note_patches_before_deleting(monkeypatch):
    event = {
        'id': 'event-1',
        'summary': 'Recurring workshop',
        'description': 'Bring your questions.',
        'start': {'dateTime': '2026-08-20T10:00:00Z'},
    }
    service = fake_service(event)
    monkeypatch.setattr(
        calendar_commands, 'authenticate_calendar', lambda account: service)

    operations = []
    events = service.events.return_value
    events.patch.return_value.execute.side_effect = lambda: operations.append('patch')
    events.delete.return_value.execute.side_effect = lambda: operations.append('delete')

    assert calendar_commands.cmd_cal_delete(
        delete_args(note='Speaker is unavailable')) == 0

    events.patch.assert_called_once_with(
        calendarId='primary',
        eventId='event-1',
        body={
            'summary': '[Cancelled] Recurring workshop',
            'description': 'Speaker is unavailable\n\nBring your questions.',
        },
        sendUpdates='all',
    )
    events.delete.assert_called_once_with(
        calendarId='primary', eventId='event-1', sendUpdates='all')
    assert operations == ['patch', 'delete']


def test_delete_without_note_skips_patch_but_notifies_attendees(monkeypatch):
    event = {
        'id': 'event-1',
        'summary': 'Workshop',
        'start': {'date': '2026-08-20'},
    }
    service = fake_service(event)
    monkeypatch.setattr(
        calendar_commands, 'authenticate_calendar', lambda account: service)

    assert calendar_commands.cmd_cal_delete(delete_args()) == 0

    events = service.events.return_value
    events.patch.assert_not_called()
    events.delete.assert_called_once_with(
        calendarId='primary', eventId='event-1', sendUpdates='all')


@pytest.mark.parametrize('note_args', [
    ['--note'],
    ['--note', ''],
    ['--note', '   '],
])
def test_delete_note_requires_non_empty_value(monkeypatch, note_args):
    monkeypatch.setattr(
        sys, 'argv', ['gmail', 'cal', 'delete', 'event-1', *note_args])

    with pytest.raises(SystemExit) as exc:
        gmail_cli.main()

    assert exc.value.code == 2
