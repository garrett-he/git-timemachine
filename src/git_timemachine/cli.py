"""CLI for git_timemachine."""

import typer

app = typer.Typer()


@app.command()
def main() -> None:
    """Print a greeting."""
    typer.echo('Hello, world!')
