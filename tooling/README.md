# nrfmodule code-quality tooling

Shared, reuse-once quality gate for every nrfmodule repo. Lives in the manifest
repo (already present in every west workspace at `config/manifest/tooling/`), so
products consume it without copying anything.

## What it enforces vs. reports

| Check | Mode | Catches |
|-------|------|---------|
| `checks/no-ifdef-config.sh` | **enforced** (fails) | `#ifdef CONFIG_X` → use `#if defined(CONFIG_X)` |
| `checks/paren-numeric-defines.sh` | **enforced** (fails) | `#define X 1000` → `#define X (1000)` |
| `checks/no-ai-attribution.sh` | **enforced** (commit-msg) | AI attribution in commit messages |
| clang-format (`.clang-format`) | **advisory** (reports, never blocks/reformats) | formatting drift vs. the canonical Zephyr style |
| checkpatch (Zephyr) | advisory, opt-in (`RUN_CHECKPATCH=1`) | broad Zephyr coding-style issues |

clang-format is **advisory by design**: the codebase uses deliberate hand-alignment
(aligned struct tables, switch cases, stub braces) that clang-format would collapse.
We surface drift to catch agent-introduced inconsistency, then decide per-case —
we never auto-reformat.

## Run it

```bash
# staged files (default), a git range, all files, or explicit files:
bash tooling/check.sh
bash tooling/check.sh --range origin/main..HEAD
bash tooling/check.sh --all
bash tooling/check.sh src/foo.c src/foo.h
```

Env overrides: `CLANG_FORMAT`, `CHECKPATCH`, `NRFMODULE_TOOLING`,
`RUN_CHECKPATCH=1`, `CLANG_FORMAT_VERBOSE=1`.

clang-format is found on `PATH`, via `$CLANG_FORMAT`, or the pip `--user` install
(`pip install clang-format`). If absent, the advisory step is skipped — the
enforced rule checks still run.

## Adopt in a repo

**Local git hooks** (pre-commit gate + commit-msg AI-attribution check), no
per-repo files — uses `core.hooksPath`:

```bash
bash <workspace>/config/manifest/tooling/install-hooks.sh   # run inside the repo
```

**CI** — add a wrapper workflow (`.github/workflows/lint.yml`):

```yaml
name: Lint
on: [pull_request]
jobs:
  lint:
    uses: nrfmodule/nrfmodule-dev-manifest/.github/workflows/reusable-lint.yml@main
    secrets: inherit
```

**Agents** — a global `~/.claude` PostToolUse hook runs the rule checks on every
C/C++ edit and feeds violations back so the agent self-corrects in-session
(conditional: no-ops outside nrfmodule projects). See the hook script under
`~/.claude/hooks/`.

## Change a rule once, everywhere

Rules live here in the manifest (pinned by `west.yml`); the CI image carries the
tools. Edit a check or `.clang-format` once and every repo picks it up on the
next `west update` / CI run — no copy-paste drift.
