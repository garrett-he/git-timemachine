"""Commit command for recording commits at calculated timestamps."""

import random
from datetime import datetime, timedelta
from typing import Annotated

import typer
from pygit2 import GitError, Repository, discover_repository

from git_timemachine.config import Settings, States
from git_timemachine.git import (
    DailyCommitLimitError,
    check_repo_commit_status,
    check_repo_commit_time,
    check_repo_max_daily_commits,
    git_external_commit,
)


def record_commit(
    repo: Repository,
    settings: Settings,
    states: States,
    args: list[str],
    *,
    base_time: datetime | None = None,
    jitter_min: int | None = None,
    jitter_max: int | None = None,
    allow_empty: bool = False,
    reuse_from: str | None = None,
) -> datetime:
    """Record a commit using git-timemachine validation and jitter rules.

    Args:
        repo: Repository to commit into.
        settings: Application settings holding limits and jitter defaults.
        states: Persisted state updated after a successful commit.
        args: Extra arguments forwarded to `git commit`.
        base_time: Base commit time; defaults to `states.last_commit_time`.
        jitter_min: Minimum jitter in seconds; defaults to `settings.jitter_min`.
        jitter_max: Maximum jitter in seconds; defaults to `settings.jitter_max`.
        allow_empty: Skip the staged-changes check and allow empty commits.
        reuse_from: Commit ID whose message and author identity should be reused.

    Returns:
        The final commit time including jitter.

    Raises:
        DailyCommitLimitError: When a configured daily commit limit is exceeded.
        GitError: When the commit cannot be recorded.
    """
    effective_jitter_min = jitter_min if jitter_min is not None else settings.jitter_min
    effective_jitter_max = jitter_max if jitter_max is not None else settings.jitter_max
    commit_time = base_time if base_time is not None else states.last_commit_time

    is_same_day = commit_time.date() == states.current_commit_date
    new_daily_count = (states.daily_commit_count + 1) if is_same_day else 1
    commit_date = commit_time.date()

    # Validate every prerequisite before mutating state or creating the commit.
    check_repo_commit_time(repo, commit_time)
    if not allow_empty:
        check_repo_commit_status(repo)

    if new_daily_count > settings.max_total_daily_commits:
        raise DailyCommitLimitError(f'Exceeded the total daily commit limit: {settings.max_total_daily_commits}.')

    check_repo_max_daily_commits(repo, commit_time, settings.max_repo_daily_commits)

    random.seed()
    commit_time += timedelta(seconds=random.randint(effective_jitter_min, effective_jitter_max))

    final_args = list(args)
    if reuse_from is not None:
        date_arg = commit_time.replace(microsecond=0).astimezone().isoformat()
        final_args += ['-C', reuse_from, f'--date={date_arg}']
    if allow_empty:
        final_args.append('--allow-empty')

    git_external_commit(repo, final_args, commit_time)

    if is_same_day:
        states.daily_commit_count = new_daily_count
    else:
        states.current_commit_date = commit_date
        states.daily_commit_count = 1

    states.last_commit_time = commit_time
    states.save()

    return commit_time


def commit_command(
    ctx: typer.Context,
    jitter_min: int | None = typer.Option(None, '--jitter-min', '-j', help='Minimum time jitter in seconds'),
    jitter_max: int | None = typer.Option(None, '--jitter-max', '-J', help='Maximum time jitter in seconds'),
    at: str | None = typer.Option(None, '--at', help='Datetime string for commit time'),
    args: Annotated[list[str] | None, typer.Argument(..., help='Extra arguments to pass to git commit command')] = None,
) -> None:
    """Record a commit on repository at the specified time node."""
    repo_dir = ctx.obj['repo_dir']
    settings: Settings = ctx.obj['settings']
    states: States = ctx.obj['states']

    base_time: datetime | None = None
    if at is not None:
        try:
            base_time = datetime.fromisoformat(at)
        except ValueError:
            ctx.fail(f'Error: Invalid datetime format for --at: {at}')

    repo = Repository(discover_repository(repo_dir))

    try:
        record_commit(
            repo,
            settings,
            states,
            args or [],
            base_time=base_time,
            jitter_min=jitter_min,
            jitter_max=jitter_max,
        )
    except GitError as exc:
        ctx.fail(str(exc))
