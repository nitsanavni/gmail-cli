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

# Google Drive (read-only)
uv run gmail_cli.py drive list                    # Recently modified files
uv run gmail_cli.py drive list --shared           # Only files shared with me
uv run gmail_cli.py drive search "quarterly"      # Match name or full text
uv run gmail_cli.py drive read <file-id-or-url>   # Content to stdout
uv run gmail_cli.py drive read <url> -o out.md    # Save to file (required for binaries)
uv run gmail_cli.py drive info <file-id-or-url>   # Metadata

# Google Docs (write)
uv run gmail_cli.py docs append <id-or-url> --file section.md
uv run gmail_cli.py docs append <id-or-url> --body "text"
uv run gmail_cli.py docs append <id-or-url> --file x.md --dry-run  # preview only
```

`drive read` accepts a bare file ID or any Drive/Docs URL. Google-native files are
exported: docs -> markdown, sheets -> CSV, slides -> plain text. Override with `--mime`.

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
- `gmail.modify` - archive
- `calendar` - cal commands
- `drive.readonly` - drive commands
- `documents` - docs commands (read/write, all docs; Google has no per-file Docs scope)

Adding a scope here does **not** invalidate existing tokens — a still-valid token is
reused as-is and API calls fail with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. After changing
this list, run:

```bash
uv run gmail_cli.py --account EMAIL accounts reauth
```

Note `--account` is a global flag: it goes before the subcommand, not after.

The `docs` commands also require the Google Docs API to be enabled on the Cloud project
behind `credentials.json` (separate from the Drive API).
