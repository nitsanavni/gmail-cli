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

# Just the IDs, one per line — for scripts and poll loops
uv run gmail_cli.py list --query "has:attachment -label:factory/seen" --ids-only
```

Each row carries its thread context and names the command that opens it:

```
[2] ID: 19fdc1aed4900463
    From: Nitsan Avni <nitsan@askeffi.ai>
    Subject: Re: AskEffi Feedback
    Date: 2026-08-07 12:02
    Thread: 19fd8c7cb5f0667b · 6 msgs · this is the latest
    "Update about the failed Scheduled Reports runs. We've identified the cau…"
    → gmail thread 19fd8c7cb5f0667b
```

`this is the latest` / `2 newer in thread` is the message's position by time
inside its thread — so a row you are about to reply to says whether someone has
already answered. A thread of one prints only the snippet: most of an inbox is
singletons, and a Thread line on every row buries the rows that have one.

The context is free. One `threads.get` returns every sibling's headers, so the
distinct threads behind N rows are fetched instead of the N messages, not on top
of them — same round-trips as before, or fewer when rows share a thread.

`--ids-only` prints nothing at all when the query matches nothing, so a shell
`for` over its output iterates zero times instead of once over a prose line. It
also skips the thread fetch entirely, so N ids cost one round-trip.

### See a thread

```bash
uv run gmail_cli.py thread 19fd8c7cb5f0667b   # thread ID
uv run gmail_cli.py thread 19fdbee34965cafe   # or any message ID in it
```

The structure level between `list` and `read` — who said what, when, and which
messages carry attachments, without a single body:

```
Thread: 19fd8c7cb5f0667b · "Fwd: AskEffi Feedback" · 6 messages
[1] 19fd8c7cb5f0667b · 2026-08-06 20:34 · Guy Levit <guy@askeffi.ai> · 📎 3
    "Team - can you have a look? Deleting a project is a feature we haven't b…"
[2] 19fd91cf28865c30 · 2026-08-06 22:06 · Lihu Berman <lihu@askeffi.ai> · 📎 3 · unread
    "Sure, I'll take archiving. Nitsan, will you look at the scheduled reports…"

→ gmail read 19fdc1aed4900463 · gmail materialize 19fdc1aed4900463 -o <dir>
```

Messages are ordered oldest-first by `internalDate`. `📎 N` appears only on
messages that have attachments, `unread` only on unread ones, and the closing
hint uses the last message's real id. One API call for the whole thread.

Passing a *message* id works because that is what every other command prints:
the thread lookup is tried first and only falls back to resolving the message
when it 404s.

### Read emails

```bash
# By message ID
uv run gmail_cli.py read abc123def

# Multiple IDs
uv run gmail_cli.py read abc123 def456 ghi789

# By query (list + read in one step)
uv run gmail_cli.py read --query "from:bob@example.com" --limit 3
```

The `Thread-ID` line says where the message sits in its conversation, and the
attachments are named after the body:

```
Message-ID: 19fdbee34965cafe
Thread-ID: 19fd8c7cb5f0667b (message 5 of 6 · 1 newer)
→ gmail thread 19fd8c7cb5f0667b
...

---
Attachments (3): image.png (111KB image/png), image-1.png (34KB image/png), image-2.png (97KB image/png)
→ gmail materialize 19fdbee34965cafe -o <dir>
```

Both blocks are omitted when there is nothing to say — a single-message thread
prints the bare `Thread-ID:` line, and a message with no attachments prints
nothing after the body. The filenames are the ones `materialize` would write, so
the listing predicts the directory rather than spelling it differently. Sizes
come from the payload we already fetched, so the block costs no API calls; the
position line costs one `threads.get` per distinct thread being read.

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
