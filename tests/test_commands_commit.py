"""Tests for the commit command."""

from datetime import datetime

import pytest
from chance import chance
from pygit2 import Repository
from typer.testing import CliRunner

from git_timemachine.cli import app
from git_timemachine.config import Settings, States

from ._helpers import repo_add_new_file  # type: ignore[missing-import]


def test_commit_on_empty_repo(
    empty_repo: Repository, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Test commit on an empty repository."""
    assert_new_commit(empty_repo, runner, gtm_settings, gtm_states)


def test_commit_on_nonempty_repo(
    nonempty_repo: Repository, runner: CliRunner, gtm_settings: Settings, gtm_states: States
) -> None:
    """Test commit on a non-empty repository."""
    assert_new_commit(nonempty_repo, runner, gtm_settings, gtm_states)


@pytest.mark.usefixtures('gtm_settings', 'gtm_states')
def test_exception_nothing_to_commit(empty_repo: Repository, nonempty_repo: Repository, runner: CliRunner) -> None:
    """Test that committing with no changes raises an error."""
    for repo in [empty_repo, nonempty_repo]:
        result = runner.invoke(app, ['-C', repo.workdir, 'commit', '--', '--message', chance.sentence()])

        assert result.exception
        assert 'Nothing to commit or pending changes.' in result.output


@pytest.mark.usefixtures('gtm_settings')
def test_exception_commit_earlier(nonempty_repo: Repository, runner: CliRunner, gtm_states: States) -> None:
    """Test that committing with earlier time than HEAD raises an error."""
    gtm_states.last_commit_time = datetime(2000, 1, 1, 8, 0, 0)
    gtm_states.save()

    repo_add_new_file(nonempty_repo)
    result = runner.invoke(app, ['-C', nonempty_repo.workdir, 'commit', '--', '--message', chance.sentence()])

    assert result.exception
    assert 'Commit time is earlier than HEAD.' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_exception_daily_commit_limit(
    empty_repo: Repository, nonempty_repo: Repository, runner: CliRunner, gtm_settings: Settings
) -> None:
    """Test that exceeding daily commit limit raises an error."""
    gtm_settings.max_repo_daily_commits = 1
    gtm_settings.save()

    for repo in [empty_repo, nonempty_repo]:
        repo_add_new_file(repo)

        result = runner.invoke(app, ['-C', repo.workdir, 'commit', '--', '--message', chance.sentence()])
        assert not result.exception

        repo_add_new_file(repo)

        result = runner.invoke(app, ['-C', repo.workdir, 'commit', '--', '--message', chance.sentence()])
        assert result.exception
        assert 'Exceeded the daily repository commit limit: 1' in result.output


def assert_new_commit(repo: Repository, runner: CliRunner, gtm_settings: Settings, gtm_states: States) -> None:
    """Assert that a new commit is created with correct properties."""
    last_commit_time = gtm_states.last_commit_time

    if repo.head_is_unborn:
        commit_num = 0
        parent_id = None
    else:
        commits = list(repo.walk(repo.head.target))
        commit_num = len(commits)
        parent_id = str(commits[0].id)

    repo_add_new_file(repo)
    result = runner.invoke(app, ['-C', repo.workdir, 'commit', '--', '--message', chance.sentence()])

    if result.exception:
        raise result.exception

    commits = list(repo.walk(repo.head.target))
    assert len(commits) == commit_num + 1

    new_commit = commits[0]
    if commit_num == 0:
        assert len(new_commit.parents) == 0
    else:
        assert str(new_commit.parents[0].id) == parent_id

    assert new_commit.author.name == new_commit.committer.name == repo.config['user.name']
    assert new_commit.author.email == new_commit.committer.email == repo.config['user.email']

    commit_range = range(gtm_settings.jitter_min - 1, gtm_settings.jitter_max + 1)
    assert int(new_commit.author.time - last_commit_time.timestamp()) in commit_range


@pytest.mark.usefixtures('gtm_states')
def test_exception_total_daily_commit_limit(empty_repo: Repository, runner: CliRunner, gtm_settings: Settings) -> None:
    """Test that exceeding the total daily commit limit (across all repos) raises an error."""
    gtm_settings.max_total_daily_commits = 1
    gtm_settings.max_repo_daily_commits = 10
    gtm_settings.save()

    # First commit — should succeed
    repo_add_new_file(empty_repo)
    result = runner.invoke(app, ['-C', empty_repo.workdir, 'commit', '--', '--message', chance.sentence()])
    assert not result.exception

    # Second commit on the same day — should fail due to total daily limit
    repo_add_new_file(empty_repo)
    result = runner.invoke(app, ['-C', empty_repo.workdir, 'commit', '--', '--message', chance.sentence()])
    assert result.exception
    assert 'Exceeded the total daily commit limit: 1' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_exception_total_daily_commit_limit_cross_repo(
    empty_repo: Repository, nonempty_repo: Repository, runner: CliRunner, gtm_settings: Settings
) -> None:
    """Test that total daily limit is enforced across different repositories."""
    gtm_settings.max_total_daily_commits = 1
    gtm_settings.max_repo_daily_commits = 10
    gtm_settings.save()

    # Commit in the first repo — should succeed
    repo_add_new_file(empty_repo)
    result = runner.invoke(app, ['-C', empty_repo.workdir, 'commit', '--', '--message', chance.sentence()])
    assert not result.exception

    # Commit in a different repo on the same day — should be rejected
    repo_add_new_file(nonempty_repo)
    result = runner.invoke(app, ['-C', nonempty_repo.workdir, 'commit', '--', '--message', chance.sentence()])
    assert result.exception
    assert 'Exceeded the total daily commit limit: 1' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_total_daily_commit_count_resets_next_day(
    empty_repo: Repository, runner: CliRunner, gtm_settings: Settings
) -> None:
    """Test that the total daily commit count resets when the date changes."""
    gtm_settings.max_total_daily_commits = 2
    gtm_settings.save()

    # Day 1 — first commit succeeds
    repo_add_new_file(empty_repo)
    result = runner.invoke(
        app, ['-C', empty_repo.workdir, 'commit', '--at', '2030-06-15T10:00:00', '--', '--message', 'day1']
    )
    assert not result.exception

    # Day 2 — first commit on a new day should succeed (count resets)
    repo_add_new_file(empty_repo)
    result = runner.invoke(
        app, ['-C', empty_repo.workdir, 'commit', '--at', '2030-06-16T10:00:00', '--', '--message', 'day2a']
    )
    assert not result.exception

    # Day 2 — second commit should still succeed (limit is 2)
    repo_add_new_file(empty_repo)
    result = runner.invoke(
        app, ['-C', empty_repo.workdir, 'commit', '--at', '2030-06-16T11:00:00', '--', '--message', 'day2b']
    )
    assert not result.exception

    # Day 2 — third commit should fail (exceeds limit)
    repo_add_new_file(empty_repo)
    result = runner.invoke(
        app, ['-C', empty_repo.workdir, 'commit', '--at', '2030-06-16T12:00:00', '--', '--message', 'day2c']
    )
    assert result.exception
    assert 'Exceeded the total daily commit limit: 2' in result.output
