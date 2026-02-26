# AGENTS.md

Guidance for AI coding agents working in the `git-timemachine` repository.

## Project Overview

`git-timemachine` is a command-line tool that records Git commits at arbitrary
timestamps with randomized jitter while enforcing configurable daily commit
limits. It is built with [Typer](https://typer.tiangolo.com/) on Python 3.12+
and uses `pygit2` for repository inspection and `git commit` (via `subprocess`)
for the actual writes.

Key technologies:

- Language: Python 3.12+ (fully type-annotated).
- CLI framework: `typer`.
- Git: `pygit2` for inspection, `subprocess` calls to `git commit` for writes.
- Config/state: `pydantic` models serialized to YAML (`pyyaml`).
- Packaging: `hatchling` via `uv`.
- Tasks: `just`.
- Tests: `pytest` + `pytest-cov` (coverage threshold 80%).
- Lint/format: `ruff`, `pyrefly`, `rumdl`, `pyproject-fmt`.

## Repository Layout

- `src/git_timemachine/` - application package.
    - `cli.py` - Typer app, global callback, command registration.
    - `config.py` - `BaseConfig`, `Settings`, `States` pydantic models with YAML
      load/save.
    - `git.py` - validation helpers and the external `git commit` runner.
    - `commands/` - one module per subcommand: `commit`, `retime`, `shift`,
      `review`, `states`.
- `tests/` - pytest suite mirroring the command modules.
- `justfile` - task runner recipes.
- `pyproject.toml` - project metadata, dependencies, and tool config.

## Setup Commands

- Install dependencies and pre-commit hooks: `just install`
- Run the CLI from source: `uv run git-timemachine --version`
- Run on demand without installing: `uvx --from . git-timemachine --version`

The project uses [uv](https://docs.astral.sh/uv/) for dependency management.
Dev dependencies live in the `dev` optional-dependency group and are synced
with `uv sync --extra dev`.

## Development Workflow

Always run `just ci` before finishing a task. Key recipes:

- `just install` - sync dev dependencies and install pre-commit hooks.
- `just check` - run `ruff check`, `ruff format --check`, `pyrefly check`,
  `pyproject-fmt --check`, `rumdl check`.
- `just format` - apply `ruff format`, `pyproject-fmt`, `rumdl check --fix`.
- `just test` - run `pytest` with coverage.
- `just ci` - run `check` and `test` together.
- `just build` - build distributions with `uv build`.
- `just publish` - publish distributions with `uv publish`.

There is no long-running dev server; the tool is a CLI invoked per command.

## Testing Instructions

- Run the full suite: `just test` (or `uv run pytest`).
- Coverage threshold is enforced at 80% (`--cov-fail-under=80`).
- pytest options: `-ra --strict-markers --strict-config
--cov=git_timemachine --cov-report=term-missing`.
- Tests live in `tests/` and mirror command modules
  (`test_commands_commit.py`, `test_commands_review.py`,
  `test_commands_shift.py`, `test_commands_states.py`, `test_version.py`).
- Shared fixtures/helpers: `tests/conftest.py` and `tests/_helpers.py`; static
  fixtures under `tests/assets/`.
- Add or update tests for any new command behavior or validation rule.

## Code Style

- Line length 120 for code; Markdown prose wraps near 88 characters.
- 4-space indentation (2 spaces for YAML); LF line endings.
- Single quotes for Python strings.
- Docstrings follow the Google convention (`pydocstyle`).
- Every parameter, return, and attribute must be type-annotated; `pyrefly`
  runs in the `strict` preset and treats untyped imports as errors.
- Ruff rule sets: `A`, `B`, `C4`, `D`, `E`, `F`, `I`, `N`, `RUF`, `SIM`,
  `TCH`, `UP`, `W`.
- Do not edit linter/formatter config to bypass failures; fix the code.

## CLI Commands

The entry point is `git_timemachine.cli:app` (script `git-timemachine`).
Global options must precede the subcommand.

- Global options: `--repo-dir/-C PATH`, `--version`.
- `commit` - record a commit at a calculated timestamp; forwards extra args to
  `git commit`. Options: `--jitter-min/-j`, `--jitter-max/-J`, `--at`.
- `retime` - replay `COMMIT_ID..HEAD` in place with fresh timestamps.
  `COMMIT_ID` accepts a full SHA or an abbreviated SHA of at least 6 characters.
  Options: `--jitter-min/-j`, `--jitter-max/-J`.
- `shift` - move the persisted `last_commit_time` by days, optionally
  randomizing the time of day. Options: `--days/-d`, `--hours-min/-h`,
  `--hours-max/-H`.
- `review` - print commit counts grouped by date.
- `states` - get, set, or list values in the state file.

## Runtime Files

Both files are created on first run and can be relocated with environment
variables.

- Settings: `~/.git-timemachine/settings.yaml`
  (`GIT_TIMEMACHINE_SETTINGS`). Holds `max_repo_daily_commits`,
  `max_total_daily_commits`, `jitter_min`, `jitter_max`.
- States: `~/.git-timemachine/states.yaml` (`GIT_TIMEMACHINE_STATES`). Tracks
  `last_commit_time`, `current_commit_date`, `daily_commit_count`.
- Retime session: `<repo>/.git/git-timemachine-session.yaml` (per repository).
  Holds replay progress, snapshot commits, backup branch, and expected HEAD.

## Commit Command Internals

`commit` is the core flow. When modifying it, preserve these invariants:

1. Base time is `--at` if given, otherwise `states.last_commit_time`.
2. Validate before mutating state: commit time is not earlier than `HEAD`,
   staged changes exist, and daily limits (`max_repo_daily_commits`,
   `max_total_daily_commits`) are not exceeded.
3. Only after all checks pass, update `daily_commit_count` and
   `current_commit_date`.
4. Apply random jitter in `[jitter_min, jitter_max]` seconds.
5. Run `git commit` via `git_external_commit` with `GIT_AUTHOR_DATE` and
   `GIT_COMMITTER_DATE` set to the final time, then persist
   `last_commit_time`.

## Retime Command Internals

`retime` rewrites `COMMIT_ID..HEAD` in place. Preserve these invariants:

1. Validate branch state, clean worktree, merge-free linear range, and
   ancestor relationship before creating the backup branch or rewriting.
2. Snapshot the commit range (oid and emptiness) before any rewrite; never
   re-read the live history while replaying.
3. Create `<branch>-gtm-backup` and never overwrite an existing backup.
4. Replay each snapshot with `record_commit(..., reuse_from=oid,
   allow_empty=is_empty)`, which injects `-C <oid> --date=<final>` so both
   author and committer times change while message and author identity stay.
5. On `DailyCommitLimitError`, prompt before shifting `last_commit_time` by one
   day; on refusal or any failure, restore index/worktree to the current HEAD
   and keep already replayed commits.
6. Root commits use `update-ref -d` plus `read-tree --empty` and
   `clean -fd` before replaying, since there is no parent to reset to.
7. Persist progress to `.git/git-timemachine-session.yaml` after each successful
   commit; `--continue` validates branch, backup target, remaining objects, and
   the expected HEAD before resuming. Delete the session only after success.
8. Never start a new replay while a session file exists; require `--continue`
   or explicit deletion. `Ctrl-C` exits with code 130 after restoring the
   worktree and keeps the session resumable.

## Build and Deployment

- Build distributions: `just build` (`uv build`).
- Publish to PyPI: `just publish` (`uv publish`).
- CI workflow: `.github/workflows/ci.yml` runs `just install` then `just ci`
  on `ubuntu-latest` across Python 3.12, 3.13, and 3.14, triggered on pushes
  to `main` and on pull requests.

## Do Not

- Do not print or modify `.env` files.
- Do not run destructive commands (e.g. `rm -rf`, force-push, hard resets)
  without explicit confirmation.
- Do not bump core dependency major versions.
- Do not edit linter/formatter config to bypass failures; fix the code.
