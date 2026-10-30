"""Read audio frames from MainApp and emit recognized interruption commands.

Vosk owns its model and Python environment, while MainApp remains the only
process that opens the microphone. The pipe protocol is a 4-byte little-endian
frame length followed by mono PCM16 audio; control lengths 1 and 2 reset
recognition and report playback active or inactive, while 0 only resets.
"""

from __future__ import annotations

import json
import os
import math
import re
import struct
import sys
import time
import unicodedata
from collections import deque
from difflib import SequenceMatcher
from pathlib import Path

from vosk import KaldiRecognizer, Model as VoskModel


HERE = Path(__file__).resolve().parent
MODEL_CONFIG = json.loads((HERE / 'model.json').read_text(encoding='utf-8-sig'))
MODEL_PATH = Path(os.environ.get('MIO_VOSK_MODEL') or MODEL_CONFIG['model_path'])
if not MODEL_PATH.is_absolute():
    MODEL_PATH = (HERE / MODEL_PATH).resolve()
TRIGGER_DIR = HERE.parent / "MainApp" / "trigger"
TRIGGER_GROUPS = (
    ("wake_up", "wake"),
    ("mise_en_sommeil", "pause"),
    ("couper_la_parole", "stop"),
    ("interrompre_mode_femme", "flirt"),
    ("fin_mode_enfant", "child_exit"),
)
SAMPLE_RATE = 16000
MAX_FRAME_BYTES = 64_000
TRIGGER_COOLDOWN_SECONDS = 1.0
# Trigger filters (input level is normalized: 1.0 means full scale).
# Raise these slightly to make commands stricter; lower them if normal speech
# is rejected. The level uses a rolling 500 ms window from the amplified VB input.
TRIGGER_FILTERS = json.loads((HERE / "seuils.json").read_text(encoding="utf-8-sig"))
MIN_TRIGGER_RMS = float(TRIGGER_FILTERS["min_trigger_rms"])
PAUSE_MIN_TRIGGER_RMS = float(TRIGGER_FILTERS["pause_min_trigger_rms"])
MIN_TRIGGER_ACOUSTIC_CONFIDENCE = float(TRIGGER_FILTERS["min_acoustic_confidence_percent"])
MIN_TRIGGER_TEXT_MATCH = float(TRIGGER_FILTERS["min_text_match"])
WAKE_MIN_TEXT_MATCH = float(TRIGGER_FILTERS["wake_min_text_match"])
RMS_WINDOW_FRAMES = 5
MULTIWORD_PARTIAL_STABLE_FRAMES = int(TRIGGER_FILTERS["multiword_partial_stable_frames"])
SINGLE_WORD_PARTIAL_STABLE_FRAMES = int(TRIGGER_FILTERS["single_word_partial_stable_frames"])
PLAYBACK_INTERRUPT_STABLE_FRAMES = int(TRIGGER_FILTERS["playback_interrupt_stable_frames"])
PLAYBACK_INTERRUPT_MIN_RMS = float(TRIGGER_FILTERS["playback_interrupt_min_rms"])
PLAYBACK_INTERRUPT_MIN_CONFIDENCE = float(TRIGGER_FILTERS["playback_interrupt_min_acoustic_confidence_percent"])
if not (0 < MIN_TRIGGER_RMS <= 1 and 0 < PAUSE_MIN_TRIGGER_RMS <= 1
        and 0 <= MIN_TRIGGER_ACOUSTIC_CONFIDENCE <= 100
        and 0 < PLAYBACK_INTERRUPT_MIN_RMS <= 1
        and 0 < MIN_TRIGGER_TEXT_MATCH <= 1
        and 0 < WAKE_MIN_TEXT_MATCH <= 1
        and min(MULTIWORD_PARTIAL_STABLE_FRAMES, SINGLE_WORD_PARTIAL_STABLE_FRAMES,
                PLAYBACK_INTERRUPT_STABLE_FRAMES) >= 1
        and 0 <= PLAYBACK_INTERRUPT_MIN_CONFIDENCE <= 100):
    raise ValueError("Invalid Vosk thresholds in seuils.json")


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    without_marks = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", without_marks).strip()


def load_trigger_phrases() -> tuple[str, ...]:
    """Load editable trigger phrases from MainApp's four command folders."""
    phrases = []
    for folder, category in TRIGGER_GROUPS:
        trigger_file = TRIGGER_DIR / folder / "phrases.txt"
        if not trigger_file.is_file():
            raise FileNotFoundError(f"Trigger list not found: {trigger_file}")
        for line in trigger_file.read_text(encoding="utf-8-sig").splitlines():
            phrase = line.split("#", maxsplit=1)[0].strip()
            if phrase:
                normalized = normalize(phrase)
                if normalized:
                    phrases.append((normalized, category))
    for phrase in json.loads(os.environ.get('MIO_PROVIDER_COMMANDS', '[]')):
        normalized = normalize(phrase)
        if normalized and all(normalized != existing for existing, _ in phrases):
            phrases.append((normalized, 'provider'))
    if not phrases:
        raise ValueError(f"No trigger configured in {TRIGGER_DIR}")
    return tuple(phrases)


NORMALIZED_TRIGGERS = load_trigger_phrases()


def read_exact(stream, size: int) -> bytes | None:
    data = bytearray()
    while len(data) < size:
        part = stream.read(size - len(data))
        if not part:
            return None
        data.extend(part)
    return bytes(data)


def emit(event_type: str, **values: object) -> None:
    message = {"type": event_type, **values}
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def best_trigger_match(text: str) -> tuple[str, str, float, int] | None:
    """Find the closest command at the sample end, not inside a sentence."""
    words = normalize(text).split()
    best_match = None
    best_score = 0.0
    for phrase, category in NORMALIZED_TRIGGERS:
        phrase_words = phrase.split()
        # Compare only a short suffix window. This tolerates a dropped or
        # misheard first word while preventing a trigger embedded in a sentence.
        min_words = max(1, len(phrase_words) - 2)
        max_words = min(len(words), len(phrase_words) + 1)
        for count in range(min_words, max_words + 1):
            candidate = " ".join(words[-count:])
            score = SequenceMatcher(None, candidate, phrase).ratio()
            if score > best_score:
                best_match = (category, phrase, score, count)
                best_score = score
    return best_match


def matching_trigger(text: str) -> tuple[str, str, float] | None:
    """Accept the closest command when its text resemblance clears the threshold."""
    if TRIGGER_FILTERS.get("exact_command_only", False):
        normalized = normalize(text)
        words_without_unknown = [word for word in normalized.split() if word != "unk"]
        interruption_text = " ".join(words_without_unknown)
        for phrase, category in NORMALIZED_TRIGGERS:
            if normalized == phrase:
                return category, phrase, 1.0
            # Loudspeaker bleed can add [unk] before or after an interruption.
            # Ignore only these markers; all other recognized words still block it.
            if category == "stop" and interruption_text == phrase:
                return category, phrase, 1.0
        # Sleep and wake require the complete configured command, without unknown words.
        return None
    best_match = best_trigger_match(text)
    if not best_match:
        return None

    category, phrase, score, _matched_word_count = best_match
    threshold = MIN_TRIGGER_TEXT_MATCH
    if category in ("wake", "provider"):
        # While Mio sleeps, ordinary speech must not wake her just because its
        # last word resembles part of a wake phrase. Require at least two
        # recognized words and a near-exact match to the configured phrase.
        if len(normalize(text).split()) < 2:
            return None
        threshold = max(threshold, 0.90)

    if score >= threshold:
        return best_match[:3]
    return None


def matching_playback_interruption(text: str) -> tuple[str, str, float] | None:
    """Find an exact stop at the end of a mixed loudspeaker hypothesis."""
    words = normalize(text).split()
    while words and words[-1] == "unk":
        words.pop()
    for phrase, category in NORMALIZED_TRIGGERS:
        if category != "stop":
            continue
        phrase_words = phrase.split()
        if len(words) >= len(phrase_words) and words[-len(phrase_words):] == phrase_words:
            return category, phrase, 1.0
    return None


def describe_sample(text: str, result: dict) -> dict[str, object]:
    """Return readable lexical-match and Vosk word-confidence diagnostics."""
    best_match = best_trigger_match(text)
    best_phrase = best_match[1] if best_match else ""
    best_score = best_match[2] if best_match else 0.0
    best_word_count = best_match[3] if best_match else 1

    word_results = result.get("result") or []
    confidences = [
        float(word["conf"])
        for word in word_results[-best_word_count:]
        if isinstance(word, dict) and word.get("conf") is not None
    ]
    acoustic_confidence = (
        round(sum(confidences) / len(confidences) * 100)
        if confidences
        else None
    )
    return {
        "candidate": best_phrase,
        "match_percent": round(best_score * 100),
        "acoustic_percent": acoustic_confidence,
    }


def pcm_rms(pcm: bytes) -> float:
    """Return normalized RMS amplitude for little-endian PCM16 audio."""
    sample_count = len(pcm) // 2
    if not sample_count:
        return 0.0
    squared_total = sum(
        sample * sample for (sample,) in struct.iter_unpack("<h", pcm[: sample_count * 2])
    )
    return math.sqrt(squared_total / sample_count) / 32768.0


def recent_rms_level(levels: deque[float]) -> float:
    """Combine recent frame RMS values over the configured rolling window."""
    if not levels:
        return 0.0
    return math.sqrt(sum(level * level for level in levels) / len(levels))


def main() -> int:
    if not MODEL_PATH.is_dir():
        print(f"[Vosk] Vosk model not found: {MODEL_PATH}", file=sys.stderr, flush=True)
        return 1

    print(
        "[Vosk] Active commands: "
        + ", ".join(phrase for phrase, _category in NORMALIZED_TRIGGERS),
        file=sys.stderr,
        flush=True,
    )
    print(
        f"[Vosk] Command thresholds: RMS >= {MIN_TRIGGER_RMS:.3f} "
        f"({MIN_TRIGGER_RMS * 100:.1f}%) ; text similarity >= "
        f"{MIN_TRIGGER_TEXT_MATCH * 100:.0f}% ; final confidence >= "
        f"{MIN_TRIGGER_ACOUSTIC_CONFIDENCE}%",
        file=sys.stderr,
        flush=True,
    )
    model = VoskModel(str(MODEL_PATH))
    # A small command grammar keeps the command model focused on wake/stop
    # phrases instead of decoding unrestricted sentences while Mio is idle.
    command_grammar = json.dumps(
        [phrase for phrase, category in NORMALIZED_TRIGGERS
         if category != 'provider' or all(model.vosk_model_find_word(word) >= 0
                                          for word in phrase.split())] + ["[unk]"],
        ensure_ascii=False,
    )
    recognizer = KaldiRecognizer(model, SAMPLE_RATE, command_grammar)
    recognizer.SetWords(True)
    recognizer.SetPartialWords(True)
    last_trigger_at = 0.0
    last_partial_text = ""
    last_partial_command = ""
    stable_partial_frames = 0
    recent_levels: deque[float] = deque(maxlen=RMS_WINDOW_FRAMES)
    utterance_peak_level = 0.0
    assistant_playing = False
    emit("ready")

    while True:
        header = read_exact(sys.stdin.buffer, 4)
        if header is None:
            return 0

        frame_size = struct.unpack("<I", header)[0]
        if frame_size in (0, 1, 2):
            if frame_size:
                assistant_playing = frame_size == 1
            recognizer.Reset()
            last_partial_text = ""
            last_partial_command = ""
            stable_partial_frames = 0
            recent_levels.clear()
            utterance_peak_level = 0.0
            continue
        if frame_size > MAX_FRAME_BYTES or frame_size % 2:
            print(f"[Vosk] Invalid audio block size: {frame_size}", file=sys.stderr, flush=True)
            return 2

        pcm = read_exact(sys.stdin.buffer, frame_size)
        if pcm is None:
            return 0
        recent_levels.append(pcm_rms(pcm))
        level = recent_rms_level(recent_levels)
        level_percent = round(level * 100, 2)
        # Keep the strongest recent speech level until Vosk finalizes. Its
        # endpoint arrives after silence, so the instantaneous RMS alone is 0.
        utterance_peak_level = max(utterance_peak_level, level)

        # Check stable fuzzy matches in partial results for fast interruption;
        # finalized results remain a fallback when the live hypothesis missed it.
        if recognizer.AcceptWaveform(pcm):
            result = json.loads(recognizer.Result())
            recognized_text = result.get("text", "")
        else:
            partial_result = json.loads(recognizer.PartialResult())
            partial_text = partial_result.get("partial", "")
            partial_match = matching_trigger(partial_text)
            if assistant_playing and (not partial_match or partial_match[0] not in {"stop", "child_exit"}):
                partial_match = matching_playback_interruption(partial_text)
            if assistant_playing and partial_match and partial_match[0] == "pause":
                partial_match = None
            partial_command = partial_match[1] if partial_match else None
            partial_diagnostics = describe_sample(
                partial_text,
                {"result": partial_result.get("partial_result", [])},
            )
            # Require repeated stable hypotheses before acting on a partial.
            if partial_command:
                if partial_command == last_partial_command:
                    stable_partial_frames += 1
                else:
                    last_partial_command = partial_command
                    stable_partial_frames = 1
            else:
                last_partial_command = ""
                stable_partial_frames = 0

            now = time.monotonic()
            # Partial stop can cut playback after the configured number
            # of stable 100 ms hypotheses; wake remains final-only by default.
            required_stable_frames = (
                SINGLE_WORD_PARTIAL_STABLE_FRAMES
                if partial_match and partial_match[0] in {"stop", "pause"}
                else MULTIWORD_PARTIAL_STABLE_FRAMES
            )
            if assistant_playing and partial_match:
                if partial_match[0] == "stop":
                    required_stable_frames = PLAYBACK_INTERRUPT_STABLE_FRAMES
            partial_allowed = (
                TRIGGER_FILTERS.get("allow_partial_triggers", False)
                or (assistant_playing and partial_match and partial_match[0] == "stop")
            )
            partial_confidence = partial_diagnostics.get("acoustic_percent")
            required_confidence = MIN_TRIGGER_ACOUSTIC_CONFIDENCE
            if assistant_playing and partial_match:
                if partial_match[0] == "stop":
                    required_confidence = PLAYBACK_INTERRUPT_MIN_CONFIDENCE
            if (
                partial_allowed
                and partial_command
                and stable_partial_frames >= required_stable_frames
                and partial_confidence is not None
                and partial_confidence >= required_confidence
                and now - last_trigger_at >= TRIGGER_COOLDOWN_SECONDS
            ):
                decision_level = max(level, utterance_peak_level)
                required_rms = (
                    PLAYBACK_INTERRUPT_MIN_RMS if assistant_playing and partial_match[0] == "stop"
                    else PAUSE_MIN_TRIGGER_RMS if partial_match[0] == "pause"
                    else MIN_TRIGGER_RMS
                )
                if decision_level >= required_rms:
                    emit(
                        "trigger",
                        text=partial_text,
                        command=partial_command,
                        kind=partial_match[0],
                        source="partial",
                        level_rms_percent=round(decision_level * 100, 2),
                        **partial_diagnostics,
                    )
                    last_trigger_at = now
                    recognizer.Reset()
                    last_partial_text = ""
                    last_partial_command = ""
                    stable_partial_frames = 0
                    recent_levels.clear()
                    utterance_peak_level = 0.0
                    continue
                emit(
                    "transcript",
                    text=partial_text,
                    final=False,
                    level_rms_percent=level_percent,
                    blocked_reason="volume too low to validate a command",
                    **partial_diagnostics,
                )

            if partial_text and partial_text != last_partial_text:
                last_partial_text = partial_text
                emit(
                    "transcript",
                    text=partial_text,
                    final=False,
                    **partial_diagnostics,
                )
            continue

        last_partial_text = ""
        last_partial_command = ""
        stable_partial_frames = 0
        now = time.monotonic()
        if recognized_text:
            trigger_match = matching_trigger(recognized_text)
            if assistant_playing and (not trigger_match or trigger_match[0] != "stop"):
                playback_stop = matching_playback_interruption(recognized_text)
                if playback_stop is not None:
                    trigger_match = playback_stop
            ignored_sleep_during_playback = bool(
                assistant_playing and trigger_match and trigger_match[0] == "pause"
            )
            if ignored_sleep_during_playback:
                trigger_match = None
            diagnostics = describe_sample(recognized_text, result)
            acoustic_percent = diagnostics.get("acoustic_percent")
            decision_level = max(level, utterance_peak_level)
            decision_level_percent = round(decision_level * 100, 2)
            required_rms = (
                PLAYBACK_INTERRUPT_MIN_RMS
                if assistant_playing and trigger_match and trigger_match[0] == "stop"
                else PAUSE_MIN_TRIGGER_RMS
                if trigger_match and trigger_match[0] == "pause"
                else MIN_TRIGGER_RMS
            )
            level_ok = decision_level >= required_rms
            required_confidence = MIN_TRIGGER_ACOUSTIC_CONFIDENCE
            if assistant_playing and trigger_match:
                if trigger_match[0] == "stop":
                    required_confidence = PLAYBACK_INTERRUPT_MIN_CONFIDENCE
            confidence_ok = (
                acoustic_percent is not None
                and acoustic_percent >= required_confidence
            )
            if (
                trigger_match
                and level_ok
                and confidence_ok
                and now - last_trigger_at >= TRIGGER_COOLDOWN_SECONDS
            ):
                kind, command, _score = trigger_match
                emit(
                    "trigger",
                    text=recognized_text,
                    command=command,
                    kind=kind,
                    source="final",
                    level_rms_percent=decision_level_percent,
                    **diagnostics,
                )
                last_trigger_at = now
                recognizer.Reset()
                recent_levels.clear()
            elif trigger_match:
                reasons = []
                if not level_ok:
                    reasons.append("volume too low")
                if not confidence_ok:
                    reasons.append("acoustic confidence too low")
                emit(
                    "transcript",
                    text=recognized_text,
                    final=True,
                    level_rms_percent=decision_level_percent,
                    blocked_reason=" and ".join(reasons),
                    **diagnostics,
                )
            else:
                emit(
                    "transcript",
                    text=recognized_text,
                    final=True,
                    level_rms_percent=decision_level_percent,
                    blocked_reason=("voice sleep command disabled during playback"
                                    if ignored_sleep_during_playback else ""),
                    **diagnostics,
                )
        recent_levels.clear()
        utterance_peak_level = 0.0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[Vosk] Command detector error: {exc}", file=sys.stderr, flush=True)
        raise
