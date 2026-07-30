# gmail-cli

CLI tool for reading, sending, and replying to Gmail emails. Designed for Claude Code integration.

## Setup

1. **Get OAuth credentials:**
   - Copy `credentials.json` from `../gmail_to_md/`, or
   - Create new credentials in [Google Cloud Console](https://console.cloud.google.com/apis/credentials)

2. **First run:**
   ```bash
   uv run gmail_cli.py list --limit 1
   ```
   This will open a browser for OAuth authorization. The token is saved to
   `token-<your-email>.json`.

3. **No browser on this machine?** (devcontainer, devbox, ssh)
   ```bash
   uv run gmail_cli.py accounts add --headless
   ```
   Plain `accounts add` falls back to this automatically when it can't reach a
   browser. Three steps: open the printed URL in a browser anywhere, grant
   access, then paste back the full `localhost:1` URL you land on — the
   "connection refused" page is expected, and its address bar holds the code.

## Usage

### List emails

```bash
# Recent emails
uv run gmail_cli.py list --limit 10

# Search with Gmail query
uv run gmail_cli.py list --query "from:alice@example.com" --limit 5
uv run gmail_cli.py list --query "is:unread subject:urgent"
```

### Read emails

```bash
# By message ID
uv run gmail_cli.py read abc123def

# Multiple IDs
uv run gmail_cli.py read abc123 def456 ghi789

# By query (list + read in one step)
uv run gmail_cli.py read --query "from:bob@example.com" --limit 3
```

### Send email

```bash
# Inline body
uv run gmail_cli.py send --to "user@example.com" --subject "Hello" --body "Message here"

# From file
uv run gmail_cli.py send --to "user@example.com" --subject "Update" --file message.md

# Create draft instead of sending
uv run gmail_cli.py send --to "user@example.com" --subject "Hello" --body "Message" --draft

# With BCC recipient
uv run gmail_cli.py send --to "user@example.com" --bcc "hidden@example.com" --subject "Hello" --body "Message"
```

### Reply to email

```bash
# Reply to a message (maintains threading)
uv run gmail_cli.py reply abc123def --body "Thanks for your message!"

# Reply from file
uv run gmail_cli.py reply abc123def --file response.md

# Create draft reply instead of sending
uv run gmail_cli.py reply abc123def --body "Thanks!" --draft

# Reply with BCC
uv run gmail_cli.py reply abc123def --body "Thanks!" --bcc "hidden@example.com"
```

### Materialize an email into a directory

```bash
uv run gmail_cli.py materialize abc123def --output ./events/abc123def
```

Writes the message as a filesystem event another program can read without any
Gmail credentials:

```
events/abc123def/
  envelope.json     # id, thread_id, ts, from/to/cc, subject, labels,
                    # body_markdown, attachments manifest
  attachments/      # every attachment and inline image, sanitized names
```

Re-running against the same directory refreshes it in place — the same message
always produces the same filenames. An unknown message id exits non-zero.

### Labels

```bash
# What exists (system labels first, then yours)
uv run gmail_cli.py labels

# Apply a label, creating it if the account doesn't have it yet
uv run gmail_cli.py label abc123def --add "factory/seen"

# Several at once, and remove in the same call
uv run gmail_cli.py label abc123def --add "factory/seen" --add urgent --remove UNREAD
```

A `/` in a name is what Gmail renders as nesting — `factory/seen` shows up under
`factory` in the sidebar. System labels work by name, so `--remove UNREAD` marks a
message read and `--remove INBOX` archives it.

### Google Drive (read-only)

```bash
# Recently modified files (ID, date, type, name, owner)
uv run gmail_cli.py drive list --limit 10

# Only files other people shared with you
uv run gmail_cli.py drive list --shared

# Search by filename or full text
uv run gmail_cli.py drive search "board meeting"

# Read content — accepts a bare file ID or any Drive/Docs URL
uv run gmail_cli.py drive read 1uAO8mD6Sj24UgqNZ9TWgdznztDkeIqK
uv run gmail_cli.py drive read "https://docs.google.com/document/d/<id>/edit"

# Save to a file (required for binaries like PDFs/images)
uv run gmail_cli.py drive read <id> --output paper.pdf

# Metadata only
uv run gmail_cli.py drive info <id>
```

Google-native files are exported as text: Docs → markdown, Sheets → CSV,
Slides → plain text. Override the export format with `--mime`.

### Append to a Google Doc

```bash
uv run gmail_cli.py docs append <id-or-url> --file section.md
uv run gmail_cli.py docs append <id-or-url> --body "one-liner"
uv run gmail_cli.py docs append <id-or-url> --file x.md --dry-run  # preview only
```

Markup supported: `# ## ###` headings, `- ` bullets, `**bold**`, `*italic*`,
`~subscript~`, `^superscript^`. Markers nest, so `**m~1~ < m~2~**` keeps the
subscripts inside the bold run.

Other flags: `--plain` (insert literally), `--keep-breaks` (keep source line
breaks instead of unwrapping soft-wrapped paragraphs), `--font-size N`.

### Create and watch docs

```bash
# Create a doc, optionally seeded
uv run gmail_cli.py docs create "My doc" --file seed.md

# Poll for changes and print a unified diff of each one
uv run gmail_cli.py docs watch <id-or-url> --interval 10
uv run gmail_cli.py docs watch <id> --once --timeout 900   # exit on first change
```

`watch` uses `revisionId` as the change signal and diffs the document text, so
edits made by anyone (you, a collaborator, another tool) are reported. Detection
latency is roughly the poll interval. Google has no public API for live cursor
or keystroke presence — polling is the available mechanism.

To let Claude read a doc, just share it with your Gmail account and paste the link.

## Gmail Query Syntax

Use [Gmail search operators](https://support.google.com/mail/answer/7190):

- `from:user@example.com` - From address
- `to:user@example.com` - To address
- `subject:keyword` - Subject contains
- `is:unread` - Unread messages
- `is:starred` - Starred messages
- `has:attachment` - Has attachments
- `after:2024/01/01` - Date filter
- `label:important` - By label
