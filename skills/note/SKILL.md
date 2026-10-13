---
name: note
description: Appends a timestamped line to the current project's note.md, a private gitignored log of observations and decisions about that project. Use when the user says "note this down", "take a note", or "add to my notes".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(git rev-parse *)
  - Bash(date *)
---

Arguments passed: $ARGUMENTS

## Step 1: Locate the target file

Run in parallel:

```bash
git rev-parse --show-toplevel 2>/dev/null || pwd
date "+%Y-%m-%d %H:%M"
```

The target is `<root>/note.md`, where `<root>` is the git toplevel — or the current directory when outside a git repo. Never write into a subdirectory.

## Step 2: Decide the note text

- **Arguments given** — record them verbatim. Fix spelling and punctuation only; do not rephrase, expand, or append context from the conversation.
- **No arguments** — condense the most recent topic of the conversation into one sentence and record that.

## Step 3: Prepare the file

Read `note.md` at the target path.

**Missing** — write it with a single `# Notes` heading, then keep the notes private:

1. Read `.gitignore` at the same root (create it if absent).
2. Unless `note.md` is already listed, append a `note.md` line.
3. Tell the user both things happened.

Skip the `.gitignore` work entirely when outside a git repo, and on every later run once `note.md` exists.

## Step 4: Append the note

Use today's date from Step 1 as the section heading:

- **Section exists** — insert the note as the last line of that section.
- **Section missing** — append a blank line, `## YYYY-MM-DD`, then the note at the end of the file.

Each note is one line: `- HH:MM — <note>` (em dash, 24-hour local time).

```markdown
# Notes

## 2026-08-01
- 14:20 — move to expo router v4

## 2026-08-02
- 09:12 — redis cache TTL will be 300s
```

Multi-line input collapses into that single line; keep line breaks only when the note is a list the user wrote as a list, indenting continuation lines by two spaces.

## Step 5: Report

State the absolute path written and the exact line appended.

## Edge cases

**Existing note.md with a different shape** (no `# Notes` heading, flat bullets, other headings): append the note under a new date section at the end and leave the rest of the file untouched. Never reformat existing content.

**Repeated calls in the same minute**: append a second line with the same timestamp — do not merge notes.

**Empty conversation and no arguments**: ask what to note instead of guessing.
