from app.main import process_message_request


def process_user_request(text: str, metadata: dict | None = None) -> dict:
    activity_payload = dict(metadata or {})
    activity_payload["text"] = text

    result, _ = process_message_request(activity_payload)
    return result
