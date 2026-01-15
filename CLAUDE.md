# gmail-cli

CLI tool for reading, sending, and replying to Gmail emails. Designed for Claude Code integration.

## Commands

```bash
# List emails
uv run gmail_cli.py list --query "from:user@example.com" --limit 10

# Read emails (by ID or query)
uv run gmail_cli.py read <message-id> [<message-id> ...]
uv run gmail_cli.py read --query "is:unread" --limit 5

# Send email
uv run gmail_cli.py send --to "user@example.com" --subject "Subject" --body "Body"
uv run gmail_cli.py send --to "user@example.com" --file message.md
uv run gmail_cli.py send --to "user@example.com" --subject "Subject" --body "Body" --draft
uv run gmail_cli.py send --to "user@example.com" --bcc "hidden@example.com" --subject "Subject" --body "Body"

# Reply to email
uv run gmail_cli.py reply <message-id> --body "Reply text"
uv run gmail_cli.py reply <message-id> --body "Reply text" --draft
uv run gmail_cli.py reply <message-id> --body "Reply text" --bcc "hidden@example.com"
```

## Setup

1. Copy `credentials.json` from gmail_to_md or create new OAuth credentials
2. First run will prompt for OAuth authorization
3. Token saved to `token.json`

## Scopes

- `gmail.readonly` - list/read
- `gmail.compose` - send/reply/drafts
