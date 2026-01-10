"""Tests for states command."""

import pytest
from typer.testing import CliRunner

from git_timemachine.cli import app
from git_timemachine.config import States


@pytest.mark.usefixtures('gtm_states')
def test_states_list_all(runner: CliRunner, gtm_states: States) -> None:
    """Test listing all state values."""
    result = runner.invoke(app, ['states'])
    assert not result.exception
    assert 'last_commit_time=' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_states_get_single_value(runner: CliRunner, gtm_states: States) -> None:
    """Test getting a single state value."""
    result = runner.invoke(app, ['states', 'last_commit_time'])
    assert not result.exception
    assert '2023' in result.output  # Year from fixture


@pytest.mark.usefixtures('gtm_states')
def test_states_set_value(runner: CliRunner, gtm_states: States) -> None:
    """Test setting a state value."""
    path = gtm_states._path

    result = runner.invoke(app, ['states', 'last_commit_time', '2024-06-15T14:30:00'])
    assert not result.exception
    assert 'last_commit_time=2024-06-15 14:30:00' in result.output

    # Verify the value was persisted
    states = States.load(path)
    assert states.last_commit_time.year == 2024
    assert states.last_commit_time.month == 6
    assert states.last_commit_time.day == 15
    assert states.last_commit_time.hour == 14
    assert states.last_commit_time.minute == 30


@pytest.mark.usefixtures('gtm_states')
def test_states_unknown_key(runner: CliRunner, gtm_states: States) -> None:
    """Test getting an unknown state key."""
    result = runner.invoke(app, ['states', 'unknown_key'])
    assert result.exit_code == 1
    assert 'Unknown state key' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_states_set_invalid_datetime(runner: CliRunner, gtm_states: States) -> None:
    """Test setting an invalid datetime value."""
    result = runner.invoke(app, ['states', 'last_commit_time', 'invalid-date'])
    assert result.exit_code == 1
    assert 'Invalid value' in result.output


@pytest.mark.usefixtures('gtm_states')
def test_states_help(runner: CliRunner, gtm_states: States) -> None:
    """Test states command help."""
    result = runner.invoke(app, ['states', '--help'])
    assert not result.exception
    assert 'Get, set, or list state values' in result.output
