"""Isolated Silero ONNX voice detector for Mio (20 ms, 16 kHz PCM)."""

import json
import os
import socket
import struct
import sys
from pathlib import Path

import numpy as np
EXECUTION = json.loads(Path(__file__).with_name("execution.json").read_text(encoding="utf-8"))
os.environ["CUDA_VISIBLE_DEVICES"] = EXECUTION["gpu_uuid"]
import onnxruntime as ort
ort.preload_dlls(directory="")


HOST = "127.0.0.1"
PORT = 9891
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 4
MODEL_FRAME_SAMPLES = 480  # Recommended window for this openWakeWord Silero model.
MODEL_PATH = Path(os.environ.get('MIO_SILERO_MODEL', str(Path(__file__).parent / 'silero_vad.onnx')))


def read_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part:
            return None
        data.extend(part)
    return bytes(data)


class Detector:
    def __init__(self):
        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = max(1, int(EXECUTION["cpu_threads"]))
        options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        options.add_session_config_entry("session.inter_op.allow_spinning", "0")
        self.session = ort.InferenceSession(
            str(MODEL_PATH), sess_options=options, providers=[("CUDAExecutionProvider", {"device_id": 0, "arena_extend_strategy": "kSameAsRequested"})]
        )
        if "CUDAExecutionProvider" not in self.session.get_providers():
            raise RuntimeError("Silero CUDA requested but unavailable")
        print("Silero VAD CUDA ready on " + EXECUTION["gpu_uuid"], flush=True)
        self.reset()

    def reset(self):
        self.h = np.zeros((2, 1, 64), dtype=np.float32)
        self.c = np.zeros((2, 1, 64), dtype=np.float32)
        self.pending = np.empty(0, dtype=np.float32)
        self.last_score = 0.0

    def predict(self, frame):
        # Preserve every sample: 20 ms transport frames become contiguous
        # 30 ms inference windows. Reuse the latest score between windows.
        self.pending = np.concatenate((self.pending, frame))
        while self.pending.size >= MODEL_FRAME_SAMPLES:
            window = self.pending[:MODEL_FRAME_SAMPLES]
            self.pending = self.pending[MODEL_FRAME_SAMPLES:]
            self.last_score = self._predict_window(window)
        return self.last_score

    def _predict_window(self, frame):
        probability, self.h, self.c = self.session.run(
            None,
            {
                "input": frame.reshape(1, MODEL_FRAME_SAMPLES),
                "h": self.h,
                "c": self.c,
                "sr": np.array(16000, dtype=np.int64),
            },
        )
        score = float(probability[0][0])
        if not np.isfinite(score):
            raise RuntimeError("Invalid speech probability")
        return score


def main():
    detector = Detector()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, PORT))
        listener.listen(1)
        with listener.accept()[0] as connection:
            connection.sendall(b"VAD1")
            while True:
                command = read_exact(connection, 1)
                if command is None:
                    return
                if command == b"R":
                    detector.reset()
                    connection.sendall(b"R")
                elif command == b"P":
                    payload = read_exact(connection, FRAME_BYTES)
                    if payload is None:
                        return
                    frame = np.frombuffer(payload, dtype="<f4")
                    connection.sendall(struct.pack("<f", detector.predict(frame)))
                else:
                    raise RuntimeError("Unknown VAD command")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Silero VAD stopped: {exc}", file=sys.stderr, flush=True)
        raise
