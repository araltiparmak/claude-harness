# my-harness

My Claude Code setup: the general-purpose skills I wrote, the script that installs and updates every skill I use, and a record of the plugins I install.

Skills come from three repos:

- **this repo**: my general-purpose skills, in `skills/<name>/`;
- **[private-skills](https://github.com/araltiparmak/private-skills)** (private): skills tied to my own projects, accounts and vault;
- **[mattpocock/skills](https://github.com/mattpocock/skills)**: Matt Pocock's engineering and productivity skills.

See [`HARNESS.md`](HARNESS.md) for plugins and other skills installed from elsewhere.

## Install

```bash
git clone https://github.com/araltiparmak/my-harness.git ~/dev/my-harness
~/dev/my-harness/scripts/update.sh
```

`update.sh` pulls all three repos (cloning any that are missing to `~/dev/`), then symlinks their skills into `~/.claude/skills/`. Run it again to update; the `us` alias in [terminal-aliases](https://github.com/araltiparmak/terminal-aliases) runs it. On a machine without access to `private-skills`, that clone fails and the rest still links. It links Matt's promoted buckets (`engineering`, `productivity`); set `MATT_BUCKETS` to change that. My skills win a name clash with Matt's, and entries in `~/.claude/skills/` that are not links into these repos are left alone.

## Skills

| Skill | What it does |
|---|---|
| [mobile-app-stack](skills/mobile-app-stack/SKILL.md) | Recommends the default stack for a new Expo + React Native + TypeScript app, one decision at a time |
| [note](skills/note/SKILL.md) | Appends a timestamped line to the current project's private `note.md` |
| [react-project](skills/react-project/SKILL.md) | Scaffolds a React + Vite + TS + Tailwind prototype in `~/dev` via `cra` and builds v1 (user-invoked: `/react-project`) |
| [vercel](skills/vercel/SKILL.md) | Deploys a Vite/React project to Vercel, or repairs its deploy path |
