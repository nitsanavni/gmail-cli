# gmail-cli

CLI tool for reading, sending, and replying to Gmail emails. Designed for Claude Code integration.

## Commands

```bash
# Account management
uv run gmail_cli.py accounts              # List configured accounts
uv run gmail_cli.py accounts add          # Add new account (OAuth flow)
uv run gmail_cli.py accounts remove EMAIL # Remove account

# Use specific account (add --account/-a before any command)
uv run gmail_cli.py --account user@example.com list
uv run gmail_cli.py -a work@company.com send --to ...

# List emails
uv run gmail_cli.py list --query "from:user@example.com" --limit 10

# Read emails (by ID or query)
uv run gmail_cli.py read <message-id> [<message-id> ...]
uv run gmail_cli.py read --query "is:unread" --limit 5

# Send email
uv run gmail_cli.py send --to "user@example.com" --subject "Subject" --body "Body"
uv run gmail_cli.py send --to "user@example.com" --file message.md
uv run gmail_cli.py send --to "user@example.com" --subject "Subject" --body "Body" --draft
uv run gmail_cli.py send --to "user@example.com" --cc "cc@example.com" --subject "Subject" --body "Body"
uv run gmail_cli.py send --to "user@example.com" --cc "a@example.com" --cc "b@example.com" --subject "Subject" --body "Body"
uv run gmail_cli.py send --to "user@example.com" --bcc "hidden@example.com" --subject "Subject" --body "Body"

# Reply to email
uv run gmail_cli.py reply <message-id> --body "Reply text"
uv run gmail_cli.py reply <message-id> --body "Reply text" --draft
uv run gmail_cli.py reply <message-id> --body "Reply text" --cc "cc@example.com"
uv run gmail_cli.py reply <message-id> --body "Reply text" --bcc "hidden@example.com"

# Archive emails (removes the INBOX label)
uv run gmail_cli.py archive <message-id> [<message-id> ...]

# Download attachments (sender-supplied names are stripped to a bare filename)
uv run gmail_cli.py attachments <message-id>
uv run gmail_cli.py attachments <message-id> --output ./downloads
```

## Tests

```bash
uv run --dev pytest tests/
```

## Setup

1. Copy `credentials.json` from gmail_to_md or create new OAuth credentials
2. First run will prompt for OAuth authorization
3. Token saved to `token-{email}.json` (e.g., `token-user@example.com.json`)

## Multi-Account

- Tokens are stored as `token-{email}.json` for each authenticated account
- If only one account exists, it's used automatically
- With multiple accounts, use `--account` or set `GMAIL_CLI_ACCOUNT` env var

## Scopes

- `gmail.readonly` - list/read
- `gmail.compose` - send/reply/drafts
- `gmail.modify` - archive (label changes)

Adding a scope invalidates existing tokens. The CLI detects a token that
predates a scope and re-runs the OAuth flow instead of failing with a 403.
