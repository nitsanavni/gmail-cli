# Collaborating with a human inside a Google Doc

A playbook for an agent working *in* a document alongside a person, rather than
reading it once. Written from a session that built this and hit every trap below.

## The working setup

Two watchers over one doc, with different jobs and cadences:

```bash
RECEIPT="⟳ seen by Claude at"
DOC=<id-or-url>

# 1. Fast signal: stamps a receipt line the moment anything changes.
#    Detached; its stdout is not interesting.
gmail docs watch $DOC --interval 1 \
  --receipt "$RECEIPT" --ignore-prefix "$RECEIPT" \
  --state /tmp/fast.state > /tmp/fast.log 2>&1 &

# 2. Reader: coalesces bursts into readable diffs and wakes the agent.
#    Run under a Monitor so each diff arrives as a notification.
gmail docs watch $DOC --interval 2 --debounce 4 --context 2 \
  --ignore-prefix "$RECEIPT" --state /tmp/read.state
```

Why two: proof-of-receipt and readable content want opposite settings. One
watcher forces a compromise that is wrong for both. The user proposed this split
and it is better than tuning a single watcher.

Run the reader under `Monitor(persistent: true)`, not `Bash(run_in_background)`.
A background command notifies once, on exit, which forces a `--once` +restart
cycle and a blind gap between runs. Monitor turns every stdout line into a
notification, so the process never has to exit.

## Traps, and why each one bites

**Self-wake.** The Docs API exposes no author on a revision, so a watcher cannot
tell its own writes from the user's. Left alone, the agent's reply wakes the
agent. Two defences, both needed: `append --state` re-baselines after writing,
and a long-running watcher re-reads that state file each poll (it holds its
baseline in memory and would otherwise never see the update).

**The restart gap.** With `--once`, anything typed between one watcher exiting
and the next starting is absorbed into the new baseline and is *invisible*, not
merely late. This silently ate a user's sentence. `--state` persists the
baseline across runs and reports the difference as "missed while not watching".

**Mid-typing.** Docs saves continuously, so any poll can land mid-word. Polling
faster makes this worse, not better. Separate the two concerns: poll fast to
notice, `--debounce` to report only once typing stops. Then let the *agent*
judge completeness — if a diff ends mid-sentence, stay quiet and wait for the
next event rather than answering a fragment.

**Two watchers chasing each other.** A receipt-stamping watcher writes to the
doc, which is a change, which the other watcher reports, forever.
`--ignore-prefix` excludes the receipt line from the compared text, breaking the
loop at the source.

**Line numbers are meaningless in a doc.** A raw unified diff orients the tool,
not the reader. Hunks are labelled with the section they fall under instead.

## Writing into a shared doc

**Style is inherited from the insertion point.** Appending after subscripted
math (`m₁`, `mₐ`) made an entire section render as subscript — small and low —
while the API faithfully reported the requested font size. Three rounds of
checking `fontSize` found nothing; the HTML export's computed CSS
(`vertical-align:sub`) showed it immediately. Always reset `baselineOffset`,
`bold`, `italic`, `underline`, `strikethrough` over the inserted range.

**Verify rendering via the HTML export, not `documents.get`.** The API reports
what you asked for. The export reports what the reader sees. Every styling bug
in this session was invisible in the former and obvious in the latter.

**Docs indexes in UTF-16 code units.** Python strings are code points. One emoji
shifts every subsequent style range one character early — subscripting the `m`
instead of the `a`. Use `u16_offsets()`, never `len()`. This is invisible in any
text without a non-BMP character, so it will pass casual testing.

**The final newline cannot be deleted.** `deleteContentRange` on the last
paragraph must stop at `endIndex - 1`, or Docs rejects the request.

**Reply in place, not at the bottom.** `--after ANCHOR` inserts below the
paragraph containing the anchor. It errors on zero or multiple matches rather
than guessing, because a wrong guess edits the user's document somewhere they
did not ask for.

**Self-identify.** Label contributions (`**Claude:**` inline, an italic
attribution note for a whole section). A mixed-authorship doc has no diff view
or avatars; without a label the reader cannot separate their thinking from the
agent's. Requested explicitly, then confirmed unprompted as more readable.

## Comments as a collaboration surface

Less intrusive than writing in the body, and anchored: the user selects the text
they mean and comments on it, so the thread carries its own context. The agent
replies in-thread and the document body stays the user's.

```bash
gmail drive comments <doc>              # open threads, with the text each anchors to
gmail drive reply <doc> <comment-id> --body "..." [--resolve]
gmail drive comment <doc> --body "..."  # unanchored, agent-initiated
```

Reading comments needs only `drive.readonly`; creating or replying needs a Drive
**write** scope (`drive.file` reaches only app-created files; `drive` reaches
everything). Ask the user before widening this — it is the broadest scope here.

**Attribution is the user's, not the agent's.** The token belongs to the user, so
every comment and reply is authored by *them* in the Drive UI. There is no way to
present a separate identity. Always open the text with an explicit `Claude:` (or
similar) marker — otherwise the user sees their own name saying things they never
wrote. This matters more here than in the body, where the agent at least controls
the whole paragraph.

**Anchor, or the user never sees it.** An unanchored comment frequently does not
render in the Docs UI at all — it exists only via the API. `drive comment
--anchor-text "..."` builds the anchor from the undocumented legacy shape
`{"r": revision, "a":[{"txt":{"o": offset, "l": length}}]}`, where offset is the
Docs index minus one. Note the user may still need to open the comment pane.

**Comments need their own watcher.** Document text and comments are different
APIs; `docs watch` sees no comment activity whatsoever. Use `drive
watch-comments` alongside it, under its own Monitor.

**Self-wake applies here too, and is worse.** Because Drive attributes agent
comments to the *user*, a comment watcher cannot filter its own writes out by
author. `drive comment`/`drive reply` take `--state` and claim their own IDs in
the watcher's state file — the same contract as `docs append --state`. Expect
this failure mode on every new surface: any channel the agent can write to and
watch will feed itself unless the writer marks its output.

## Etiquette

- **Acknowledge in the doc before doing the work.** The person may be working
  only in the document, with no view of the chat stream. Silence there reads as
  absence, however busy the agent is elsewhere.
- **Clean up test artifacts.** Probe lines written while verifying behaviour are
  the agent's mess, not content.
- **Only one watcher per state file.** A stray second watcher consumes changes
  and the intended one never sees them.
