import typer

from src.auto_rsa import main as rsa_main

app = typer.Typer()


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def main(ctx: typer.Context) -> None:
    """Entry point for the CLI."""
    if ctx.args and ctx.args[0].lower() == "mcp":
        # Lazy load since this imports and starts the MCP server when imported
        from src.mcp_server import run as run_mcp_server  # ruff: ignore[import-outside-top-level]

        run_mcp_server()
        return
    rsa_main(ctx.args)


if __name__ == "__main__":
    app()
