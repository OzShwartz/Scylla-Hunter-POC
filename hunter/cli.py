"""Typer CLI: reset, run, review, approve, reject, edit, event, simulate, report, eval, serve."""

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)

if __name__ == "__main__":
    app()
