import os

from botbuilder.core import BotFrameworkAdapter, BotFrameworkAdapterSettings, TurnContext


def _get_setting(name: str) -> str:
    return os.getenv(name, "").strip()


SETTINGS = BotFrameworkAdapterSettings(
    app_id=_get_setting("MicrosoftAppId") or _get_setting("BOT_APP_ID"),
    app_password=_get_setting("MicrosoftAppPassword") or _get_setting("BOT_APP_PASSWORD"),
    channel_auth_tenant=(
        _get_setting("MicrosoftAppTenantId")
        or _get_setting("BOT_APP_TENANT_ID")
    ),
)
BOT_ADAPTER = BotFrameworkAdapter(SETTINGS)


async def _on_error(turn_context: TurnContext, error: Exception):
    await turn_context.send_activity("The bot encountered an unexpected error.")


BOT_ADAPTER.on_turn_error = _on_error
