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
    config = ctx.obj['config']
    states = ctx.obj['states']

    # Resolve jitter values: inline options take precedence over config
    effective_jitter_min = jitter_min if jitter_min is not None else config.jitter_min
    effective_jitter_max = jitter_max if jitter_max is not None else config.jitter_max

    # Handle --at option: parse datetime and use as base time
    if at is not None:
        try:
            commit_time = datetime.fromisoformat(at)
        except ValueError:
            ctx.fail(f'Error: Invalid datetime format for --at: {at}')
    else:
        commit_time = states.last_commit_time

    repo = Repository(discover_repository(repo_dir))

    try:
        check_repo_commit_time(repo, commit_time)
        check_repo_commit_status(repo)
        check_repo_max_daily_commits(repo, commit_time, config.max_repo_daily_commits)
    except GitError as exc:
        ctx.fail(str(exc))

    random.seed()

    commit_time += timedelta(seconds=random.randint(effective_jitter_min, effective_jitter_max))

    git_external_commit(repo, args or [], commit_time)

    states.last_commit_time = commit_time
    states.save()
