"""One microphone stream, shared by continuous Vosk and utterance capture."""

import logging
import queue
import threading
import time
from collections import deque

import sounddevice as sd
import numpy as np


class MicrophoneInput:
    def __init__(self, device, sample_rate, block_samples, queue_seconds, on_chunk, on_error,
                 preroll_seconds=2.0, process_chunk=None,
                 gate_rms_threshold=0.0, gate_hold_seconds=0.0,
                 whisper_gate_rms_threshold=0.003):
        self.device = device
        self.sample_rate = sample_rate
        self.block_samples = block_samples
        self.on_chunk = on_chunk
        self.on_error = on_error
        self.process_chunk = process_chunk
        self.gate_rms_threshold = gate_rms_threshold
        self.gate_hold_seconds = gate_hold_seconds
        self.gate_open_until = 0.0
        self.whisper_gate_rms_threshold = whisper_gate_rms_threshold
        self.whisper_gate_open_until = 0.0
        self.dropped_frames = 0
        self.frames = queue.Queue(maxsize=max(1, int(queue_seconds * sample_rate / block_samples)))
        self.history = deque(maxlen=max(1, int((preroll_seconds + queue_seconds) * sample_rate / block_samples)))
        self.history_lock = threading.Lock()
        self.preroll_seconds = preroll_seconds
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.error = ""
        self.audio_stats_started = time.monotonic()
        self.audio_stats = np.zeros((3, 4), dtype=np.float64)
        self.audio_stats_frames = 0
        self.audio_stats_eligible = 0

    def _log_audio_levels(self, raw, gated, cleaned, eligible):
        for row, audio in zip(self.audio_stats, (raw, gated, cleaned)):
            row[0] += float(np.sum(audio * audio))
            row[1] = max(row[1], float(np.max(np.abs(audio))))
            row[2] += int(np.count_nonzero(np.abs(audio) >= 0.999))
            row[3] += audio.size
        self.audio_stats_frames += 1
        self.audio_stats_eligible += int(eligible)
        if time.monotonic() - self.audio_stats_started < 5.0:
            return
        labels = []
        for name, row in zip(("VB Cable", "after Whisper gate", "after WebRTC Whisper"), self.audio_stats):
            labels.append("%s RMS %.2f%% / pic %.2f%% / plafond %.2f%%" % (
                name, 100 * np.sqrt(row[0] / row[3]), 100 * row[1], 100 * row[2] / row[3]))
        logging.info("Audio diagnostics: %s; capture-eligible blocks %s/%s.",
                     " ; ".join(labels), self.audio_stats_eligible, self.audio_stats_frames)
        self.audio_stats.fill(0)
        self.audio_stats_frames = self.audio_stats_eligible = 0
        self.audio_stats_started = time.monotonic()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="Mio-Microphone")
        self.thread.start()

    def clear(self):
        with self.history_lock:
            self.history.clear()
        while True:
            try:
                self.frames.get_nowait()
            except queue.Empty:
                return

    def read(self, timeout=0.1):
        return self.frames.get(timeout=timeout)

    def before(self, detected_at, generation, not_before):
        """Return contiguous eligible history before this detection, oldest first."""
        lower = max(not_before, detected_at - self.preroll_seconds)
        with self.history_lock:
            preceding = []
            for timestamp, chunk, tag in reversed(self.history):
                if timestamp >= detected_at:
                    continue
                if timestamp < lower or tag != generation:
                    break
                preceding.append(chunk)
        preceding.reverse()
        return preceding

    def recover_playback_tail(self, start, end, generation):
        """Make only the final playback tail eligible for the next pre-buffer."""
        with self.history_lock:
            self.history = deque(
                ((timestamp, chunk, generation if start <= timestamp <= end and tag is None else tag)
                 for timestamp, chunk, tag in self.history), maxlen=self.history.maxlen)

    def _run(self):
        fault_reported = False
        while not self.closed.is_set():
            try:
                with sd.InputStream(device=self.device, samplerate=self.sample_rate,
                                    channels=1, dtype="float32", blocksize=self.block_samples) as stream:
                    self.error = ""
                    self.ready.set()
                    logging.info("Actual microphone stream latency: %.1f ms.", stream.latency * 1000)
                    while not self.closed.is_set():
                        chunk, overflow = stream.read(self.block_samples)
                        if overflow:
                            raise RuntimeError("Blocks lost in the microphone buffer")
                        captured_at = time.monotonic()
                        raw_chunk = chunk.copy()
                        # Independent gates/AEC states: preserve the Vosk branch.
                        whisper_chunk = chunk
                        rms = float(np.sqrt(np.mean(np.square(chunk))))
                        if self.whisper_gate_rms_threshold > 0:
                            if rms >= self.whisper_gate_rms_threshold:
                                self.whisper_gate_open_until = captured_at + self.gate_hold_seconds
                            elif captured_at > self.whisper_gate_open_until:
                                whisper_chunk = np.zeros_like(chunk)
                        if self.gate_rms_threshold > 0:
                            if rms >= self.gate_rms_threshold:
                                self.gate_open_until = captured_at + self.gate_hold_seconds
                            elif captured_at > self.gate_open_until:
                                chunk = np.zeros_like(chunk)
                        gated_whisper_chunk = whisper_chunk.copy()
                        if self.process_chunk is not None:
                            chunk, whisper_chunk = self.process_chunk(chunk, captured_at, whisper_chunk)
                        generation = self.on_chunk(chunk, captured_at)
                        self._log_audio_levels(raw_chunk, gated_whisper_chunk, whisper_chunk, generation is not None)
                        frame = (captured_at, whisper_chunk.copy(), generation)
                        with self.history_lock:
                            self.history.append(frame)
                        if generation is None:
                            # Sleep/playback history remains stamped as ineligible;
                            # it must not saturate the speech assembler's queue.
                            continue
                        try:
                            self.frames.put_nowait(frame)
                        except queue.Full:
                            self.dropped_frames += 1
                            if self.dropped_frames % 50 == 1:
                                logging.warning("Audio queue full: %s block(s) lost before assembly.",
                                                self.dropped_frames)
                            try:
                                self.frames.get_nowait()
                            except queue.Empty:
                                pass
                            self.frames.put_nowait(frame)
                        fault_reported = False
            except Exception as exc:
                self.error = str(exc)
                self.ready.clear()
                self.clear()
                if not fault_reported:
                    self.on_error(exc)
                    fault_reported = True
                self.closed.wait(1.0)
        self.ready.clear()
