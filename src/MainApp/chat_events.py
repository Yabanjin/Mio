"""Display-only events. No changes to recognition, prompts or authorization."""
import json
import logging
import os
import sys
import threading
import uuid

PREFIX = "@@MIO_CHAT@@"
_token = os.environ.get("MIO_UI_TOKEN", "")
_lock = threading.RLock()
_mode = "SLEEP MODE"
_generation = 0
_last_state = None


def emit(kind, **values):
    if not _token:
        return
    with _lock:
        event = dict(kind=kind, mode=_mode, generation=_generation, **values)
        event["token"] = _token
        try:
            # Previous console prints may have left an unfinished line.
            sys.stdout.write("\n" + PREFIX + json.dumps(event, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except (OSError, ValueError):
            pass  # A closed display must not change conversation decisions.


def state(active, generation, ready=True, child_mode=False, family_mode="Normal"):
    global _mode, _generation, _last_state
    with _lock:
        _mode = "ACTIVE MODE" if active else "SLEEP MODE"
        _generation = generation
        value = (_mode, generation, bool(ready), bool(child_mode), family_mode)
        if value == _last_state:
            return
        _last_state = value
        emit("state", ready=ready, child_mode=child_mode, family_mode=family_mode)


def message(key, text, names=(), *, complete=False, mio=False):
    emit("message", key=key, text=text, names=list(names),
         stage="FULL TEXT" if complete else "PREPROCESSING", mio=mio)


class ChatErrors(logging.Handler):
    def emit(self, record):
        if record.levelno >= logging.ERROR:
            emit("error", key=uuid.uuid4().hex,
                 text=(record.getMessage().splitlines() or ['MainApp error'])[0][:300])


def install_error_handler():
    if _token:
        logging.getLogger().addHandler(ChatErrors(level=logging.ERROR))
