"""Git operations and validation helpers."""

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

from pygit2 import GIT_STATUS_WT_NEW, Commit, GitError, Repository
from pygit2.enums import ReferenceType


class DailyCommitLimitError(GitError):
    """Raised when a configured daily commit limit is exceeded."""


@dataclass(frozen=True, slots=True)
class ReplayCommit:
    """Immutable snapshot of a commit scheduled for replay."""

    oid: str
    is_empty: bool


def check_repo_commit_status(repo: Repository) -> None:
    """Check that the repository has staged changes to commit."""
    repo_status = repo.status(untracked_files='no')
    if repo_status == {} or len([value for value in repo_status.values() if value < GIT_STATUS_WT_NEW]) < 1:
        raise GitError('Nothing to commit or pending changes.')


def check_repo_commit_time(repo: Repository, commit_time: datetime) -> None:
    """Check that commit time is not earlier than HEAD."""
    if not repo.head_is_unborn and commit_time.timestamp() < next(repo.walk(repo.head.target)).commit_time:
        raise GitError('Commit time is earlier than HEAD.')


def check_repo_max_daily_commits(repo: Repository, commit_time: datetime, max_num: int) -> None:
    """Check that the daily commit limit has not been exceeded."""
    if repo.head_is_unborn or max_num == 0:
        return

    date_str = commit_time.strftime('%Y-%m-%d')

    commits = [
        commit
        for commit in repo.walk(repo.head.target)
        if datetime.fromtimestamp(commit.commit_time).strftime('%Y-%m-%d') == date_str
    ]

    if len(commits) >= max_num:
        raise DailyCommitLimitError(f'Exceeded the daily repository commit limit: {max_num}.')


def git_external_commit(repo: Repository, args: list[str], commit_time: datetime) -> None:
    """Execute git commit with custom author/committer timestamps."""
    env = commit_time.replace(microsecond=0).astimezone().isoformat()
    subprocess.run(
        ['git', '-C', repo.workdir, 'commit', *list(args)],
        cwd=repo.workdir,
        env={**os.environ, 'GIT_AUTHOR_DATE': env, 'GIT_COMMITTER_DATE': env},
        check=True,
    )


def require_workdir(repo: Repository) -> str:
    """Return the repository work directory, rejecting bare repositories."""
    if repo.workdir is None:
        raise GitError('Bare repositories are not supported.')

    return repo.workdir


def run_git(workdir: str, *args: str) -> str:
    """Run a git command in the given work directory and return its output."""
    try:
        result = subprocess.run(
            ['git', '-C', workdir, *args],
            cwd=workdir,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or '').strip()
        raise GitError(f'git {" ".join(args)} failed: {detail}') from exc

    return result.stdout


def run_git_optional(workdir: str, *args: str) -> str | None:
    """Run a git command and return its output, or None when it fails."""
    result = subprocess.run(
        ['git', '-C', workdir, *args],
        cwd=workdir,
        check=False,
        capture_output=True,
        text=True,
    )

    return result.stdout if result.returncode == 0 else None


def check_clean_worktree(repo: Repository) -> None:
    """Check that the working tree has no tracked or untracked changes."""
    if run_git(require_workdir(repo), 'status', '--porcelain').strip():
        raise GitError('Working tree is not clean. Commit or stash your changes first.')


def head_oid(repo: Repository) -> str | None:
    """Return the current HEAD oid, or None when HEAD is unborn."""
    if repo.head_is_unborn:
        return None

    return str(repo.head.target)


def current_branch_name(repo: Repository, *, allow_unborn: bool = False) -> str:
    """Return the name of the checked out branch."""
    if repo.head_is_unborn:
        if allow_unborn:
            head = repo.lookup_reference('HEAD')
            target = str(head.target)
            if head.type == ReferenceType.SYMBOLIC and target.startswith('refs/heads/'):
                return target.removeprefix('refs/heads/')

        raise GitError('Repository has no commits to retime.')

    if repo.head_is_detached:
        raise GitError('Cannot retime from a detached HEAD. Check out a branch first.')

    return repo.head.shorthand


def create_backup_branch(repo: Repository, name: str) -> None:
    """Create a backup branch pointing at the current HEAD."""
    if name in repo.branches:
        raise GitError(f'Backup branch {name} already exists; delete it with `git branch -D {name}` and retry.')

    if repo.head_is_unborn:
        raise GitError('Repository has no commits to retime.')

    head = repo[repo.head.target]
    if not isinstance(head, Commit):
        raise GitError('HEAD does not point to a commit.')

    repo.branches.create(name, head)


def resolve_commit_id(repo: Repository, value: str) -> Commit:
    """Resolve a full or abbreviated (at least 6 characters) commit SHA."""
    spec = value.strip().lower()
    if re.fullmatch(r'[0-9a-f]{6,40}', spec) is None:
        raise GitError('commit_id must be a full SHA or an abbreviated SHA of at least 6 characters.')

    try:
        obj = repo.revparse_single(spec)
    except (KeyError, ValueError) as exc:
        raise GitError(f'Commit not found: {value.strip()}') from exc

    if not isinstance(obj, Commit):
        raise GitError(f'Not a commit: {value.strip()}')

    return obj


def snapshot_replay_range(repo: Repository, start: Commit) -> list[ReplayCommit]:
    """Snapshot the linear commit range from start (inclusive) to HEAD."""
    if repo.head_is_unborn:
        raise GitError('Repository has no commits to retime.')

    head = repo[repo.head.target]
    if not isinstance(head, Commit):
        raise GitError('HEAD does not point to a commit.')

    commits: list[Commit] = []
    current = head

    while True:
        if len(current.parents) > 1:
            raise GitError(f'Merge commit is not supported: {str(current.id)[:7]}')

        commits.append(current)

        if current.id == start.id:
            break

        if not current.parents:
            raise GitError(f'Commit {str(start.id)[:7]} is not an ancestor of HEAD.')

        current = current.parents[0]

    commits.reverse()

    return [
        ReplayCommit(
            oid=str(commit.id),
            is_empty=bool(commit.parents) and commit.tree_id == commit.parents[0].tree_id,
        )
        for commit in commits
    ]


def sync_worktree_to_commit(repo: Repository, oid: str) -> None:
    """Synchronize the index and working tree with the given commit."""
    run_git(require_workdir(repo), 'read-tree', '-u', '--reset', oid)


def reset_branch_to(repo: Repository, oid: str) -> None:
    """Reset the current branch and working tree to the given commit."""
    run_git(require_workdir(repo), 'reset', '--hard', oid)


def reset_root_branch(repo: Repository, branch: str, oid: str) -> None:
    """Remove the branch and prepare an empty worktree for a new root commit."""
    workdir = require_workdir(repo)
    ref = f'refs/heads/{branch}'
    if run_git_optional(workdir, 'rev-parse', '--verify', ref) is not None:
        run_git(workdir, 'update-ref', '-d', ref)
    run_git(workdir, 'read-tree', '--empty')
    run_git(workdir, 'clean', '-fd')
    run_git(workdir, 'read-tree', '-u', '--reset', oid)


def restore_worktree(repo: Repository) -> None:
    """Reset index and working tree to HEAD, or clear them when HEAD is unborn."""
    workdir = require_workdir(repo)

    if run_git_optional(workdir, 'rev-parse', '--verify', 'HEAD') is None:
        run_git(workdir, 'read-tree', '--empty')
        run_git(workdir, 'clean', '-fd')
    else:
        run_git(workdir, 'reset', '--hard', 'HEAD')
