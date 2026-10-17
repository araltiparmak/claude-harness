---
name: todo
description: Adds an item to the current project's todo.md checklist, or ticks one off. Use when the user says "add a project todo", "put this on this project's todo list", "add to todo.md", "todo: <something>", or "mark <item> as done" for the project's list. A list that spans all projects is a different skill (todo-general).
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(git rev-parse *)
---

Arguments passed: $ARGUMENTS

## Step 1: Locate the file

```bash
git rev-parse --show-toplevel 2>/dev/null || pwd
```

The file is `<root>/todo.md`, where `<root>` is the git toplevel, or the current directory outside a git repo. Never write into a subdirectory.

## Step 2: Decide what to do

- **Add** (the default): the user names something to do.
- **Done**: the user says an item is finished ("mark X as done", "tick off X", "X is done").

For an add:

- **Arguments given**: record them as one imperative line. Fix spelling and punctuation only; do not rephrase, expand, or append context from the conversation.
- **No arguments**: condense the most recent open action item in the conversation into one imperative sentence. If there is none, ask what to add instead of guessing.

## Step 3: Prepare the file

Read `todo.md`.

**Missing**: create it with a single `# Todo` heading. Do not touch `.gitignore`. Tell the user the file is a normal file in the project: commit it to share the list, or add `todo.md` to `.gitignore` to keep it private.

## Step 4: Write

**Add**: append `- [ ] <text>` as the last item. If an identical unchecked item already exists, say so and add nothing.

**Done**: change `- [ ]` to `- [x]` on the unchecked item that matches the user's words. If more than one item matches, list them and ask which. If none matches, say so and add nothing. Do not move, reorder or delete items.

```markdown
# Todo

- [x] Pin the Node version
- [ ] Add a loading state to the orders table
- [ ] Write the migration runbook
```

Multi-line input collapses into one line. Keep line breaks only when the user wrote a list: each line becomes its own item.

## Step 5: Report

State the absolute path and the exact line added or changed.

## Edge cases

**Existing todo.md with a different shape** (no `# Todo` heading, other sections, plain bullets): append the new item at the end of the file in the same checkbox style, and leave the rest untouched. Never reformat existing content.

**Wrong list**: when the user means a list that spans all their projects, say that is the `todo-general` skill, if it is installed, and stop.
