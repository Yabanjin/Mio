"""Locate app-owned clients without installing their ML dependencies in MainApp."""
from pathlib import Path
import sys


def configure_module_paths():
    root = Path(__file__).resolve().parent.parent
    for directory in ("MemoireVectorielle", "Whisper Turbo", "Speechbrain", "SileroVAD",
                      "WebRTC", "Agent DVR", "LM Studio"):
        path = str(root / directory)
        if path not in sys.path:
            sys.path.append(path)
