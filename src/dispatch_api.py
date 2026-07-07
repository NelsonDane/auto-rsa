"""HTTP entrypoint so other containers can submit orders and holdings checks.

This is a third transport into the exact same `arg_parser(args) -> StockOrder`
-> `fun_run` pipeline the CLI and the `!rsa` Discord command already use -- not
a parallel implementation. Results are reported through the same `bot`/`loop`
already running in this process (via `print_and_discord`), so the Discord
channel stays the single place a human sees order outcomes or an OTP/captcha
prompt, regardless of which producer container originated the request.

Only mounted when `DISPATCH_API_KEY` is set (see auto_rsa.py); otherwise this
container behaves exactly as it did before -- Discord bot only, no new
network surface.
"""

import asyncio
import secrets
from typing import TYPE_CHECKING

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

if TYPE_CHECKING:
    from discord.ext import commands


class CommandRequest(BaseModel):
    """Same token grammar as the CLI / `!rsa` Discord command.

    e.g. ["buy", "1", "AAPL", "robinhood", "true"] or ["holdings", "all"].
    """

    args: list[str]


def create_app(
    *,
    bot: "commands.Bot",
    event_loop: asyncio.AbstractEventLoop,
    docker_mode: bool,
    order_lock: asyncio.Lock,
    api_key: str,
) -> FastAPI:
    """Build the dispatch API app bound to this process's running bot and loop."""
    # Local import: src.auto_rsa is what calls create_app, so importing it back
    # at module load time would be circular. By the time create_app actually
    # runs, src.auto_rsa is already fully loaded.
    from src.auto_rsa import arg_parser, fun_run  # noqa: PLC0415

    app = FastAPI(title="auto-rsa dispatch API")

    def _check_api_key(x_api_key: str = Header(alias="X-API-Key")) -> None:
        if not secrets.compare_digest(x_api_key, api_key):
            raise HTTPException(status_code=401, detail="Invalid API key")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/command", dependencies=[Depends(_check_api_key)])
    async def command(req: CommandRequest) -> dict[str, str]:
        try:
            order_obj = arg_parser(req.args)
            order_obj.order_validate(pre_login=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Same chokepoint the `!rsa` Discord command goes through: two
        # producers hitting a browser-automation broker at once means two
        # logins racing over the same on-disk session/cookie state.
        async with order_lock:
            await run_in_threadpool(fun_run, order_obj, bot, event_loop, docker_mode=docker_mode)
        return {"status": "completed"}

    return app
