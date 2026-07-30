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

# Download attachments
uv run gmail_cli.py attachments <message-id>              # Into the current directory
uv run gmail_cli.py attachments <message-id> -o ./out     # Created if missing

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

**Collaborating live in a doc with a human: read `docs/doc-collaboration.md` first.**
It covers the two-watcher setup and the traps (self-wake, restart gap, UTF-16
offsets, inherited styling, mid-typing) that each cost real debugging time here.

`docs append` markup: `#`/`##`/`###` headings, `- ` bullets, `**bold**`,
`*italic*`, `~subscript~`, `^superscript^` — markers nest.

Two index traps when extending `docs append`:
- Docs indexes in **UTF-16 code units**, so a non-BMP char (emoji) shifts every
  later range by one. Use `u16_offsets()`, never `len()`.
- Inserted text **inherits the style at the insertion point**. The reset request
  must clear `baselineOffset` too, or appending after subscripted math renders
  the whole section as subscript.

`attachments` walks the part tree recursively, so it also saves inline images — a
screenshot pasted into a body is nested two levels down and a top-level-only scan
reports "No attachments found." Filenames come from the sender and are reduced to a
bare name before use; same-named attachments get a `-1`, `-2` suffix rather than
overwriting each other.

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

Adding a scope here invalidates existing tokens on purpose: `get_credentials` compares
`SCOPES` against the scopes recorded in the token file and re-runs consent when the token
is short, rather than letting the call fail with `ACCESS_TOKEN_SCOPE_INSUFFICIENT`. So the
next command after a scope change prompts for authorization. To re-consent deliberately
instead of on next use:

```bash
uv run gmail_cli.py --account EMAIL accounts reauth
```

Note `--account` is a global flag: it goes before the subcommand, not after.

The check reads the token file directly because `Credentials.from_authorized_user_info()`
overwrites the token's own scopes with the requested ones — `creds.scopes` always reports
the full list and can never reveal a short token.

The `docs` commands also require the Google Docs API to be enabled on the Cloud project
behind `credentials.json` (separate from the Drive API).

## Tests

```bash
uv run pytest
```

Tests mock the Google service objects, so they need no credentials and make no network
calls. There is no CI — run them locally before pushing.
