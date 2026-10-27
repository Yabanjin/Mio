"""Client for the isolated Speechbrain speaker-recognition service."""

from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import requests


ROOT_DIR = Path(__file__).resolve().parent.parent
SERVICE_DIR = ROOT_DIR / "Speechbrain"
SERVICE_PYTHON = Path(os.environ.get('MIO_PYTHON') or __import__('sys').executable)
SERVICE_SCRIPT = SERVICE_DIR / "speaker_recognition_server.py"
PROFILE_FILE = SERVICE_DIR / "profiles.json"
MODEL_DIR = Path(os.environ.get('MIO_SPEAKER_MODEL', str(ROOT_DIR / "huggingface" / "speechbrain" / "spkrec-ecapa-voxceleb")))
SERVICE_URL = os.getenv("MIO_SPEAKER_URL", "http://127.0.0.1:9010")
SERVICE_LOG = ROOT_DIR.parent / "data" / "logs" / "speechbrain.log"


class SpeakerRecognizer:
    """Start and call the dedicated local voice identification service."""

    def __init__(self):
        self._start_lock = threading.Lock()
        self.process = None

    def _service_ready(self) -> bool:
        try:
            response = requests.get(f"{SERVICE_URL}/health", timeout=2)
            return response.ok and response.json().get("service") == "Speechbrain"
        except requests.RequestException:
            return False

    def _start_service(self) -> bool:
        if self._service_ready():
            return True
        if not SERVICE_PYTHON.is_file() or not SERVICE_SCRIPT.is_file():
            logging.error(
                "Environnement Speechbrain introuvable. Lance Speechbrain\\setup_environment.bat."
            )
            return False
        with self._start_lock:
            if self._service_ready():
                return True
            SERVICE_LOG.parent.mkdir(parents=True, exist_ok=True)
            log_file = SERVICE_LOG.open("a", encoding="utf-8")
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            try:
                child_env = os.environ.copy()
                temp_dir = SERVICE_DIR / "cache" / "tmp"
                temp_dir.mkdir(parents=True, exist_ok=True)
                child_env.update(HF_HOME=str(ROOT_DIR / "huggingface"), HF_HUB_OFFLINE="1",
                                 TORCH_HOME=str(SERVICE_DIR / "cache" / "torch"),
                                 TEMP=str(temp_dir), TMP=str(temp_dir))
                self.process = subprocess.Popen(
                    [
                        str(SERVICE_PYTHON),
                        "-u",
                        str(SERVICE_SCRIPT),
                        "--profiles",
                        str(PROFILE_FILE),
                        "--model-dir",
                        str(MODEL_DIR),
                    ],
                    cwd=str(ROOT_DIR),
                    stdin=subprocess.DEVNULL,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=creation_flags,
                    close_fds=True,
                    env=child_env,
                )
                log_file.close()
            except OSError:
                log_file.close()
                logging.exception("Unable to start the SpeechBrain service.")
                return False
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self._service_ready():
                return True
            time.sleep(0.25)
        logging.error("SpeechBrain service is not responding at %s.", SERVICE_URL)
        return False

    def warm_up(self) -> None:
        """Start the local service and load its model in the dedicated env."""
        if not self._start_service():
            return
        try:
            response = requests.post(f"{SERVICE_URL}/warmup", timeout=300)
            response.raise_for_status()
            health = requests.get(f"{SERVICE_URL}/health", timeout=2).json()
            logging.info("SpeechBrain %s (%s) ready; usable references: %s.",
                         health.get("device", "not specified"), health.get("gpu_uuid", "not specified"),
                         health.get("profiles", []))
        except requests.RequestException:
            logging.exception("SpeechBrain model loading unavailable.")

    def identify(self, audio_buffer) -> dict:
        started = time.monotonic()
        unknown = {
            "name": None,
            "role": "unknown",
            "prompt": None,
            "authorized": False,
            "score": 0.0,
            "names": [],
            "speakers": [],
        }
        if audio_buffer is None or not self._service_ready():
            return unknown
        try:
            audio_buffer.seek(0)
            response = requests.post(
                f"{SERVICE_URL}/identify",
                data=audio_buffer.read(),
                headers={"Content-Type": "audio/wav"},
                timeout=(0.5, 2.0),
            )
            response.raise_for_status()
            result = response.json()
            logging.info("SpeechBrain %.2f s: names=%s, best candidate=%s, similarity=%s, threshold=%s.",
                         time.monotonic() - started, result.get("names", []),
                         result.get("best_candidate"), result.get("best_similarity"), result.get("threshold"))
            audio_buffer.seek(0)
            return result
        except (requests.RequestException, ValueError):
            logging.warning("Speaker identification unavailable; text retained without speaker tags.")
            try:
                audio_buffer.seek(0)
            except (AttributeError, OSError, ValueError):
                pass
            return unknown

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()


SPEAKER_RECOGNIZER = SpeakerRecognizer()
