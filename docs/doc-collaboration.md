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

## Etiquette

- **Acknowledge in the doc before doing the work.** The person may be working
  only in the document, with no view of the chat stream. Silence there reads as
  absence, however busy the agent is elsewhere.
- **Clean up test artifacts.** Probe lines written while verifying behaviour are
  the agent's mess, not content.
- **Only one watcher per state file.** A stray second watcher consumes changes
  and the intended one never sees them.
