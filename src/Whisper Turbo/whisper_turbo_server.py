"""Mio STT: whole utterance -> multilingual Turbo -> language validation."""
import io
import json
import logging
import os
import re
import threading
import time
import bisect
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from math import gcd
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8-sig"))
os.environ["CUDA_VISIBLE_DEVICES"] = CONFIG["gpu_uuid"]
os.environ["HF_HOME"] = str(ROOT / "cache" / "huggingface")
os.environ["HF_HUB_OFFLINE"] = "1"
# PyTorch supplies CUDA/cuDNN DLLs and normalizes token distributions on GPU.
import torch
_dll_handles = []
if os.name == "nt":
    _torch_lib = str(Path(torch.__file__).parent / "lib")
    os.environ["PATH"] = _torch_lib + os.pathsep + os.environ.get("PATH", "")
    _dll_handles.append(os.add_dll_directory(_torch_lib))

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from faster_whisper import WhisperModel
from langid.langid import LanguageIdentifier, model as language_model
from token_confidence import TokenConfidenceDecoder

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("Whisper-Turbo")
LOCK = threading.Lock()
MODEL = None
DECODER = None
LANGUAGE_ID = LanguageIdentifier.from_modelstring(language_model, norm_probs=True)
ALLOWED = set(CONFIG["allowed_languages"])
CANCELLED = {}  # session/generation -> expiry; never cancels another client.
CANCEL_LOCK = threading.Lock()


def is_cancelled(group):
    with CANCEL_LOCK:
        now = time.monotonic()
        for key in list(CANCELLED):
            if CANCELLED[key] < now:
                del CANCELLED[key]
        return bool(group) and group in CANCELLED


def scored_words(segment, probabilities):
    """Partition the original emitted-token scores across aligned words.

    Alignment adds times only; it does not replace the existing confidence
    method with the aligner's word probability. Unicode tokens may span a word.
    """
    words = list(segment.words or [])
    if not words:
        if segment.text.strip():
            raise ValueError("Text without time alignment")
        return []
    norm = lambda text: re.sub(r"\s+", "", text)
    if norm("".join(w.word for w in words)) != norm(segment.text):
        raise ValueError("Inconsistent text/word alignment")
    boundaries, length = [], 0
    for word in words:
        length += len(norm(word.word))
        boundaries.append(length)
    tokens = [t for t in segment.tokens if t < DECODER.end_of_text_token]
    if len(tokens) != len(probabilities):
        raise ValueError("Scores individuels incomplets")
    result = [{"word": w.word, "start": w.start, "end": w.end,
               "probability_sum": 0.0, "token_count": 0} for w in words]
    for index, probability in enumerate(probabilities):
        prefix = MODEL.hf_tokenizer.decode(tokens[:index + 1])
        position = len(norm(prefix.rstrip("\ufffd")))
        bucket = min(len(words) - 1, bisect.bisect_left(boundaries, max(1, position)))
        result[bucket]["probability_sum"] += probability
        result[bucket]["token_count"] += 1
    return result


def validate_language(text, detected_language):
    """Check complete text after decoding. Short fragments use the audio hint.

    This statistical check cannot guarantee language purity in names or mixtures.
    """
    if re.search(r"[\u0400-\u052f\u0600-\u06ff\uac00-\ud7af]", text):
        return "unsupported_script"
    japanese = bool(re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text))
    latin = re.sub(r"[\u3040-\u30ff\u4e00-\u9fff]", " ", text)
    letters = sum(c.isalpha() for c in latin)
    languages = {"ja"} if japanese else set()
    if letters:
        code, probability = LANGUAGE_ID.classify(latin)
        if letters >= int(CONFIG["text_language_min_letters"]) and probability >= float(CONFIG["text_language_confidence"]):
            if code not in ALLOWED:
                return code
            languages.add(code)
        elif detected_language in {"fr", "en"}:
            languages.add(detected_language)
        elif code in {"fr", "en"} and probability >= float(CONFIG["text_language_confidence"]):
            languages.add(code)
        elif not japanese:
            return detected_language if detected_language not in ALLOWED else "und"
    if not languages:
        return detected_language
    if detected_language not in ALLOWED and not re.search(r"[\u3040-\u30ff]", text) and not letters:
        return detected_language
    return "mixed" if len(languages) > 1 else next(iter(languages))


def transcribe(audio, progressive=False, group=""):
    started = time.monotonic()
    while not LOCK.acquire(timeout=0.05):
        if is_cancelled(group):
            return {"cancelled": True}
    try:
        if is_cancelled(group):
            return {"cancelled": True}
        DECODER.reset()
        # MainApp already assembles speech with Silero. No second VAD, no fixed
        # six-second language slices, and no language rejection before decoding.
        iterator, info = MODEL.transcribe(
            audio, language=None, task="transcribe", multilingual=True,
            beam_size=int(CONFIG["beam_size"]), temperature=float(CONFIG["temperature"]),
            condition_on_previous_text=False, vad_filter=False,
            word_timestamps=progressive, no_speech_threshold=float(CONFIG["no_speech_threshold"]),
            log_prob_threshold=float(CONFIG["log_prob_threshold"]),
        )
        segments = []
        for segment in iterator:
            if is_cancelled(group):
                return {"cancelled": True}
            confidence = DECODER.accept(segment.tokens)
            segments.append({"text": segment.text.strip(), "start": segment.start,
                             "end": segment.end, "token_confidence": confidence,
                             "words": scored_words(segment, DECODER.last_values) if progressive else []})
        text = " ".join(s["text"] for s in segments).strip()
        language = validate_language(text, info.language) if text else ""
        result = {"text": text, "language": language, "detected_language": info.language,
                  "language_probability": info.language_probability,
                  "token_confidence": DECODER.mean(), "token_count": DECODER.token_count,
                  "confidence_method": "mean_token_probability", "segments": segments}
    finally:
        LOCK.release()
    result["elapsed_seconds"] = time.monotonic() - started
    log.info("Turbo %.2f s | audio %.2f s | langue %s (audio %s) | score %.1f%% | %s",
             result["elapsed_seconds"], len(audio) / 16000, language, info.language,
             result["token_confidence"] * 100, text or "no text")
    return result


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, result):
        payload = json.dumps(result, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path in {"/", "/health"}:
            self.send_json(200, {"service": "WhisperTurbo", "ready": MODEL is not None,
                                "model": CONFIG["model"], "device": "cuda:0",
                                "gpu_uuid": CONFIG["gpu_uuid"],
                                "progressive_protocol": 1,
                                "confidence_method": "mean_token_probability"})
        else:
            self.send_json(404, {"error": "Unknown endpoint"})

    def do_POST(self):
        if self.path in {"/cancel", "/validate"}:
            try:
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size < 1024 * 1024:
                    raise ValueError("Invalid size")
                request = json.loads(self.rfile.read(size))
                if self.path == "/cancel":
                    with CANCEL_LOCK:
                        CANCELLED[str(request["group"])] = time.monotonic() + 600
                    self.send_json(200, {"cancelled": True})
                else:
                    # Same language check on the assembled text, not tiny fragments.
                    with LOCK:
                        language = validate_language(str(request["text"]), str(request["language"]))
                    self.send_json(200, {"language": language})
            except Exception as exc:
                self.send_json(400, {"error": str(exc)})
            return
        if self.path != "/v1/audio/transcriptions":
            self.send_json(404, {"error": "Unknown endpoint"})
            return
        try:
            size = int(self.headers.get("Content-Length", 0))
            content_type = self.headers.get("Content-Type", "")
            if not 0 < size <= 100 * 1024 * 1024 or "multipart/form-data" not in content_type:
                self.send_json(400, {"error": "Invalid audio request"})
                return
            message = BytesParser(policy=default).parsebytes(
                b"Content-Type: " + content_type.encode("latin-1")
                + b"\r\nMIME-Version: 1.0\r\n\r\n" + self.rfile.read(size))
            payload = next((p.get_payload(decode=True) for p in message.iter_parts()
                            if p.get_param("name", header="content-disposition") == "file"), None)
            if not payload:
                self.send_json(400, {"error": "Fichier audio absent"})
                return
            audio, sr = sf.read(io.BytesIO(payload), dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if not audio.size or not np.isfinite(audio).all():
                self.send_json(400, {"error": "Empty or non-finite audio"})
                return
            if sr != 16000:
                divisor = gcd(sr, 16000)
                audio = resample_poly(audio, 16000 // divisor, sr // divisor).astype(np.float32)
            log.info("Received %.2f s of audio, RMS %.2f%%, peak %.2f%%", len(audio) / 16000,
                     np.sqrt(np.mean(audio ** 2)) * 100, np.max(np.abs(audio)) * 100)
            fields = {p.get_param("name", header="content-disposition"): p.get_payload(decode=True)
                      for p in message.iter_parts()}
            progressive = fields.get("progressive", b"0") == b"1"
            group = fields.get("group", b"").decode("utf-8")
            self.send_json(200, transcribe(audio, progressive, group))
        except Exception as exc:
            log.exception("Turbo transcription failed")
            try:
                self.send_json(500, {"error": str(exc)})
            except OSError:
                pass


def main():
    global MODEL, DECODER
    model_path = Path(os.environ.get('MIO_WHISPER_MODELS', str(ROOT / 'models'))) / CONFIG['model']
    MODEL = WhisperModel(str(model_path), device=CONFIG["device"], device_index=0,
                         compute_type=CONFIG["compute_type"], local_files_only=True,
                         num_workers=1)
    eot = MODEL.hf_tokenizer.token_to_id("<|endoftext|>")
    if eot is None:
        raise RuntimeError("Whisper end token missing")
    DECODER = TokenConfidenceDecoder(MODEL.model, eot)
    MODEL.model = DECODER
    log.info("Whisper Turbo ready on GPU 0 (%s), model %s", CONFIG["gpu_uuid"], CONFIG["model"])
    with ThreadingHTTPServer((CONFIG["host"], int(CONFIG["port"])), Handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
