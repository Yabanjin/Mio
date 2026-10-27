"""Local speaker verification service, isolated from MainApp's Python env."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

ROOT_DIR = Path(__file__).resolve().parent.parent
EXECUTION = json.loads(Path(__file__).with_name("execution.json").read_text(encoding="utf-8"))
os.environ["CUDA_VISIBLE_DEVICES"] = EXECUTION["gpu_uuid"]
os.environ.setdefault("HF_HOME", str(ROOT_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_OFFLINE", "1")

SAMPLE_RATE = 16000
MIN_PHRASE_SECONDS = 1.2
DEFAULT_MATCH_THRESHOLD = 0.72
MODEL_SOURCE = "speechbrain/spkrec-ecapa-voxceleb"


class SpeakerRecognizer:
    def __init__(self, profile_file: Path, model_dir: Path):
        self.profile_file = profile_file
        self.model_dir = model_dir
        self._lock = threading.Lock()
        self._model = None
        self._profiles = []
        self._torch = None
        self._profile_stamp = None

    def load(self):
        if self._model is not None:
            with self._lock:
                self._refresh_profiles()
            return
        with self._lock:
            if self._model is not None:
                return
            import torch
            from speechbrain.inference.speaker import SpeakerRecognition
            from speechbrain.utils.fetching import LocalStrategy

            torch.set_num_threads(max(1, int(EXECUTION["cpu_threads"])))
            if not torch.cuda.is_available():
                raise RuntimeError("SpeechBrain CUDA requested but unavailable; check its GPU environment")
            self._model = SpeakerRecognition.from_hparams(
                source=str(self.model_dir),
                savedir=str(self.model_dir),
                local_strategy=LocalStrategy.COPY_SKIP_CACHE,
                run_opts={"device": EXECUTION["device"]},
            )
            self._torch = torch
            self._refresh_profiles()
            logging.info(
                "Speaker recognition ready; loaded profiles: %s",
                ", ".join(p["name"] for p in self._profiles) or "none",
            )

    def _refresh_profiles(self):
        config = json.loads(self.profile_file.read_text(encoding="utf-8-sig"))
        stamp = [self.profile_file.stat().st_mtime_ns]
        for entry in config.get("profiles", []):
            for reference in entry.get("reference_files", []):
                path = self.profile_file.parent / reference
                stat = path.stat() if path.is_file() else None
                stamp.append((str(path), stat.st_size if stat else 0, stat.st_mtime_ns if stat else 0))
        if stamp != self._profile_stamp:
            self._profiles = self._read_profiles()
            self._profile_stamp = stamp
            logging.info("Usable references: %s", [p["name"] for p in self._profiles])

    @staticmethod
    def _read_audio(path: Path) -> np.ndarray:
        audio, sample_rate = sf.read(path, dtype="float32", always_2d=True)
        audio = np.mean(audio, axis=1, dtype=np.float32)
        if sample_rate != SAMPLE_RATE:
            divisor = math.gcd(int(sample_rate), SAMPLE_RATE)
            audio = resample_poly(
                audio, SAMPLE_RATE // divisor, int(sample_rate) // divisor
            ).astype(np.float32, copy=False)
        return np.ascontiguousarray(audio)

    def _read_profiles(self):
        config = json.loads(self.profile_file.read_text(encoding="utf-8-sig"))
        profiles = []
        for entry in config.get("profiles", []):
            if not entry.get("authorized", False):
                continue
            references = []
            for reference in entry.get("reference_files", []):
                path = (self.profile_file.parent / reference).resolve()
                if not path.is_file():
                    logging.warning("Voice reference not found: %s", path)
                    continue
                try:
                    audio = self._read_audio(path)
                    if audio.size < int(SAMPLE_RATE * MIN_PHRASE_SECONDS):
                        logging.warning("Voice reference too short: %s", path)
                        continue
                    waveform = self._torch.from_numpy(audio).unsqueeze(0)
                    with self._torch.inference_mode():
                        embedding = self._model.encode_batch(waveform, normalize=True)
                    references.append(embedding.reshape(-1).detach())
                except Exception:
                    logging.exception("Unreadable voice reference: %s", path)
            if references:
                profiles.append(
                    {
                        "name": str(entry["name"]),
                        "role": str(entry.get("role", "adult")),
                        "prompt": str(entry.get("prompt", "Normal")),
                        "references": references,
                    }
                )
        self.threshold = float(config.get("match_threshold", DEFAULT_MATCH_THRESHOLD))
        return profiles

    def identify(self, wav_data: bytes) -> dict:
        import io

        unknown = {
            "name": None,
            "role": "unknown",
            "prompt": None,
            "authorized": False,
            "score": 0.0,
            "names": [],
            "speakers": [],
        }
        audio, sample_rate = sf.read(
            io.BytesIO(wav_data), dtype="float32", always_2d=True
        )
        audio = np.mean(audio, axis=1, dtype=np.float32)
        if sample_rate != SAMPLE_RATE:
            divisor = math.gcd(int(sample_rate), SAMPLE_RATE)
            audio = resample_poly(
                audio, SAMPLE_RATE // divisor, int(sample_rate) // divisor
            ).astype(np.float32, copy=False)
        if audio.size < int(SAMPLE_RATE * MIN_PHRASE_SECONDS) or not self._profiles:
            return unknown
        found = {}
        diagnostic_best = None
        # Short overlapping windows give global names; no word/speaker attribution.
        with self._lock, self._torch.inference_mode():
            for offset in range(0, audio.size, SAMPLE_RATE * 2):
                window = audio[offset:offset + SAMPLE_RATE * 3]
                if window.size < int(SAMPLE_RATE * MIN_PHRASE_SECONDS):
                    continue
                waveform = self._torch.from_numpy(np.ascontiguousarray(window)).unsqueeze(0)
                query = self._model.encode_batch(waveform, normalize=True).reshape(-1).detach()
                best = None
                for profile in self._profiles:
                    score = max(float(self._torch.nn.functional.cosine_similarity(query, ref, dim=0).item())
                                for ref in profile["references"])
                    if best is None or score > best["score"]:
                        best = {k: v for k, v in profile.items() if k != "references"}
                        best["score"] = score
                if best and (diagnostic_best is None or best["score"] > diagnostic_best["score"]):
                    diagnostic_best = best
                if best and best["score"] >= self.threshold:
                    if best["score"] > found.get(best["name"], {}).get("score", -1):
                        found[best["name"]] = best
        diagnostics = {"best_candidate": diagnostic_best["name"] if diagnostic_best else None,
                       "best_similarity": round(diagnostic_best["score"], 4) if diagnostic_best else None,
                       "threshold": self.threshold}
        if not found:
            unknown.update(diagnostics)
            return unknown
        speakers = list(found.values())
        family = [p for p in speakers if p["role"] != "assistant"]
        chosen = next((p for p in family if p["role"] == "child"), family[0] if family else speakers[0])
        return {**chosen, **diagnostics, "authorized": bool(family), "names": [p["name"] for p in speakers],
                "speakers": speakers}


class ServiceHandler(BaseHTTPRequestHandler):
    recognizer: SpeakerRecognizer

    def log_message(self, fmt, *args):
        logging.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload: dict):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._json(200, {"service": "Speechbrain", "ready": self.recognizer._model is not None,
                             "device": EXECUTION["device"], "gpu_uuid": EXECUTION["gpu_uuid"],
                             "profiles": [p["name"] for p in self.recognizer._profiles]})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/warmup":
            try:
                self.recognizer.load()
                self._json(200, {"ready": True})
            except Exception:
                logging.exception("Failed to load the SpeechBrain model")
                self._json(503, {"ready": False, "error": "model unavailable"})
            return
        if self.path != "/identify":
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 20 * 1024 * 1024:
                self._json(400, {"error": "invalid audio size"})
                return
            self.recognizer.load()
            result = self.recognizer.identify(self.rfile.read(length))
            self._json(200, result)
        except Exception:
            logging.exception("Speaker identification failed")
            self._json(500, {"error": "identification failed"})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=9010, type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ServiceHandler.recognizer = SpeakerRecognizer(args.profiles, args.model_dir)
    server = ThreadingHTTPServer((args.host, args.port), ServiceHandler)
    logging.info("Local SpeechBrain running at http://%s:%s", args.host, args.port)
    server.serve_forever()


if __name__ == "__main__":
    main()
