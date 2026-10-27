"""Local WebRTC AEC3 worker. Only this environment imports pywebrtc_audio.

AEC2: 20 ms at 16 kHz. Vosk near, Whisper near, shared far-end reference.
Two independent AEC states return Vosk clean then Whisper clean samples.
This process exits when MainApp closes its connection.
"""

import socket
import sys

import numpy as np
from pywebrtc_audio import EchoCanceller


HOST = "127.0.0.1"
PORT = 9890
FRAME_SAMPLES = 320
FRAME_BYTES = FRAME_SAMPLES * 4


def read_exact(connection, count):
    data = bytearray()
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part:
            return None
        data.extend(part)
    return bytes(data)


def main():
    processor = EchoCanceller(sample_rate=16000, num_channels=1, stream_delay_ms=0)
    whisper_processor = EchoCanceller(sample_rate=16000, num_channels=1, stream_delay_ms=0)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOST, PORT))
        listener.listen(1)
        print("WebRTC AEC3 ready on 127.0.0.1:9890", flush=True)
        with listener.accept()[0] as connection:
            connection.sendall(b"AEC2")
            while True:
                packet = read_exact(connection, FRAME_BYTES * 3)
                if packet is None:
                    return
                near = np.frombuffer(packet, dtype="<f4", count=FRAME_SAMPLES).copy()
                whisper_near = np.frombuffer(packet, dtype="<f4", count=FRAME_SAMPLES, offset=FRAME_BYTES).copy()
                far = np.frombuffer(packet, dtype="<f4", count=FRAME_SAMPLES, offset=FRAME_BYTES * 2).copy()
                cleaned = np.asarray(processor.process(near, far), dtype="<f4")
                whisper_cleaned = np.asarray(whisper_processor.process(whisper_near, far), dtype="<f4")
                if (cleaned.size != FRAME_SAMPLES or not np.isfinite(cleaned).all()
                        or whisper_cleaned.size != FRAME_SAMPLES or not np.isfinite(whisper_cleaned).all()):
                    raise RuntimeError("WebRTC AEC3 returned an invalid audio block")
                connection.sendall(cleaned.tobytes() + whisper_cleaned.tobytes())


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"WebRTC AEC3 stopped: {exc}", file=sys.stderr, flush=True)
        raise
