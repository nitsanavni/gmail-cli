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
