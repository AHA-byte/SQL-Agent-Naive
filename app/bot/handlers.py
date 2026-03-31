import logging

from botbuilder.core import ActivityHandler, TurnContext
from botbuilder.schema import ActivityTypes

from app.bot.cards import build_message_activity
from app.core.sql_orchestrator import process_user_request


def _looks_like_kql(text: str) -> bool:
    lowered = text.lower()
    kql_markers = [
        "| where",
        "| project",
        "| order by",
        "| take",
        "ago(",
        "resultcode",
        "operation_id",
        "requests",
        "traces",
        "exceptions",
    ]
    return any(marker in lowered for marker in kql_markers)


def _monitoring_hint() -> str:
    return (
        "This bot answers business data questions from your SQL databases. "
        "It does not run Application Insights KQL queries. "
        "Run KQL in Azure Monitor Logs instead."
    )


class SqlActivityHandler(ActivityHandler):
    async def on_message_activity(self, turn_context: TurnContext):
        activity = turn_context.activity
        user_text = (activity.text or "").strip()

        if _looks_like_kql(user_text):
            logging.info("KQL-like prompt detected, returning monitoring hint")
            await turn_context.send_activity(_monitoring_hint())
            return

        logging.info(
            "Bot message received channel=%s conversation=%s text_present=%s",
            activity.channel_id,
            activity.conversation.id if activity.conversation else "",
            bool(user_text),
        )

        metadata = {
            "type": activity.type or "message",
            "channelId": activity.channel_id,
            "from": {"id": (activity.from_property.id if activity.from_property else "")},
            "conversation": {"id": (activity.conversation.id if activity.conversation else "")},
            "channelData": activity.channel_data or {},
            "value": activity.value or {},
        }

        result = process_user_request(user_text, metadata)
        logging.info("Bot SQL result status=%s row_count=%s", result.get("status"), len(result.get("rows") or []))
        reply = build_message_activity(result)
        await turn_context.send_activity(reply)
        logging.info("Bot reply sent for conversation=%s", activity.conversation.id if activity.conversation else "")

    async def on_members_added_activity(self, members_added, turn_context: TurnContext):
        for member in members_added:
            if member.id != turn_context.activity.recipient.id:
                await turn_context.send_activity(
                    "SQL Agent is ready. Ask a question like: show my latest jobs."
                )

    async def on_unrecognized_activity_type(self, turn_context: TurnContext):
        if turn_context.activity.type != ActivityTypes.message:
            logging.info("Bot non-message activity type=%s", turn_context.activity.type)
            await turn_context.send_activity("I currently handle message activities only.")


SQL_BOT = SqlActivityHandler()
