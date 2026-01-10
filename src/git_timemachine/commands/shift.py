"""Shift command for adjusting the persisted last-commit timestamp."""

from __future__ import annotations

import random
from datetime import timedelta

import typer


def shift_command(
    ctx: typer.Context,
    days: int = typer.Option(..., '--days', '-d', help='Shift by N days'),
    hours_min: int | None = typer.Option(None, '--hours-min', '-h', help='Minimum hour (0-23) for random time'),
    hours_max: int | None = typer.Option(None, '--hours-max', '-H', help='Maximum hour (0-23) for random time'),
) -> None:
    """Adjust the persisted timestamp in the state file forward or backward."""
    states = ctx.obj['states']

    delta = timedelta(days=days or 0)
    base = states.last_commit_time + delta

    if hours_min is not None or hours_max is not None:
        h_min = hours_min if hours_min is not None else 0
        h_max = hours_max if hours_max is not None else 23
        assert 0 <= h_min <= 23 and 0 <= h_max <= 23
        assert h_min < h_max

        new_hour = random.randint(h_min, h_max)
        new_minute = random.randint(0, 59)
        new_second = random.randint(0, 59)
        new_time = base.replace(hour=new_hour, minute=new_minute, second=new_second)
    else:
        new_time = base

    states.last_commit_time = new_time

    states.save()
    typer.echo(f'New timestamp: {states.last_commit_time.isoformat()}')
