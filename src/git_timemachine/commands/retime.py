"""Retime command for replaying commits at new timestamps."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Never

import typer
import yaml
from pydantic import ValidationError
from pygit2 import Commit, GitError, Repository, discover_repository

from git_timemachine.commands.commit import record_commit
from git_timemachine.commands.shift import shift_last_commit_time
from git_timemachine.config import RetimeCommit, RetimeSession
from git_timemachine.git import (
    DailyCommitLimitError,
    ReplayCommit,
    check_clean_worktree,
    create_backup_branch,
    current_branch_name,
    head_oid,
    reset_branch_to,
    reset_root_branch,
    resolve_commit_id,
    restore_worktree,
    snapshot_replay_range,
    sync_worktree_to_commit,
)

if TYPE_CHECKING:
    from datetime import datetime

    from git_timemachine.config import Settings, States

SESSION_FILENAME = 'git-timemachine-session.yaml'


@dataclass(frozen=True, slots=True)
class _ReplayPlan:
    """Prepared replay plan created before rewriting any history."""

    branch: str
    commits: list[ReplayCommit]
    backup_branch: str
    parent_oid: str | None
    original_head: str


def session_path(repo: Repository) -> Path:
    """Return the session file path inside the repository git directory."""
    return Path(repo.path) / SESSION_FILENAME


def _prepare_new(repo: Repository, states: States, commit_id: str) -> _ReplayPlan:
    """Validate the environment and snapshot the commits to replay.

    Args:
        repo: Repository to retime.
        states: Persisted state holding the base commit time.
        commit_id: Full or abbreviated start commit SHA.

    Returns:
        The immutable replay plan.

    Raises:
        GitError: When validation fails or the range cannot be replayed.
    """
    path = session_path(repo)
    if path.exists():
        raise GitError(
            f'An interrupted retime session exists at {path}; '
            'run `git-timemachine retime --continue` or delete the file to start over.'
        )

    branch = current_branch_name(repo)
    check_clean_worktree(repo)

    start = resolve_commit_id(repo, commit_id)
    commits = snapshot_replay_range(repo, start)

    if start.parents and states.last_commit_time.timestamp() < start.parents[0].commit_time:
        raise GitError(
            'Commit time is earlier than the parent of the start commit; '
            'shift `last_commit_time` forward with `git-timemachine shift` first.'
        )

    original_head = head_oid(repo)
    if original_head is None:
        raise GitError('Repository has no commits to retime.')

    backup_branch = f'{branch}-gtm-backup'
    create_backup_branch(repo, backup_branch)

    return _ReplayPlan(
        branch=branch,
        commits=commits,
        backup_branch=backup_branch,
        parent_oid=str(start.parents[0].id) if start.parents else None,
        original_head=original_head,
    )


def _new_session(plan: _ReplayPlan) -> RetimeSession:
    """Build the persisted session for a new replay."""
    return RetimeSession(
        original_head=plan.original_head,
        branch=plan.branch,
        backup_branch=plan.backup_branch,
        parent_oid=plan.parent_oid,
        commits=[RetimeCommit(oid=item.oid, is_empty=item.is_empty) for item in plan.commits],
        next_index=0,
        last_new_head=plan.parent_oid,
        reset_done=False,
    )


def _load_session(repo: Repository) -> tuple[RetimeSession, Path]:
    """Load the interrupted session of the given repository."""
    path = session_path(repo)
    if not path.exists():
        raise GitError(
            f'No interrupted retime session found at {path}; start one with `git-timemachine retime <commit_id>`.'
        )

    try:
        session = RetimeSession.load(path)
    except (OSError, yaml.YAMLError, ValidationError) as exc:
        raise GitError(f'Invalid retime session at {path}: {exc}') from exc

    return session, path


def _save_session(path: Path, session: RetimeSession) -> None:
    """Persist the session atomically."""
    try:
        session.save_atomic(path)
    except OSError as exc:
        raise GitError(f'Failed to write retime session at {path}: {exc}') from exc


def _validate_session(repo: Repository, session: RetimeSession, path: Path) -> None:
    """Validate that the repository still matches the persisted session."""
    branch = current_branch_name(repo, allow_unborn=True)
    if branch != session.branch:
        raise GitError(
            f'Retime session belongs to branch {session.branch}, but {branch} is checked out; '
            f'switch back or delete {path} to start over.'
        )

    if session.backup_branch not in repo.branches:
        raise GitError(f'Backup branch {session.backup_branch} is missing; delete {path} to start over.')

    if str(repo.branches[session.backup_branch].target) != session.original_head:
        raise GitError(
            f'Backup branch {session.backup_branch} does not point to the original HEAD '
            f'{session.original_head}; delete {path} to start over.'
        )

    total = len(session.commits)
    if session.next_index > total:
        raise GitError(f'Session progress is invalid ({session.next_index}/{total}); delete {path} to start over.')

    if not session.reset_done and session.next_index != 0:
        raise GitError(
            f'Session state is inconsistent (reset pending but {session.next_index} commit(s) recorded); '
            f'delete {path} to start over.'
        )

    if session.reset_done:
        current = head_oid(repo)
        if current != session.last_new_head:
            raise GitError(
                f'HEAD is {current or "<unborn>"}, but the session expects '
                f'{session.last_new_head or "<unborn>"}; reset HEAD to the session value '
                f'or delete {path} to start over.'
            )

        check_clean_worktree(repo)

    for item in session.commits[session.next_index :]:
        try:
            obj = repo[item.oid]
        except (KeyError, ValueError) as exc:
            raise GitError(f'Commit {item.oid[:7]} from the session is missing; delete {path} to start over.') from exc

        if not isinstance(obj, Commit):
            raise GitError(f'Object {item.oid[:7]} from the session is not a commit; delete {path} to start over.')


def _confirm_shift(error: DailyCommitLimitError) -> bool:
    """Ask the user whether to shift the base timestamp by one day."""
    typer.echo(str(error), err=True)

    try:
        return typer.confirm(
            'Daily commit limit reached. Shift last commit time by one day and continue?',
            default=True,
        )
    except (typer.Abort, EOFError):
        return False


def _fail(error: BaseException) -> Never:
    """Print an error and exit with a failure code, keeping the session intact."""
    typer.echo(str(error), err=True)
    raise typer.Exit(1)


def _abort(
    repo_dir: str,
    error: BaseException,
    session: RetimeSession,
    session_path: Path,
    exit_code: int,
) -> Never:
    """Restore the working tree, report progress, and exit with the given code."""
    if isinstance(error, KeyboardInterrupt):
        typer.echo('Interrupted.', err=True)
    else:
        typer.echo(f'Error: {error}', err=True)

    current: str | None = None
    try:
        repo = Repository(discover_repository(repo_dir))
        current = head_oid(repo)
        restore_worktree(repo)
    except (GitError, subprocess.CalledProcessError) as cleanup_error:
        typer.echo(f'Warning: failed to restore the working tree: {cleanup_error}', err=True)

    total = len(session.commits)
    typer.echo(f'Retimed {session.next_index}/{total} commit(s); remaining: {total - session.next_index}.', err=True)
    typer.echo(f'Current HEAD: {current or "<unborn>"}', err=True)
    typer.echo(f'Backup branch: {session.backup_branch}', err=True)
    typer.echo('Resume with: git-timemachine retime --continue', err=True)
    typer.echo(f'Discard session: rm {session_path}', err=True)

    raise typer.Exit(exit_code)


def _replay(
    repo_dir: str,
    settings: Settings,
    states: States,
    commits: list[RetimeCommit],
    session: RetimeSession,
    session_path: Path,
    *,
    jitter_min: int | None,
    jitter_max: int | None,
) -> None:
    """Replay the given commits and persist progress after each success."""
    total = len(session.commits)

    try:
        repo = Repository(discover_repository(repo_dir))

        for item in commits:
            sync_worktree_to_commit(repo, item.oid)
            repo = Repository(discover_repository(repo_dir))

            new_time: datetime | None = None
            while new_time is None:
                try:
                    new_time = record_commit(
                        repo,
                        settings,
                        states,
                        [],
                        jitter_min=jitter_min,
                        jitter_max=jitter_max,
                        allow_empty=item.is_empty,
                        reuse_from=item.oid,
                    )
                except DailyCommitLimitError as exc:
                    if not _confirm_shift(exc):
                        raise GitError('Aborted: daily commit limit reached and shift was declined.') from exc

                    shifted = shift_last_commit_time(states, days=1)
                    typer.echo(f'Shifted last commit time to {shifted.isoformat()}')

            session.next_index += 1
            repo = Repository(discover_repository(repo_dir))
            session.last_new_head = head_oid(repo)
            _save_session(session_path, session)

            new_head = (session.last_new_head or '')[:7]
            typer.echo(f'[{session.next_index}/{total}] {item.oid[:7]} -> {new_head} at {new_time.isoformat()}')
    except KeyboardInterrupt as exc:
        _abort(repo_dir, exc, session, session_path, 130)
    except (GitError, subprocess.CalledProcessError) as exc:
        _abort(repo_dir, exc, session, session_path, 1)


def retime_command(
    ctx: typer.Context,
    commit_id: Annotated[
        str | None,
        typer.Argument(help='Starting commit (full SHA or abbreviated SHA of at least 6 characters)'),
    ] = None,
    jitter_min: int | None = typer.Option(None, '--jitter-min', '-j', help='Minimum time jitter in seconds'),
    jitter_max: int | None = typer.Option(None, '--jitter-max', '-J', help='Maximum time jitter in seconds'),
    continue_session: bool = typer.Option(False, '--continue', help='Resume the last interrupted retime session'),
) -> None:
    """Re-record commits from the given commit to HEAD at new timestamps.

    Examples:
        git-timemachine retime a1b2c3
        git-timemachine retime a1b2c3d4e5f6 --jitter-min 60 --jitter-max 600
        git-timemachine retime --continue
    """
    repo_dir = ctx.obj['repo_dir']
    settings: Settings = ctx.obj['settings']
    states: States = ctx.obj['states']

    try:
        repo = Repository(discover_repository(repo_dir))
    except GitError as exc:
        _fail(exc)

    path = session_path(repo)

    if continue_session:
        if commit_id is not None:
            _fail(GitError('COMMIT_ID cannot be used with --continue.'))

        try:
            session, path = _load_session(repo)
            _validate_session(repo, session, path)
        except GitError as exc:
            _fail(exc)

        if session.next_index == len(session.commits):
            path.unlink(missing_ok=True)
            typer.echo('Retime session already completed; removed the session file.')
            return

        typer.echo(f'Resuming retime session at {session.next_index}/{len(session.commits)} commit(s).')
        if not session.reset_done:
            typer.echo('Resuming before the reset step; residual changes will be discarded.')
    else:
        if commit_id is None:
            _fail(GitError('COMMIT_ID is required unless --continue is used.'))

        try:
            plan = _prepare_new(repo, states, commit_id)
        except GitError as exc:
            _fail(exc)

        session = _new_session(plan)
        path = session_path(repo)
        try:
            _save_session(path, session)
        except GitError as exc:
            _fail(exc)

        typer.echo(f'Backup branch: {session.backup_branch}')

    if not session.reset_done:
        try:
            if session.parent_oid is None:
                reset_root_branch(repo, session.branch, session.commits[0].oid)
            else:
                reset_branch_to(repo, session.parent_oid)

            session.reset_done = True
            session.last_new_head = head_oid(repo)
            _save_session(path, session)
        except KeyboardInterrupt as exc:
            _abort(str(repo_dir), exc, session, path, 130)
        except (GitError, subprocess.CalledProcessError) as exc:
            _abort(str(repo_dir), exc, session, path, 1)

    _replay(
        str(repo_dir),
        settings,
        states,
        session.commits[session.next_index :],
        session,
        path,
        jitter_min=jitter_min,
        jitter_max=jitter_max,
    )

    path.unlink(missing_ok=True)
    typer.echo(f'Retimed {session.next_index} commit(s). New HEAD: {session.last_new_head}')
    typer.echo(f'Backup branch: {session.backup_branch}')
