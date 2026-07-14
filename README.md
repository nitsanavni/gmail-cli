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
   This will open a browser for OAuth authorization. Token is saved to `token.json`.

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

# With attachments (repeat --attach for more than one)
uv run gmail_cli.py send --to "user@example.com" --subject "Report" --body "Attached" --attach report.pdf
uv run gmail_cli.py send --to "user@example.com" --subject "Files" --body "Two" --attach a.pdf --attach b.png
```

Gmail caps a message at 25MB. Attachments are base64-encoded, which adds
roughly a third to each file's size, so the practical ceiling is lower than
25MB of raw files.

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

# Reply with an attachment
uv run gmail_cli.py reply abc123def --body "Here it is" --attach report.pdf
```

### Archive emails

Removes the `INBOX` label, matching Gmail's native archive behavior.

```bash
# Archive one message
uv run gmail_cli.py archive abc123def

# Archive several at once
uv run gmail_cli.py archive abc123 def456 ghi789
```

Archiving needs the `gmail.modify` scope. The first archive run after
upgrading re-opens the browser to grant it.

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
