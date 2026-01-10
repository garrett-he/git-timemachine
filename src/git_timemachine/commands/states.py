"""States command for getting and settings state values."""

from datetime import datetime
from typing import Annotated, get_args

import typer

from git_timemachine.config import States


def _is_datetime_type(annotation: type | None) -> bool:
    """Check if annotation is datetime or Optional[datetime]."""
    if annotation is datetime:
        return True

    return datetime in get_args(annotation)


def states_command(
    ctx: typer.Context,
    key: Annotated[str | None, typer.Argument(help='State key to get or set')] = None,
    value: Annotated[str | None, typer.Argument(help='State value to set')] = None,
) -> None:
    """Get, set, or list state values.

    Examples:
        git-timemachine states              # List all states
        git-timemachine states last_commit_time   # Get specific state
        git-timemachine states last_commit_time "2024-06-15T14:30:00"  # Set state
    """
    states: States = ctx.obj['states']

    if key is None:
        # List all states
        for field_name in States.model_fields:
            field_value = getattr(states, field_name)
            typer.echo(f'{field_name}={field_value}')
        return

    if key not in States.model_fields:
        typer.echo(f"Error: Unknown state key '{key}'", err=True)
        raise typer.Exit(1)

    if value is None:
        # Get state value
        typer.echo(getattr(states, key))
        return

    # Set state value
    field_info = States.model_fields[key]
    try:
        annotation = field_info.annotation
        if _is_datetime_type(annotation):
            parsed_value = datetime.fromisoformat(value)
        elif annotation is not None:
            parsed_value = annotation(value)
        else:
            typer.echo(f"Error: Cannot determine type for '{key}'", err=True)
            raise typer.Exit(1)

        setattr(states, key, parsed_value)
        states.save()
        typer.echo(f'{key}={parsed_value}')
    except (ValueError, TypeError) as e:
        typer.echo(f"Error: Invalid value for '{key}': {e}", err=True)
        raise typer.Exit(1) from None
