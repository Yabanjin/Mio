"""Fresh system-clock context, never written into chat history or vector memory."""
import json
from datetime import datetime
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "MainApp" / "config" / "horloge.json").read_text(encoding="utf-8"))
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def with_current_time(messages):
    if not CONFIG["enabled"]:
        return messages
    now = datetime.now().astimezone()
    offset = now.strftime("%z")
    instruction = CONFIG["instruction"].format(
        datetime=now.strftime("%Y-%m-%d %H:%M:%S"),
        weekday=WEEKDAYS[now.weekday()],
        offset=offset[:3] + ":" + offset[3:],
    )
    result = [dict(message) for message in messages]
    if result and result[0].get("role") == "system":
        result[0]["content"] += "\n\n" + instruction
    else:
        result.insert(0, {"role": "system", "content": instruction})
    return result
