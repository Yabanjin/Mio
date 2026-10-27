"""MainApp's small IPC client for the isolated WebRTC AEC3 service."""

import os
import logging
import socket
import subprocess
import threading
import time
from math import gcd

import numpy as np
from scipy.signal import resample_poly


SAMPLE_RATE = 16000
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 4
WEBRTC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "WebRTC"))
WEBRTC_PYTHON = os.environ.get('MIO_PYTHON') or __import__('sys').executable
WEBRTC_SERVICE = os.path.join(WEBRTC_DIR, "aec_service.py")


class EchoCancellationError(RuntimeError):
    pass


class PlaybackReference:
    """Timestamped mono reference for the exact audio handed to sd.play."""

    def __init__(self):
        self.lock = threading.Lock()
        self.audio = np.empty(0, dtype=np.float32)
        self.started_at = 0.0

    @staticmethod
    def prepare(audio, sample_rate):
        mono = np.asarray(audio, dtype=np.float32)
        if mono.ndim == 2:
            mono = mono.mean(axis=1)
        if sample_rate != SAMPLE_RATE:
            divisor = gcd(sample_rate, SAMPLE_RATE)
            mono = resample_poly(mono, SAMPLE_RATE // divisor, sample_rate // divisor)
        return np.ascontiguousarray(mono, dtype=np.float32)

    def start(self, audio, started_at):
        with self.lock:
            self.audio = audio
            self.started_at = started_at

    def clear(self):
        with self.lock:
            self.audio = np.empty(0, dtype=np.float32)
            self.started_at = 0.0

    def for_capture(self, captured_at):
        frame = np.zeros(FRAME_SAMPLES, dtype=np.float32)
        with self.lock:
            if not self.audio.size:
                return frame
            first = round((captured_at - FRAME_SAMPLES / SAMPLE_RATE - self.started_at) * SAMPLE_RATE)
            source_start = max(0, first)
            source_end = min(self.audio.size, first + FRAME_SAMPLES)
            if source_end > source_start:
                target_start = source_start - first
                frame[target_start:target_start + source_end - source_start] = self.audio[source_start:source_end]
        return frame


class EchoClient:
    def __init__(self, reference):
        self.reference = reference
        self.process = None
        self.connection = None
        self.diagnostic_started = time.monotonic()
        self.diagnostic_frames = 0
        self.diagnostic_near_power = 0.0
        self.diagnostic_far_power = 0.0
        self.diagnostic_clean_power = 0.0
        self.diagnostic_process_seconds = 0.0

    @staticmethod
    def _read_exact(connection, count):
        data = bytearray()
        while len(data) < count:
            part = connection.recv(count - len(data))
            if not part:
                raise EchoCancellationError("WebRTC connection closed")
            data.extend(part)
        return bytes(data)

    def start(self):
        if not os.path.isfile(WEBRTC_PYTHON) or not os.path.isfile(WEBRTC_SERVICE):
            raise EchoCancellationError("WebRTC environment or service not found")
        self.process = subprocess.Popen(
            [WEBRTC_PYTHON, "-u", WEBRTC_SERVICE],
            cwd=WEBRTC_DIR,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise EchoCancellationError("WebRTC service stopped during startup")
            try:
                connection = socket.create_connection(("127.0.0.1", 9890), timeout=0.2)
                connection.settimeout(0.2)
                if self._read_exact(connection, 4) != b"AEC2":
                    connection.close()
                    raise EchoCancellationError("Invalid WebRTC signature")
                connection.settimeout(0.2)
                self.connection = connection
                return
            except OSError:
                time.sleep(0.1)
        raise EchoCancellationError("WebRTC service did not respond within ten seconds")

    def process_chunk(self, chunk, captured_at, whisper_chunk):
        if self.connection is None or self.process is None or self.process.poll() is not None:
            raise EchoCancellationError("WebRTC service unavailable")
        near = np.ascontiguousarray(chunk.reshape(-1), dtype="<f4")
        if near.size != FRAME_SAMPLES:
            raise EchoCancellationError("Microphone block size incompatible with WebRTC")
        far = self.reference.for_capture(captured_at)
        whisper_near = np.ascontiguousarray(whisper_chunk.reshape(-1), dtype="<f4")
        process_started = time.monotonic()
        try:
            self.connection.sendall(near.tobytes() + whisper_near.tobytes() + far.tobytes())
            response = self._read_exact(self.connection, FRAME_BYTES * 2)
            cleaned = np.frombuffer(response[:FRAME_BYTES], dtype="<f4").copy()
            whisper_cleaned = np.frombuffer(response[FRAME_BYTES:], dtype="<f4").copy()
        except (OSError, EchoCancellationError) as exc:
            raise EchoCancellationError(f"WebRTC communication failed: {exc}") from exc
        if np.any(far):
            self.diagnostic_frames += 1
            self.diagnostic_near_power += float(np.mean(near * near))
            self.diagnostic_far_power += float(np.mean(far * far))
            self.diagnostic_clean_power += float(np.mean(cleaned * cleaned))
            self.diagnostic_process_seconds += time.monotonic() - process_started
            if time.monotonic() - self.diagnostic_started >= 2.0:
                count = self.diagnostic_frames
                logging.info(
                    "WebRTC AEC3 during playback: microphone %.2f%% RMS, reference %.2f%% RMS, "
                    "output %.2f%% RMS, processing %.1f ms/20 ms block (%s blocks).",
                    100 * (self.diagnostic_near_power / count) ** 0.5,
                    100 * (self.diagnostic_far_power / count) ** 0.5,
                    100 * (self.diagnostic_clean_power / count) ** 0.5,
                    1000 * self.diagnostic_process_seconds / count,
                    count,
                )
                self.diagnostic_started = time.monotonic()
                self.diagnostic_frames = 0
                self.diagnostic_near_power = 0.0
                self.diagnostic_far_power = 0.0
                self.diagnostic_clean_power = 0.0
                self.diagnostic_process_seconds = 0.0
        else:
            self.diagnostic_started = time.monotonic()
            self.diagnostic_frames = 0
            self.diagnostic_near_power = 0.0
            self.diagnostic_far_power = 0.0
            self.diagnostic_clean_power = 0.0
            self.diagnostic_process_seconds = 0.0
        return cleaned.reshape(chunk.shape), whisper_cleaned.reshape(whisper_chunk.shape)

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.process = None
