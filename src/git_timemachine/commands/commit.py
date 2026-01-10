"""Commit command for recording commits at calculated timestamps."""

import random
from datetime import datetime, timedelta
from typing import Annotated

import typer
from pygit2 import GitError, Repository, discover_repository

from git_timemachine.git import (
    check_repo_commit_status,
    check_repo_commit_time,
    check_repo_max_daily_commits,
    git_external_commit,
)


def commit_command(
    ctx: typer.Context,
    jitter_min: int | None = typer.Option(None, '--jitter-min', '-j', help='Minimum time jitter in seconds'),
    jitter_max: int | None = typer.Option(None, '--jitter-max', '-J', help='Maximum time jitter in seconds'),
    at: str | None = typer.Option(None, '--at', help='Datetime string for commit time'),
    args: Annotated[list[str] | None, typer.Argument(..., help='Extra arguments to pass to git commit command')] = None,
) -> None:
    """Record a commit on repository at the specified time node."""
    repo_dir = ctx.obj['repo_dir']
    settings = ctx.obj['settings']
    states = ctx.obj['states']

    # Resolve jitter values: inline options take precedence over settings
    effective_jitter_min = jitter_min if jitter_min is not None else settings.jitter_min
    effective_jitter_max = jitter_max if jitter_max is not None else settings.jitter_max

    # Handle --at option: parse datetime and use as base time
    if at is not None:
        try:
            commit_time = datetime.fromisoformat(at)
        except ValueError:
            ctx.fail(f'Error: Invalid datetime format for --at: {at}')
    else:
        commit_time = states.last_commit_time

    repo = Repository(discover_repository(repo_dir))

    # Validate commit prerequisites before mutating state
    is_same_day = commit_time.date() == states.current_commit_date
    new_daily_count = (states.daily_commit_count + 1) if is_same_day else 1

    try:
        check_repo_commit_time(repo, commit_time)
        check_repo_commit_status(repo)

        if new_daily_count > settings.max_total_daily_commits:
            raise GitError(f'Exceeded the total daily commit limit: {settings.max_total_daily_commits}.')

        check_repo_max_daily_commits(repo, commit_time, settings.max_repo_daily_commits)
    except GitError as exc:
        ctx.fail(str(exc))

    # All checks passed — update persisted state
    if is_same_day:
        states.daily_commit_count = new_daily_count
    else:
        states.current_commit_date = commit_time.date()
        states.daily_commit_count = 1

    random.seed()

    commit_time += timedelta(seconds=random.randint(effective_jitter_min, effective_jitter_max))

    git_external_commit(repo, args or [], commit_time)

    states.last_commit_time = commit_time
    states.save()
