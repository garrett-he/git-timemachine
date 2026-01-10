<p align="center">
  <img src="./logo/git-timemachine.png" alt="git-timemachine" width="200">
</p>

<h1 align="center">git-timemachine</h1>

<p align="center">
  Backdate Git commits at any time node, with natural-looking jitter and configurable daily limits.
</p>

<p align="center">
  <a href="https://github.com/garrett-he/git-timemachine/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/garrett-he/git-timemachine/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/garrett-he/git-timemachine/blob/main/LICENSE"><img alt="license" src="https://img.shields.io/badge/license-MIT-blue"></a>
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-blue">
</p>

`git-timemachine` is a command-line tool that records commits on Git repositories
at arbitrary timestamps. It backdates commits with randomized jitter so the
history looks natural, while enforcing per-repository and global daily commit
limits.

Built with [Typer](https://typer.tiangolo.com/) and `pygit2` on Python 3.12+.

## Quick start

```sh
# 1. Install from source
git clone https://github.com/garrett-he/git-timemachine.git
cd git-timemachine
uv tool install .

# 2. Stage changes and record a backdated commit (jitter applied automatically)
git add .
git-timemachine commit -m "Fix typo"

# 3. Review your commit history grouped by date
git-timemachine review
```

> [!NOTE]
> On first run, `git-timemachine` initializes its config and state files under
> `~/.git-timemachine/`. No manual setup is required.

## Features

- Record commits at calculated or explicit timestamps
- Randomized time jitter so commit times look natural
- Per-repository and global daily commit limits
- Shift the persisted base timestamp forward or backward
- Review commit history grouped by date
- Inspect and update internal state values

## Requirements

- Python 3.12 or newer
- Git
- [uv](https://docs.astral.sh/uv/) (recommended for installation and development)

## Installation

Install from source with `uv`:

```sh
git clone https://github.com/garrett-he/git-timemachine.git
cd git-timemachine
uv tool install .
```

Or with `pip`:

```sh
pip install .
```

Run on demand without a permanent install:

```sh
uvx --from . git-timemachine --version
```

## Usage

The entry point is the `git-timemachine` command. Global options must be placed
before the subcommand.

```text
git-timemachine [--repo-dir PATH | -C PATH] [--version] COMMAND
```

| Option                | Description                                                 |
| --------------------- | ----------------------------------------------------------- |
| `-C, --repo-dir PATH` | Path of the target repository (default: current directory). |
| `--version`           | Print the installed version and exit.                       |

### commit

Record a commit at a calculated timestamp. Extra arguments after the options are
forwarded to `git commit`.

```text
git-timemachine commit [--jitter-min SECONDS] [--jitter-max SECONDS] [--at DATETIME] [ARGS]...
```

| Option                     | Description                                                                                                           |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `-j, --jitter-min SECONDS` | Minimum time jitter (overrides `jitter_min`).                                                                         |
| `-J, --jitter-max SECONDS` | Maximum time jitter (overrides `jitter_max`).                                                                         |
| `--at DATETIME`            | ISO datetime used as the base commit time (e.g. `2024-06-15T14:30:00`). Defaults to the persisted `last_commit_time`. |
| `ARGS`                     | Extra arguments forwarded to `git commit` (e.g. `-m "message"`).                                                      |

```sh
git-timemachine commit -m "Fix typo"
git-timemachine commit --at "2024-06-15T14:30:00" -m "Backdated fix"
git-timemachine commit --jitter-min 60 --jitter-max 600 -m "Update docs"
```

> [!IMPORTANT]
> Before committing, the command validates that staged changes exist, the
> commit time is not earlier than `HEAD`, and the daily commit limits are
> respected. It then applies random jitter in `[jitter_min, jitter_max]`
> seconds and runs `git commit` with matching `GIT_AUTHOR_DATE` and
> `GIT_COMMITTER_DATE` values.

### shift

Adjust the persisted base timestamp in the state file forward or backward.

```text
git-timemachine shift --days N [--hours-min 0-23] [--hours-max 0-23]
```

| Option                 | Description                                         |
| ---------------------- | --------------------------------------------------- |
| `-d, --days N`         | Number of days to shift (negative shifts backward). |
| `-h, --hours-min 0-23` | Minimum hour for a randomized time of day.          |
| `-H, --hours-max 0-23` | Maximum hour for a randomized time of day.          |

```sh
git-timemachine shift --days -1
git-timemachine shift --days 1 --hours-min 9 --hours-max 18
```

### review

Print the commit history of the repository grouped by date.

```sh
git-timemachine review
```

### states

Get, set, or list internal state values.

```text
git-timemachine states                  # list all states
git-timemachine states KEY              # get a state value
git-timemachine states KEY VALUE        # set a state value
```

```sh
git-timemachine states
git-timemachine states last_commit_time
git-timemachine states last_commit_time "2024-06-15T14:30:00"
```

## Configuration

On first run, `git-timemachine` creates two YAML files under
`~/.git-timemachine/`. Their locations can be overridden with environment
variables.

### Settings

Path: `~/.git-timemachine/settings.yaml`
(override with `GIT_TIMEMACHINE_SETTINGS`).

| Key                       | Default | Description                                               |
| ------------------------- | ------- | --------------------------------------------------------- |
| `max_repo_daily_commits`  | `5`     | Maximum commits per repository per day.                   |
| `max_total_daily_commits` | `15`    | Maximum total commits per day across repositories.        |
| `jitter_min`              | `600`   | Minimum random jitter added to a commit time, in seconds. |
| `jitter_max`              | `3600`  | Maximum random jitter added to a commit time, in seconds. |

### States

Path: `~/.git-timemachine/states.yaml`
(override with `GIT_TIMEMACHINE_STATES`).

| Key                   | Description                                         |
| --------------------- | --------------------------------------------------- |
| `last_commit_time`    | Datetime used as the base time for the next commit. |
| `current_commit_date` | The date the daily counter applies to.              |
| `daily_commit_count`  | Number of commits recorded on the current date.     |

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management and
[just](https://just.systems/) as a task runner.

```sh
just install   # install dependencies and pre-commit hooks
just check     # run linters and formatters (check mode)
just format    # apply formatters and auto-fixes
just test      # run the test suite with coverage
just ci        # run check and test together
just build     # build the distribution
just publish   # publish the distribution
```

The linting stack includes `ruff`, `pyrefly`, `rumdl`, and `pyproject-fmt`.
Tests run under `pytest` with a coverage threshold of 80%.
