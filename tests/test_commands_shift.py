"""Tests for the shift command."""

from datetime import timedelta

import pytest
from typer.testing import CliRunner

from git_timemachine.cli import app
from git_timemachine.config import States


def _reload_states(gtm_states: States) -> States:
    """Reload states from disk to reflect CLI-side mutations."""
    return States.load(gtm_states._path)


@pytest.mark.usefixtures('gtm_settings')
def test_shift_days_forward(runner: CliRunner, gtm_states: States) -> None:
    """Shift last_commit_time forward by N days."""
    original = gtm_states.last_commit_time

    result = runner.invoke(app, ['shift', '--days', '3'])

    assert result.exit_code == 0
    updated = _reload_states(gtm_states)
    expected = original + timedelta(days=3)
    assert updated.last_commit_time == expected
    assert expected.isoformat() in result.output


@pytest.mark.usefixtures('gtm_settings')
def test_shift_days_backward(runner: CliRunner, gtm_states: States) -> None:
    """Shift last_commit_time backward by negative days."""
    original = gtm_states.last_commit_time

    result = runner.invoke(app, ['shift', '--days', '-5'])

    assert result.exit_code == 0
    updated = _reload_states(gtm_states)
    expected = original + timedelta(days=-5)
    assert updated.last_commit_time == expected
    assert expected.isoformat() in result.output


@pytest.mark.usefixtures('gtm_settings')
def test_shift_zero_days(runner: CliRunner, gtm_states: States) -> None:
    """Shift by zero days leaves last_commit_time unchanged."""
    original = gtm_states.last_commit_time

    result = runner.invoke(app, ['shift', '--days', '0'])

    assert result.exit_code == 0
    updated = _reload_states(gtm_states)
    assert updated.last_commit_time == original
    assert original.isoformat() in result.output


@pytest.mark.usefixtures('gtm_settings')
def test_shift_output_prefix(runner: CliRunner, gtm_states: States) -> None:
    """Output contains the expected prefix text."""
    result = runner.invoke(app, ['shift', '--days', '1'])

    assert result.exit_code == 0
    assert result.output.startswith('New timestamp: ')


@pytest.mark.usefixtures('gtm_settings')
def test_shift_with_hours_range(runner: CliRunner, gtm_states: States) -> None:
    """Shift days with hours min/max sets time within the given hour range."""
    result = runner.invoke(app, ['shift', '--days', '1', '--hours-min', '14', '--hours-max', '20'])

    assert result.exit_code == 0

    updated = _reload_states(gtm_states)
    assert 14 <= updated.last_commit_time.hour <= 20


@pytest.mark.usefixtures('gtm_settings')
def test_shift_with_partial_hours(runner: CliRunner, gtm_states: States) -> None:
    """Shift with only --hours-min uses default max hour of 23."""
    result = runner.invoke(app, ['shift', '--days', '0', '--hours-min', '22'])

    assert result.exit_code == 0

    updated = _reload_states(gtm_states)
    assert 22 <= updated.last_commit_time.hour <= 23


@pytest.mark.usefixtures('gtm_settings')
def test_shift_persists_state(runner: CliRunner, gtm_states: States) -> None:
    """Shift command saves the new state so it survives a reload."""
    original = gtm_states.last_commit_time

    runner.invoke(app, ['shift', '--days', '2'])

    updated = _reload_states(gtm_states)
    assert updated.last_commit_time != original

    reloaded = States.load(gtm_states._path)
    assert reloaded.last_commit_time == updated.last_commit_time


@pytest.mark.usefixtures('gtm_settings')
def test_shift_requires_days_option(runner: CliRunner) -> None:
    """Running shift without --days should fail."""
    result = runner.invoke(app, ['shift'])

    assert result.exit_code != 0
