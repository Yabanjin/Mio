"""Per-model generation options, shared by conversation and memory requests."""
import json
from pathlib import Path

CONFIG = json.loads((Path(__file__).resolve().parent.parent / "MainApp" / "config" / "llm_generation.json").read_text(encoding="utf-8"))


def generation_options(model):
    return dict(CONFIG.get("models", {}).get(model, {}))


def conversation_options():
    return {'max_tokens': int(CONFIG.get('conversation_max_tokens', 3072))}
