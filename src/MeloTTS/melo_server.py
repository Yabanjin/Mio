"""Small local HTTP API for the cached Japanese MeloTTS voice."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import threading
import re


ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(ROOT / "hf_cache"))
os.environ.setdefault("HUGGINGFACE_HUB_CACHE", str(ROOT / "hf_cache" / "hub"))
os.environ.setdefault("TRANSFORMERS_CACHE", str(ROOT / "hf_cache" / "hub"))
os.environ.setdefault("TORCH_HOME", str(ROOT / "torch_cache"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import torch
EXECUTION = json.loads((ROOT / "config" / "execution.json").read_text(encoding="utf-8"))
torch.set_num_threads(max(1, int(EXECUTION["cpu_threads"])))
torch.set_num_interop_threads(max(1, int(EXECUTION["cpu_interop_threads"])))
from melo.api import TTS


HOST = "127.0.0.1"
PORT = 9882
DEVICE = "cuda:0"
SPEECH_SPEED = float(json.loads((ROOT / "config" / "vitesse.json").read_text(encoding="utf-8"))["speed"])
MODELS = {"JP": TTS(language="JP", device=DEVICE), "EN": TTS(language="EN", device=DEVICE)}
SPEAKER_IDS = {
    "JP": MODELS["JP"].hps.data.spk2id["JP"],
    "EN": MODELS["EN"].hps.data.spk2id["EN-US"],
}
SAMPLE_RATE = int(MODELS["JP"].hps.data.sampling_rate)
SYNTHESIS_LOCK = threading.Lock()
AUTO_AUDIO = {}


def synthesize(text, language):
    """Called under SYNTHESIS_LOCK, including during startup warm-up."""
    cached = AUTO_AUDIO.get((text, language))
    if cached is not None:
        return cached
    audio_file = BytesIO()
    with torch.inference_mode():
        MODELS[language].tts_to_file(text, SPEAKER_IDS[language], audio_file,
                                    speed=SPEECH_SPEED, format="wav", quiet=True)
    return audio_file.getvalue()


def prepare_auto_responses():
    # Only fixed project replies are cached; ordinary LLM replies use no cache.
    for path in sorted((ROOT.parent / "MainApp" / "reponse_auto").glob("*/phrases.json")):
        try:
            config = json.loads(path.read_text(encoding="utf-8-sig"))
            if not config.get("cache", True):
                continue
            for segment in config.get("segments", [config]):
                if segment.get("language") != "Japanese":
                    continue
                # Match the text MainApp sends after its TTS cleaning.
                text = re.sub(r"\*.*?\*", "", segment["text"])
                text = re.sub(r"[^a-zA-Z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ ,.!?'’\u3040-\u30ff\u4e00-\u9faf]", " ", text)
                text = re.sub(r"\s+", " ", text).strip()
                if text:
                    with SYNTHESIS_LOCK:
                        AUTO_AUDIO[(text, "JP")] = synthesize(text, "JP")
        except Exception as exc:
            print(f"[WARNING] Preparing {path.name} : {exc}", flush=True)
    print(f"Automatic responses prepared: {len(AUTO_AUDIO)} (TTS cache in RAM).", flush=True)


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        body = json.dumps(
            {"service": "MeloTTS", "voices": ["JP", "EN-US"], "sample_rate": SAMPLE_RATE, "device": DEVICE}
        ).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def do_POST(self) -> None:
        if self.path != "/tts":
            self._send(404, b"Not found", "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 1 or length > 1_000_000:
                self._send(400, b"Invalid request size", "text/plain; charset=utf-8")
                return
            payload = json.loads(self.rfile.read(length))
            text = str(payload.get("text", "")).strip()
            language = str(payload.get("language", "JP")).upper()
            if not text:
                self._send(400, b"Text is required", "text/plain; charset=utf-8")
                return
            if len(text) > 2000:
                self._send(400, b"Text is too long", "text/plain; charset=utf-8")
                return
            if language not in MODELS:
                self._send(400, b"Language must be JP or EN", "text/plain; charset=utf-8")
                return

            with SYNTHESIS_LOCK:
                audio = synthesize(text, language)
            self._send(200, audio, "audio/wav")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, str(exc).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")
        except Exception as exc:
            print(f"[ERROR MeloTTS] {exc}", flush=True)
            self._send(500, str(exc).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[MeloTTS] {self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    prepare_auto_responses()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"MeloTTS ready on http://{HOST}:{PORT} ({DEVICE}, {SAMPLE_RATE} Hz, model loaded)", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        MODELS.clear()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        print("MeloTTS server stopped; GPU cache released.", flush=True)


if __name__ == "__main__":
    main()
