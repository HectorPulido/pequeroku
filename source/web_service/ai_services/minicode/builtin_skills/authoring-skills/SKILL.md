---
name: authoring-skills
description: Create or edit a reusable skill for this workspace. Use when the user asks you to make/save a skill, or when you notice a repeatable workflow worth capturing for future turns.
---

# Authoring a skill

A skill is a reusable, self-contained set of instructions for a specific task. The
agent sees only the name + description of each available skill, and loads a skill's
full body on demand with the `skill` tool (progressive disclosure). This guide tells
you how to create one in THIS workspace.

## Where skills live

Project skills live in the user's VM under:

    /app/.pequenin/skills/<name>/SKILL.md

One folder per skill. The folder may also contain helper files (e.g. `scripts/`,
`reference/`) next to `SKILL.md`.

## SKILL.md format

A YAML frontmatter block, then a Markdown body:

    ---
    name: git-release
    description: Draft release notes and changelogs from merged PRs. Use when preparing a tagged release.
    ---

    # What I do
    ...step-by-step instructions...

## Frontmatter rules (these are enforced; get them wrong and the skill is skipped)

- `name` — REQUIRED. Lowercase letters/digits joined by single hyphens
  (`^[a-z0-9]+(-[a-z0-9]+)*$`), 1–64 chars, and it MUST equal the folder name. So
  `name: git-release` must live in `.../skills/git-release/SKILL.md`. A mismatch is
  the #1 reason a new skill silently fails to appear.
- `description` — REQUIRED, 1–1024 chars. Write WHEN to use the skill, specifically —
  this is all the agent sees when deciding whether to load it. Be concrete.
- `license`, `compatibility`, `metadata` — optional and ignored by loading.

## Body

Plain Markdown instructions: the actual workflow, commands, conventions, and any
gotchas. Keep it focused and high-signal. If the skill bundles helper files, refer to
them by RELATIVE path (e.g. `scripts/release.sh`); they resolve against the skill's
own folder (the loader tells you the base directory when the skill is loaded).

## How to create one

1. Pick a kebab-case `<name>`.
2. Use the `write` tool to create `/app/.pequenin/skills/<name>/SKILL.md` with the
   frontmatter + body above. (`write` creates the parent folders.)
3. Optionally `write` any helper files in the same folder.
4. The new skill is discovered on the NEXT turn (discovery runs once, at the start of
   each turn). To verify, check that it appears in the available-skills block of your
   context next turn.

## Editing an existing skill

`read` its `SKILL.md`, then `edit` it. Don't rename `name` without also moving the
folder so they keep matching.

## Gotchas

- `name` != folder name → the skill is silently skipped.
- Missing or empty `description` → skipped.
- A skill created mid-turn is NOT loadable via `skill(name)` until the next turn (you
  can still `read` the file you just wrote).
- Skills are VM files: they persist with the workspace but are wiped on a workspace
  reset. Don't put secrets in them.
