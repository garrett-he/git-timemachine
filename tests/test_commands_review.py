"""Tests for the review command."""

import pytest
from pygit2 import Repository
from typer.testing import CliRunner

from git_timemachine.cli import app


@pytest.mark.usefixtures('gtm_settings', 'gtm_states')
def test_command_review(runner: CliRunner, nonempty_repo: Repository) -> None:
    """Test review command displays commit history."""
    result = runner.invoke(app, ['-C', nonempty_repo.workdir, 'review'])

    assert 'date    | commits |\n+------------+---------+\n| 2022-07-23 |    3' in result.output
