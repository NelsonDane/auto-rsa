import typer

from src.auto_rsa import main as rsa_main

app = typer.Typer()


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def main(ctx: typer.Context) -> None:
    """Entry point for the CLI."""
    rsa_main(ctx.args)


if __name__ == "__main__":
    app()
