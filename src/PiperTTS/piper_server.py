from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import threading
import wave
import onnxruntime
onnxruntime.preload_dlls(directory="")

from piper import PiperVoice
from piper.config import SynthesisConfig, PiperConfig


ROOT = Path(__file__).resolve().parent
VOICE = json.loads((ROOT / 'config' / 'voix.json').read_text(encoding='utf-8'))
MODEL_ROOT = Path(os.environ.get('MIO_PIPER_MODELS', str(ROOT / 'models')))
MODEL = MODEL_ROOT / VOICE['model_file']
CONFIG = MODEL_ROOT / VOICE['config_file']
VOICE_NAME = VOICE['name']
HOST = "127.0.0.1"
PORT = 9881
LENGTH_SCALE = float(json.loads((ROOT / "config" / "vitesse.json").read_text(encoding="utf-8"))["length_scale"])
EXECUTION = json.loads((ROOT / "config" / "execution.json").read_text(encoding="utf-8"))
SESSION_OPTIONS = onnxruntime.SessionOptions()
SESSION_OPTIONS.intra_op_num_threads = max(1, int(EXECUTION["cpu_threads"]))
SESSION_OPTIONS.inter_op_num_threads = max(1, int(EXECUTION["cpu_interop_threads"]))
SESSION_OPTIONS.add_session_config_entry("session.intra_op.allow_spinning", "0")
SESSION_OPTIONS.add_session_config_entry("session.inter_op.allow_spinning", "0")
# Same model/config/CUDA provider options as PiperVoice.load; bounded CPU helpers.
VOICE = PiperVoice(
    config=PiperConfig.from_dict(json.loads(CONFIG.read_text(encoding="utf-8"))),
    session=onnxruntime.InferenceSession(str(MODEL), sess_options=SESSION_OPTIONS,
        providers=[("CUDAExecutionProvider", {"cudnn_conv_algo_search": "HEURISTIC"})]),
    download_dir=Path.cwd(),
)
if "CUDAExecutionProvider" not in VOICE.session.get_providers():
    raise RuntimeError("Piper requires GPU 0: CUDAExecutionProvider unavailable.")
SYNTHESIS_LOCK = threading.Lock()


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
        body = json.dumps({"service": "PiperTTS", "voice": VOICE_NAME, "device": "cuda:0"}).encode("utf-8")
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
            if not text:
                self._send(400, b"Text is required", "text/plain; charset=utf-8")
                return

            audio = BytesIO()
            with SYNTHESIS_LOCK:
                with wave.open(audio, "wb") as wav_file:
                    VOICE.synthesize_wav(
                        text, wav_file, syn_config=SynthesisConfig(speaker_id=0, length_scale=LENGTH_SCALE)
                    )
            self._send(200, audio.getvalue(), "audio/wav")
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, str(exc).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")
        except Exception as exc:
            print(f"[ERROR Piper] {exc}", flush=True)
            self._send(500, str(exc).encode("utf-8", errors="replace"), "text/plain; charset=utf-8")

    def log_message(self, fmt: str, *args) -> None:
        print(f"[Piper] {self.address_string()} - {fmt % args}", flush=True)


def main() -> None:
    if not MODEL.is_file() or not CONFIG.is_file():
        raise FileNotFoundError("UPMC/Jessica model or configuration missing in PiperTTS\\models.")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Piper UPMC/Jessica ready on http://{HOST}:{PORT} (GPU 0)", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        print("Piper UPMC/Jessica server stopped.", flush=True)


if __name__ == "__main__":
    main()
