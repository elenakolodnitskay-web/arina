import logging

from aiohttp import web

from config import settings
from max_bot.handlers import handle_text_message

logger = logging.getLogger(__name__)


async def handle_update(request: web.Request) -> web.Response:
    if settings.max_webhook_secret:
        secret = request.headers.get("X-Max-Bot-Api-Secret")
        if secret != settings.max_webhook_secret:
            return web.Response(status=403)

    data = await request.json()
    update_type = data.get("update_type")

    if update_type == "message_created":
        message = data.get("message", {})
        text = message.get("body", {}).get("text")
        sender = message.get("sender") or message.get("from") or {}
        user_id = sender.get("user_id")
        if text and user_id:
            try:
                await handle_text_message(user_id, text)
            except Exception:
                logger.error("Unhandled exception while processing a MAX update", exc_info=True)

    return web.Response(status=200)


def build_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook", handle_update)
    return app


async def start_webhook_server() -> None:
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.max_webhook_port)
    await site.start()
    logger.info("MAX webhook server started on port %s", settings.max_webhook_port)
