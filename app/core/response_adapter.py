def format_response(result: dict, is_bot: bool):
    if is_bot:
        return {
            "type": "message",
            "text": result.get("message", "No response"),
        }
    return result
