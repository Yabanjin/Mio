"""Install the multilingual Turbo weights locally; no token required."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ["HF_HOME"] = str(ROOT / "cache" / "huggingface")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
from huggingface_hub import snapshot_download

if __name__ == "__main__":
    snapshot_download(
        repo_id="mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        local_dir=str(ROOT / "models" / "large-v3-turbo"),
        allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"],
    )
    print("Turbo model downloaded.", flush=True)
