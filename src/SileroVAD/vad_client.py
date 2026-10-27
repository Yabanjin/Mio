"""Small IPC client; Silero and ONNX Runtime live only in SileroVAD/env."""

import os
import socket
import struct
import subprocess
import time

import numpy as np


VAD_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "SileroVAD"))
VAD_PYTHON = os.environ.get('MIO_PYTHON') or __import__('sys').executable
VAD_SERVICE = os.path.join(VAD_DIR, "vad_service.py")


class VoiceActivityError(RuntimeError):
    pass


class VoiceActivityClient:
    def __init__(self):
        self.process = None
        self.connection = None

    @staticmethod
    def _read_exact(connection, count):
        data = bytearray()
        while len(data) < count:
            part = connection.recv(count - len(data))
            if not part:
                raise VoiceActivityError("Silero VAD service disconnected")
            data.extend(part)
        return bytes(data)

    def start(self):
        if not os.path.isfile(VAD_PYTHON) or not os.path.isfile(VAD_SERVICE):
            raise VoiceActivityError("Environnement Silero VAD incomplet")
        self.process = subprocess.Popen(
            [VAD_PYTHON, "-u", VAD_SERVICE],
            cwd=VAD_DIR,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise VoiceActivityError("Silero VAD service stopped during startup")
            try:
                connection = socket.create_connection(("127.0.0.1", 9891), timeout=0.2)
                connection.settimeout(0.5)
                if self._read_exact(connection, 4) != b"VAD1":
                    connection.close()
                    raise VoiceActivityError("Invalid Silero VAD signature")
                self.connection = connection
                return
            except OSError:
                time.sleep(0.1)
        raise VoiceActivityError("Silero VAD service did not respond within ten seconds")

    def _exchange(self, request, reply_bytes):
        if self.connection is None or self.process is None or self.process.poll() is not None:
            raise VoiceActivityError("Silero VAD service unavailable")
        try:
            self.connection.sendall(request)
            return self._read_exact(self.connection, reply_bytes)
        except OSError as exc:
            raise VoiceActivityError(f"Silero VAD communication failed: {exc}") from exc

    def reset(self):
        if self._exchange(b"R", 1) != b"R":
            raise VoiceActivityError("Invalid Silero VAD reset")

    def probability(self, chunk):
        frame = np.ascontiguousarray(chunk.reshape(-1), dtype="<f4")
        if frame.size != 320:
            raise VoiceActivityError("Audio block incompatible with Silero VAD")
        score = struct.unpack("<f", self._exchange(b"P" + frame.tobytes(), 4))[0]
        if not np.isfinite(score):
            raise VoiceActivityError("Invalid Silero VAD probability")
        return score

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
