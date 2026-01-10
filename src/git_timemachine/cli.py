"""CLI for git_timemachine."""

import os
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from git_timemachine import __version__
from git_timemachine.commands import commit, review, shift, states
from git_timemachine.config import Settings, States

app = typer.Typer(no_args_is_help=True)
app.command(name='commit')(commit.commit_command)
app.command(name='review')(review.review_command)
app.command(name='shift')(shift.shift_command)
app.command(name='states')(states.states_command)


def version_callback(value: bool) -> None:
    """Print version and exit if --version flag is set."""
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    repo_dir: Annotated[
        Path | None, typer.Option(..., '--repo-dir', '-C', help='Path of repository directory.', metavar='PATH')
    ] = None,
    _: bool = typer.Option(
        None, '--version', help='Print version', callback=version_callback, is_eager=True, expose_value=False
    ),
) -> None:
    """A command-line tool that helps you record commits on Git repositories at any time node."""
    settings_file = Path(os.getenv('GIT_TIMEMACHINE_SETTINGS', Path.home() / '.git-timemachine' / 'settings.yaml'))
    states_file = Path(os.getenv('GIT_TIMEMACHINE_STATES', Path.home() / '.git-timemachine' / 'states.yaml'))

    if not settings_file.exists():
        typer.echo('Initializing git-timemachine configurations')
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        Settings().save(settings_file)

    if not states_file.exists():
        typer.echo('Initializing git-timemachine states')
        states_file.parent.mkdir(parents=True, exist_ok=True)
        States.model_validate({'last_commit_time': datetime.now()}).save(states_file)

    ctx.ensure_object(dict)

    ctx.obj['repo_dir'] = repo_dir if repo_dir else Path.cwd()
    ctx.obj['settings'] = Settings.load(settings_file)
    ctx.obj['states'] = States.load(states_file)
