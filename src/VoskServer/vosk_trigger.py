import json
import os
import sys
import threading
import time
import sounddevice as sd
from vosk import KaldiRecognizer, Model as VoskModel

# Model path inside its dedicated directory.
with open(os.path.join(os.path.dirname(__file__), "model.json"), encoding="utf-8-sig") as config_file:
    model_config = json.load(config_file)
VOSK_MODEL_PATH = os.environ.get("MIO_VOSK_MODEL") or model_config["model_path"]
if not os.path.isabs(VOSK_MODEL_PATH):
    VOSK_MODEL_PATH = os.path.join(os.path.dirname(__file__), VOSK_MODEL_PATH)

if not os.path.exists(VOSK_MODEL_PATH):
    print(f"[ERROR VOSK] Model not found in: {VOSK_MODEL_PATH}")
    sys.exit(1)

vosk_model = VoskModel(VOSK_MODEL_PATH)

class VoskTriggerListener:
    def __init__(self, mic_index=1, target_words=None):
        self.mic_index = mic_index
        self.target_words = target_words or ["stop", "mio", "be quiet"]
        self.stop_requested = False
        self._running = False

    def start(self):
        self._running = True
        thread = threading.Thread(target=self._listen_loop, daemon=True)
        thread.start()

    def reset_stop(self):
        self.stop_requested = False

    def _listen_loop(self):
        rec = KaldiRecognizer(vosk_model, 16000)
        chunk_size = 1600  # 100 ms

        try:
            with sd.InputStream(
                device=self.mic_index,
                samplerate=16000,
                channels=1,
                dtype="int16",
            ) as stream:
                while self._running:
                    data, _ = stream.read(chunk_size)
                    
                    # Fast detection from partial results (< 80 ms).
                    partial = json.loads(rec.PartialResult())
                    p_text = partial.get("partial", "").lower()
                    if any(word in p_text for word in self.target_words):
                        print(f"\n[INSTANT VOSK INTERRUPTION] Trigger : '{p_text}'")
                        self.stop_requested = True
                        sd.stop()
                        rec.Reset()
                        time.sleep(0.2)
                        continue

                    # Final validation.
                    if rec.AcceptWaveform(bytes(data)):
                        result = json.loads(rec.Result())
                        text = result.get("text", "").lower()
                        if any(word in text for word in self.target_words):
                            print(f"\n[INTERRUPTION VOSK] Trigger : '{text}'")
                            self.stop_requested = True
                            sd.stop()

        except Exception as e:
            print(f"[ERROR MODULE VOSK] {e}")
