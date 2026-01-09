"""Tests for git_timemachine CLI."""

from typer.testing import CliRunner

from git_timemachine.cli import app

runner = CliRunner()


def test_cli_prints_hello_world() -> None:
    """The CLI prints 'Hello, world!' by default."""
    result = runner.invoke(app)
    assert result.exit_code == 0
    assert 'Hello, world!' in result.output
