"""Tests for the retime command."""

import subprocess
from datetime import date, datetime
from pathlib import Path

import pytest
from pygit2 import Blob, Commit, Repository, Tree
from typer.testing import CliRunner

import git_timemachine.commands.retime as retime_module
from git_timemachine.cli import app
from git_timemachine.config import RetimeSession, Settings, States

from ._helpers import commit_files, init_repo, install_failing_hook, run_git  # type: ignore[missing-import]


def state_time() -> datetime:
    """Return a base timestamp later than the fixture commits."""
    return datetime(2031, 1, 1, 8, 0, 0)


def session_file(path: Path) -> Path:
    """Return the retime session path of a repository."""
    return Path(Repository(str(path)).path) / 'git-timemachine-session.yaml'


def build_history(path: Path, *, author: str | None = None) -> tuple[str, str, str]:
    """Create a three-commit history and return the commit SHAs."""
    init_repo(path)
    first = commit_files(path, {'a.txt': b'one'}, 'first', datetime(2030, 1, 1, 9, 0, 0), author=author)
    second = commit_files(path, {'b.bin': b'\x00\x01\x02\xff'}, 'second', datetime(2030, 1, 1, 10, 0, 0), author=author)
    third = commit_files(path, {'a.txt': b'three'}, 'third', datetime(2030, 1, 1, 11, 0, 0), author=author)

    return first, second, third


def test_retime_replays_commits(temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States) -> None:
    """Replay a range while preserving messages, authors, trees and binary content."""
    path = temp_dir / 'repo'
    first, second, _ = build_history(path, author='Original Author <original@example.com>')

    repo = Repository(str(path))
    original_head = str(repo.head.target)
    original_commits = {commit.message.strip(): commit for commit in repo.walk(repo.head.target)}

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 0, result.output

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))

    assert [commit.message.strip() for commit in commits] == ['third', 'second', 'first']
    assert str(commits[2].id) == first
    assert str(commits[0].tree_id) == str(original_commits['third'].tree_id)
    assert str(commits[1].tree_id) == str(original_commits['second'].tree_id)

    assert commits[1].author.name == 'Original Author'
    assert commits[1].author.email == 'original@example.com'
    assert commits[1].author.time != original_commits['second'].author.time
    assert commits[0].author.time > commits[1].author.time
    assert commits[1].author.time >= int(state_time().timestamp())

    tree = repo[commits[1].tree_id]
    assert isinstance(tree, Tree)
    blob = repo[tree['b.bin'].id]
    assert isinstance(blob, Blob)
    assert blob.read_raw() == b'\x00\x01\x02\xff'

    backup = repo.branches['main-gtm-backup']
    assert str(backup.target) == original_head
    assert run_git(path, 'status', '--porcelain') == ''
    assert 'Retimed 2 commit(s)' in result.output
    assert not session_file(path).exists()


@pytest.mark.parametrize('length', [6, 8, 40])
def test_retime_accepts_abbreviated_sha(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States, length: int
) -> None:
    """A 6-character, longer abbreviated, and full SHA all resolve."""
    path = temp_dir / 'repo'
    init_repo(path)
    commit_files(path, {'a.txt': b'one'}, 'first', datetime(2030, 1, 1, 9, 0, 0))
    second = commit_files(path, {'b.txt': b'two'}, 'second', datetime(2030, 1, 1, 10, 0, 0))

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:length]])

    assert result.exit_code == 0, result.output

    repo = Repository(str(path))
    assert len(list(repo.walk(repo.head.target))) == 2


@pytest.mark.parametrize(
    ('commit_id', 'message'),
    [
        ('abc12', 'at least 6 characters'),
        ('zzzzzz', 'at least 6 characters'),
        ('0' * 40, 'Commit not found'),
    ],
)
def test_retime_rejects_invalid_commit_id(
    temp_dir: Path,
    runner: CliRunner,
    gtm_settings: Settings,
    gtm_states: States,
    commit_id: str,
    message: str,
) -> None:
    """Invalid or unknown commit identifiers are rejected before rewriting."""
    path = temp_dir / 'repo'
    build_history(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', commit_id])

    assert result.exit_code == 1
    assert message in result.output
    assert 'main-gtm-backup' not in Repository(str(path)).branches


def test_retime_rejects_non_commit_object(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A tree SHA is not accepted as the starting commit."""
    path = temp_dir / 'repo'
    build_history(path)

    repo = Repository(str(path))
    head = repo[repo.head.target]
    assert isinstance(head, Commit)
    tree_oid = str(head.tree_id)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', tree_oid])

    assert result.exit_code == 1
    assert 'Not a commit' in result.output


def test_retime_rejects_non_ancestor(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """The start commit must be reachable from HEAD."""
    path = temp_dir / 'repo'
    init_repo(path)
    commit_files(path, {'a.txt': b'one'}, 'first', datetime(2030, 1, 1, 9, 0, 0))

    run_git(path, 'checkout', '-q', '-b', 'other')
    other = commit_files(path, {'other.txt': b'other'}, 'other', datetime(2030, 1, 2, 9, 0, 0))
    run_git(path, 'checkout', '-q', 'main')
    commit_files(path, {'main.txt': b'main'}, 'main', datetime(2030, 1, 3, 9, 0, 0))

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', other[:6]])

    assert result.exit_code == 1
    assert 'is not an ancestor of HEAD' in result.output
    assert 'main-gtm-backup' not in Repository(str(path)).branches


def test_retime_rejects_merge_commit(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A merge commit in the range aborts before any history rewrite."""
    path = temp_dir / 'repo'
    init_repo(path)
    root = commit_files(path, {'a.txt': b'one'}, 'root', datetime(2030, 1, 1, 9, 0, 0))

    run_git(path, 'checkout', '-q', '-b', 'feature')
    commit_files(path, {'feature.txt': b'feature'}, 'feature', datetime(2030, 1, 2, 9, 0, 0))
    run_git(path, 'checkout', '-q', 'main')
    commit_files(path, {'main.txt': b'main'}, 'main', datetime(2030, 1, 3, 9, 0, 0))

    merge_date = datetime(2030, 1, 4, 9, 0, 0).astimezone().isoformat()
    run_git(
        path,
        'merge',
        '--no-ff',
        '-m',
        'merge',
        'feature',
        env={'GIT_AUTHOR_DATE': merge_date, 'GIT_COMMITTER_DATE': merge_date},
    )
    original_head = run_git(path, 'rev-parse', 'HEAD').strip()

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', root[:6]])

    assert result.exit_code == 1
    assert 'Merge commit is not supported' in result.output
    assert run_git(path, 'rev-parse', 'HEAD').strip() == original_head
    assert 'main-gtm-backup' not in Repository(str(path)).branches


def test_retime_rejects_dirty_worktree(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Uncommitted changes block the replay."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    (path / 'a.txt').write_bytes(b'dirty')

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 1
    assert 'Working tree is not clean' in result.output
    assert 'main-gtm-backup' not in Repository(str(path)).branches


def test_retime_rejects_detached_head(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A detached HEAD is rejected."""
    path = temp_dir / 'repo'
    build_history(path)
    run_git(path, 'checkout', '-q', '--detach')

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', 'abcdef'])

    assert result.exit_code == 1
    assert 'detached HEAD' in result.output


def test_retime_rejects_empty_repository(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A repository without commits cannot be retimed."""
    path = temp_dir / 'repo'
    init_repo(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', 'abcdef'])

    assert result.exit_code == 1
    assert 'no commits to retime' in result.output


def test_retime_rejects_existing_backup_branch(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """An existing backup branch is never overwritten."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    run_git(path, 'branch', 'main-gtm-backup')

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 1
    assert 'already exists' in result.output


def test_retime_rejects_early_start_time(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """The base timestamp must not be earlier than the parent of the start commit."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)

    gtm_states.last_commit_time = datetime(2020, 1, 1, 8, 0, 0)
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 1
    assert 'earlier than the parent of the start commit' in result.output
    assert 'main-gtm-backup' not in Repository(str(path)).branches


def test_retime_replays_empty_commit(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Empty commits in the range are replayed with --allow-empty."""
    path = temp_dir / 'repo'
    init_repo(path)
    root = commit_files(path, {'a.txt': b'one'}, 'root', datetime(2030, 1, 1, 9, 0, 0))
    empty = commit_files(path, {}, 'empty', datetime(2030, 1, 1, 10, 0, 0), allow_empty=True)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', empty[:6]])

    assert result.exit_code == 0, result.output

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))
    root_commit = repo[root]
    assert isinstance(root_commit, Commit)
    assert len(commits) == 2
    assert commits[0].message.strip() == 'empty'
    assert str(commits[0].tree_id) == str(root_commit.tree_id)


def test_retime_replays_root_commit(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A range starting at the root commit is replayed into a new root commit."""
    path = temp_dir / 'repo'
    root, _, _ = build_history(path)

    repo = Repository(str(path))
    original_head = str(repo.head.target)
    original_trees = {commit.message.strip(): str(commit.tree_id) for commit in repo.walk(repo.head.target)}

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', root[:6]])

    assert result.exit_code == 0, result.output

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))

    assert len(commits) == 3
    assert len(commits[-1].parents) == 0
    assert {commit.message.strip() for commit in commits} == {'first', 'second', 'third'}
    assert {commit.message.strip(): str(commit.tree_id) for commit in commits} == original_trees
    assert repo.head.shorthand == 'main'
    assert str(repo.branches['main-gtm-backup'].target) == original_head
    assert run_git(path, 'status', '--porcelain') == ''
    assert not session_file(path).exists()


def test_retime_declines_shift_and_keeps_partial(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Declining a shift keeps completed commits and leaves a clean worktree."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)

    repo = Repository(str(path))
    original_head = str(repo.head.target)

    gtm_settings.max_repo_daily_commits = 1
    gtm_settings.jitter_min = 1
    gtm_settings.jitter_max = 1
    gtm_settings.save()

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]], input='n\n')

    assert result.exit_code == 1
    assert 'Retimed 1/2 commit(s); remaining: 1' in result.output

    repo = Repository(str(path))
    assert len(list(repo.walk(repo.head.target))) == 2
    assert str(repo.branches['main-gtm-backup'].target) == original_head
    assert run_git(path, 'status', '--porcelain') == ''
    assert session_file(path).exists()

    states = States.load(gtm_states._path)
    assert states.last_commit_time == datetime(2031, 1, 1, 8, 0, 1)


def test_retime_shifts_and_continues(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Accepting a shift moves the replay to the next day and succeeds."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)

    gtm_settings.max_repo_daily_commits = 1
    gtm_settings.jitter_min = 1
    gtm_settings.jitter_max = 1
    gtm_settings.save()

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]], input='y\n')

    assert result.exit_code == 0, result.output
    assert 'Shifted last commit time' in result.output

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))
    assert len(commits) == 3
    assert {date.fromtimestamp(commit.author.time) for commit in commits[:2]} == {
        date(2031, 1, 1),
        date(2031, 1, 2),
    }

    states = States.load(gtm_states._path)
    assert states.last_commit_time == datetime(2031, 1, 2, 8, 0, 2)


def test_retime_hook_failure_restores_worktree(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A failing hook aborts, keeps the parent commit, and cleans the worktree."""
    path = temp_dir / 'repo'
    first, second, _ = build_history(path)
    install_failing_hook(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 1
    assert 'Retimed 0/2 commit(s); remaining: 2' in result.output

    repo = Repository(str(path))
    assert str(repo.head.target) == first
    assert 'main-gtm-backup' in repo.branches
    assert run_git(path, 'status', '--porcelain') == ''
    assert session_file(path).exists()


def test_retime_root_hook_failure_clears_unborn_worktree(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A root replay failure leaves HEAD unborn and the worktree empty."""
    path = temp_dir / 'repo'
    init_repo(path)
    root = commit_files(path, {'a.txt': b'one'}, 'root', datetime(2030, 1, 1, 9, 0, 0))
    install_failing_hook(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', root[:6]])

    assert result.exit_code == 1
    assert 'Current HEAD: <unborn>' in result.output

    head_check = subprocess.run(
        ['git', '-C', str(path), 'rev-parse', '--verify', 'HEAD'],
        check=False,
        capture_output=True,
        text=True,
    )
    assert head_check.returncode != 0
    assert run_git(path, 'status', '--porcelain') == ''
    assert 'main-gtm-backup' in Repository(str(path)).branches
    assert session_file(path).exists()

    (path / '.git' / 'hooks' / 'pre-commit').unlink()
    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert not session_file(path).exists()

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))
    assert len(commits) == 1
    assert commits[0].message.strip() == 'root'
    assert repo.head.shorthand == 'main'
    assert run_git(path, 'status', '--porcelain') == ''


def decline_session(
    path: Path,
    runner: CliRunner,
    gtm_settings: Settings,
    gtm_states: States,
    start: str,
) -> None:
    """Create an interrupted session by declining the daily-limit shift."""
    gtm_settings.max_repo_daily_commits = 1
    gtm_settings.jitter_min = 1
    gtm_settings.jitter_max = 1
    gtm_settings.save()

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', start[:6]], input='n\n')
    assert result.exit_code == 1
    assert session_file(path).exists()


def test_retime_continue_after_declined_shift(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A declined shift can be resumed with --continue."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    path_to_session = session_file(path)
    session = RetimeSession.load(path_to_session)
    assert session.next_index == 1
    assert session.reset_done is True

    gtm_settings.max_repo_daily_commits = 5
    gtm_settings.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert 'Resuming retime session at 1/2 commit(s).' in result.output
    assert 'Retimed 2 commit(s)' in result.output
    assert not path_to_session.exists()

    repo = Repository(str(path))
    commits = list(repo.walk(repo.head.target))
    assert [commit.message.strip() for commit in commits] == ['third', 'second', 'first']


def test_retime_rejects_new_run_with_active_session(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A new retime is refused while an interrupted session exists."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 1
    assert 'interrupted retime session exists' in result.output
    assert session_file(path).exists()


def test_retime_continue_requires_session(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """--continue without a session reports a clear error."""
    path = temp_dir / 'repo'
    build_history(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 1
    assert 'No interrupted retime session found' in result.output


def test_retime_requires_commit_id(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """COMMIT_ID is required unless --continue is used."""
    path = temp_dir / 'repo'
    build_history(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime'])

    assert result.exit_code == 1
    assert 'COMMIT_ID is required unless --continue is used' in result.output


def test_retime_continue_rejects_commit_id(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """--continue cannot be combined with a COMMIT_ID."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6], '--continue'])

    assert result.exit_code == 1
    assert 'COMMIT_ID cannot be used with --continue' in result.output


def test_retime_continue_after_hook_failure(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A hook failure can be resumed after the hook is fixed."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    install_failing_hook(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])
    assert result.exit_code == 1

    (path / '.git' / 'hooks' / 'pre-commit').unlink()
    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert not session_file(path).exists()

    repo = Repository(str(path))
    assert len(list(repo.walk(repo.head.target))) == 3


def test_retime_continue_rejects_moved_head(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """The session cannot resume when HEAD moved since the interruption."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    commit_files(path, {}, 'extra', datetime(2031, 1, 3, 9, 0, 0), allow_empty=True)

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 1
    assert 'the session expects' in result.output
    assert session_file(path).exists()


def test_retime_continue_rejects_branch_mismatch(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """The session cannot resume on a different branch."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    run_git(path, 'checkout', '-q', '-b', 'other')

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 1
    assert 'belongs to branch' in result.output


def test_retime_continue_rejects_corrupt_session(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """An unreadable session file is reported instead of crashing."""
    path = temp_dir / 'repo'
    build_history(path)
    session_file(path).write_text('not: [valid', encoding='utf-8')

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 1
    assert 'Invalid retime session' in result.output


def test_retime_continue_clears_completed_session(
    temp_dir: Path, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """A stale session whose commits are all done is removed cleanly."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)
    decline_session(path, runner, gtm_settings, gtm_states, second)

    path_to_session = session_file(path)
    session = RetimeSession.load(path_to_session)
    session.next_index = len(session.commits)
    session.save(path_to_session)

    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert 'already completed' in result.output
    assert not path_to_session.exists()


def test_retime_ctrl_c_keeps_session(
    temp_dir: Path,
    runner: CliRunner,
    gtm_settings: Settings,
    gtm_states: States,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl-C exits with 130 and leaves a resumable session."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(retime_module, 'record_commit', interrupt)

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 130
    assert 'Interrupted.' in result.output
    assert 'Resume with: git-timemachine retime --continue' in result.output

    path_to_session = session_file(path)
    assert path_to_session.exists()
    session = RetimeSession.load(path_to_session)
    assert session.next_index == 0
    assert session.reset_done is True
    assert run_git(path, 'status', '--porcelain') == ''

    monkeypatch.undo()
    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert not path_to_session.exists()


def test_retime_continue_after_interrupted_reset(
    temp_dir: Path,
    runner: CliRunner,
    gtm_settings: Settings,
    gtm_states: States,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An interruption before the reset step is replayed from the reset again."""
    path = temp_dir / 'repo'
    _, second, _ = build_history(path)

    repo = Repository(str(path))
    original_head = str(repo.head.target)

    gtm_states.last_commit_time = state_time()
    gtm_states.save()

    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(retime_module, 'reset_branch_to', interrupt)

    result = runner.invoke(app, ['-C', str(path), 'retime', second[:6]])

    assert result.exit_code == 130
    path_to_session = session_file(path)
    assert path_to_session.exists()
    session = RetimeSession.load(path_to_session)
    assert session.reset_done is False
    assert session.next_index == 0
    assert str(Repository(str(path)).head.target) == original_head
    assert run_git(path, 'status', '--porcelain') == ''

    monkeypatch.undo()
    result = runner.invoke(app, ['-C', str(path), 'retime', '--continue'])

    assert result.exit_code == 0, result.output
    assert not path_to_session.exists()

    repo = Repository(str(path))
    assert len(list(repo.walk(repo.head.target))) == 3
