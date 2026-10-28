import io
import json
import logging
import os
import queue
import re
import sys
import struct
import subprocess
import threading
import time
import unicodedata
import uuid
from collections import deque

os.system("chcp 65001 > nul")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import numpy as np
import requests
import sounddevice as sd
import soundfile as sf
from scipy.signal import resample_poly
from module_paths import configure_module_paths
configure_module_paths()

from face_presence import FacePresence
from microphone_input import MicrophoneInput
from runtime_status import RuntimeStatus
from response_language import ResponseLanguageGuard
from aec_client import EchoClient, EchoCancellationError, PlaybackReference
from vad_client import VoiceActivityClient, VoiceActivityError
from vector_memory_client import (recall, memory_instruction, capture_async,
                                  start_memory_worker, cancel_memory, close_memory)
from llm_request_config import generation_options, conversation_options
from llm_scheduler import LLM_SCHEDULER
from reply_preview import ReplyPreview
from reply_quality import repetition_reason
from http_sessions import http_session
from current_time_context import with_current_time
from speaker_identity import SPEAKER_RECOGNIZER
from typed_chat import author_identity
from progressive_stt import ProgressiveTranscriber
from cancellable_work import CancellableWork, TurnCancelled
import chat_events

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", stream=sys.stdout
)
chat_events.install_error_handler()
# Two blank lines separate complete console records, including tracebacks.
for console_handler in logging.getLogger().handlers:
    if isinstance(console_handler, logging.StreamHandler) and not isinstance(console_handler, logging.FileHandler):
        console_handler.terminator = "\n\n\n"
VOSK_DIAGNOSTIC_LOG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "logs", "vosk-live.log")
os.makedirs(os.path.dirname(VOSK_DIAGNOSTIC_LOG), exist_ok=True)
vosk_diagnostic_logger = logging.getLogger("vosk.diagnostic")
vosk_diagnostic_logger.setLevel(logging.INFO)
vosk_diagnostic_logger.propagate = False
if not vosk_diagnostic_logger.handlers:
    vosk_file_handler = logging.FileHandler(
        VOSK_DIAGNOSTIC_LOG, encoding="utf-8"
    )
    vosk_file_handler.setFormatter(
        logging.Formatter("%(asctime)s [VOSK] %(message)s")
    )
    vosk_diagnostic_logger.addHandler(vosk_file_handler)

# ============================================================
# 1) SERVICE AND DEVICE CONFIGURATION
# Configure ports, audio device indices, and the TTS reference path here.
# ============================================================
# Endpoints
with open(os.path.join(os.path.dirname(__file__), 'config', 'connexion.json'), encoding='utf-8') as settings_file:
    CONNECTION = json.load(settings_file)
with open(os.path.join(os.path.dirname(__file__), '..', 'LM Studio', 'mio-load.json'), encoding='utf-8') as settings_file:
    MODEL_SETTINGS = json.load(settings_file)
with open(os.path.join(os.path.dirname(__file__), 'config', 'prononciation.json'), encoding='utf-8') as settings_file:
    PRONUNCIATION = json.load(settings_file)
from component_connections import load_connections
COMPONENTS = load_connections()
URL_STT = COMPONENTS['transcription']['url']
URL_LLM = COMPONENTS['llm']['url']
URL_PIPER_TTS = COMPONENTS['french_voice']['url']
URL_MELO_TTS = COMPONENTS['multilingual_voice']['url']
URL_VC_CONFIG = COMPONENTS['voice_changer']['configuration_url']
URL_VC_CONVERT_CHUNK = COMPONENTS['voice_changer']['conversion_url']

# None uses the default Windows audio output device.
TTS_DEVICE_INDEX = CONNECTION['output_device']
SAMPLE_RATE = 16000
AUDIO_BLOCK_SAMPLES = 1280  # 80 ms blocks at 16 kHz.
LLM_MODEL_NAME = COMPONENTS['llm']['model']
WHISPER_ALLOWED_LANGUAGES = {
    "fr": "fr",
    "french": "fr",
    "en": "en",
    "english": "en",
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    # Turbo validates the decoded text; mixed is allowed for FR/EN/JA.
    "mixed": "mixed",
}
FEMALE_PROMPT_BLOCKED_UNTIL = 0.0

# Vosk runs in its own process using the shared environment. MainApp sends it
# VB Cable audio blocks already amplified by MicroBoost, without opening another input.
VOSK_DIR = os.path.join(os.path.dirname(__file__), "..", "VoskServer")
VOSK_PYTHON = os.environ.get('MIO_PYTHON', sys.executable)
VOSK_PIPE_SCRIPT = os.path.join(VOSK_DIR, "vosk_pipe_listener.py")
VOSK_FRAMES_PER_WRITE = 5  # 5 blocks of 20 ms = 100 ms for Vosk.

llm_generating = False
conversation_pending = threading.Event()
tts_generating = False

# ============================================================
# 2) INTERRUPTIONS DURING A MIO TURN
# Vosk and the face-presence timeout may interrupt Mio. Independent capture
# waits during TTS playback but continues during silent STT and LLM processing.
# ============================================================
VOSK_FRAME_SAMPLES = SAMPLE_RATE * 20 // 1000
WAKE_HAI_LEADING_SILENCE_SECONDS = 1.0
VOICE_CHANGER_OUTPUT_PREROLL_SECONDS = 0.15

# Agent DVR owns the camera; this client only reads its local image. Only a
# recognized face authorizes sending an audio segment to Whisper Turbo.
MAINAPP_DIR = os.path.dirname(__file__)
TRIGGER_DIR = os.path.join(MAINAPP_DIR, "trigger")
AUTO_RESPONSE_DIR = os.path.join(MAINAPP_DIR, "reponse_auto")


def resolve_microphone_device():
    """Select MicroBoost's VB Cable output without relying on a changing index."""
    config_path = os.path.join(MAINAPP_DIR, "config", "peripheriques_audio.json")
    with open(config_path, encoding="utf-8") as config_file:
        config = json.load(config_file)
    prefix = config["microphone_name_prefix"]
    hostapi_name = config["microphone_hostapi"]
    matches = [
        index for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
        and device["name"].startswith(prefix)
        and sd.query_hostapis(device["hostapi"])["name"] == hostapi_name
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"MicroBoost input missing or ambiguous: {prefix!r} ({hostapi_name}), "
            f"{len(matches)} correspondance(s)"
        )
    logging.info("Mio microphone input: %s (index %s, %s).",
                 sd.query_devices(matches[0])["name"], matches[0], hostapi_name)
    return matches[0]


def load_json_config(path, description):
    with open(path, "r", encoding="utf-8-sig") as config_file:
        value = json.load(config_file)
    if not isinstance(value, dict):
        raise ValueError(f"The {description} file must contain a JSON object: {path}")
    return value


def load_auto_responses():
    """Load editable fixed TTS replies once at MainApp startup."""
    response_files = {
        "wake": os.path.join(AUTO_RESPONSE_DIR, "bienvenue", "phrases.json"),
        "arrival_child": os.path.join(AUTO_RESPONSE_DIR, "arrivee_enfant", "phrases.json"),
        "arrival_woman": os.path.join(AUTO_RESPONSE_DIR, "arrivee_femme", "phrases.json"),
        "error": os.path.join(AUTO_RESPONSE_DIR, "erreur", "phrases.json"),
        "stop_femme": os.path.join(AUTO_RESPONSE_DIR, "annulation_mode", "phrases.json"),
        "stop": os.path.join(AUTO_RESPONSE_DIR, "stop", "reponse.json"),
        "pause": os.path.join(AUTO_RESPONSE_DIR, "pause", "reponse.json"),
    }
    responses = {}
    for key, path in response_files.items():
        responses[key] = load_json_config(path, f"automatic response {key}")
    return responses


AUTO_RESPONSES = load_auto_responses()
RESPONSE_LANGUAGE_GUARD = ResponseLanguageGuard()
JAPANESE_UNITS = load_json_config(
    os.path.join(MAINAPP_DIR, "config", "unites_japonaises.json"), "Japanese units",
)
RUNTIME_CONFIG = load_json_config(
    os.path.join(MAINAPP_DIR, "config", "fonctionnement.json"), "runtime settings",
)
FACE_GRACE_SECONDS = float(RUNTIME_CONFIG["face_grace_seconds"])
UNKNOWN_FACE_CONFIRM_SECONDS = float(RUNTIME_CONFIG["unknown_face_confirm_seconds"])
VOICE_IDLE_SECONDS = float(RUNTIME_CONFIG["voice_idle_seconds"])
WHISPER_MIN_TOKEN_CONFIDENCE = float(RUNTIME_CONFIG["whisper_min_token_confidence"])
WHISPER_JA_MIN_TOKEN_CONFIDENCE = float(RUNTIME_CONFIG["whisper_ja_min_token_confidence"])
WHISPER_EN_MIN_TOKEN_CONFIDENCE = float(RUNTIME_CONFIG["whisper_en_min_token_confidence"])
if not 0 <= WHISPER_EN_MIN_TOKEN_CONFIDENCE <= 1:
    raise ValueError("Invalid English confidence threshold")
if not 0 <= WHISPER_JA_MIN_TOKEN_CONFIDENCE <= 1:
    raise ValueError("Invalid Japanese confidence threshold")
if UNKNOWN_FACE_CONFIRM_SECONDS <= 0 or FACE_GRACE_SECONDS <= 0 or VOICE_IDLE_SECONDS <= 0 or not 0 <= WHISPER_MIN_TOKEN_CONFIDENCE <= 1:
    raise ValueError("Invalid Whisper timings or threshold in fonctionnement.json")
FACE_PRESENCE = FacePresence(interval_seconds=float(RUNTIME_CONFIG["face_poll_seconds"]),
                             agent_snapshot_url=COMPONENTS['camera']['snapshot_url'],
                             face_recognition_url=COMPONENTS['camera']['recognition_url'],
                             min_confidence=float(CONNECTION['face_min_confidence']))
PROMPT_CONDITIONS = load_json_config(
    os.path.join(MAINAPP_DIR, "config", "conditions_prompt.json"),
    "prompt selection conditions",
)
RECOGNITION_CONTEXT = load_json_config(
    os.path.join(MAINAPP_DIR, "config", "contexte_reconnaissance.json"),
    "recognition context",
)
FEMALE_PROMPT_BLOCK_SECONDS = int(PROMPT_CONDITIONS["femme_block_seconds"])
with open(os.path.join(TRIGGER_DIR, "mots_a_retirer.txt"), encoding="utf-8-sig") as words_file:
    WAKE_WORDS_TO_REMOVE = tuple(
        line.strip()
        for line in words_file
        if line.strip() and not line.lstrip().startswith("#")
    )


def load_trigger_phrases():
    """Load every editable voice trigger once when MainApp starts."""
    folders = {
        "wake": "wake_up",
        "pause": "mise_en_sommeil",
        "stop": "couper_la_parole",
        "flirt": "interrompre_mode_femme",
        "child_exit": "fin_mode_enfant",
    }
    loaded = {}
    for category, folder in folders.items():
        path = os.path.join(TRIGGER_DIR, folder, "phrases.txt")
        with open(path, "r", encoding="utf-8-sig") as phrases_file:
            loaded[category] = tuple(
                line.split("#", maxsplit=1)[0].strip()
                for line in phrases_file
                if line.split("#", maxsplit=1)[0].strip()
            )
        if not loaded[category]:
            raise ValueError(f"No {category} trigger configured: {path}")
    return loaded


TRIGGER_PHRASES = load_trigger_phrases()
chat_events.emit("commands", groups=[
    dict(label="Wake", phrases=TRIGGER_PHRASES["wake"],
         action="Wake Mio if the face is authorized."),
    dict(label="Stop", phrases=TRIGGER_PHRASES["stop"],
         action="Cancel the exchange and stop the reply; Mio stays awake."),
    dict(label="Sleep", phrases=TRIGGER_PHRASES["pause"],
         action="Cancel the exchange, say goodbye, then sleep; ignored during speech."),
    dict(label="Stop flirting", phrases=TRIGGER_PHRASES["flirt"],
         action=f"Interrupt and block Adult mode for {FEMALE_PROMPT_BLOCK_SECONDS / 60:g} minutes."),
    dict(label="Exit Child mode", phrases=TRIGGER_PHRASES["child_exit"],
         action="Stop the reply and clear the persistent mode; a recognized child still takes priority."),
])

# ============================================================
# 3) MIO LANGUAGES AND BEHAVIOR
# Input accepts French, Japanese, and English; English is the default reply language.
# ============================================================
# Clean text only after transcription. Active commands are configured in
# MainApp\trigger and loaded at startup.
chat_histories = {mode: deque(maxlen=8) for mode in ('Normal', 'Adult', 'Child')}
stop_requested = False
mio_paused = False
conversation_active = False
interrupt_generation = 0  # Immediately invalidate any ongoing audio or LLM response.
is_speaking = False
tts_queue = queue.Queue()
prepared_tts = queue.Queue(maxsize=1)
prepared_available = threading.Event()
prepare_slot = threading.BoundedSemaphore(1)
playback_reserved = False
utterance_queue = queue.Queue(maxsize=int(RUNTIME_CONFIG["utterance_queue_size"]))
capture_thread = None
progressive_stt = None
state_lock = threading.RLock()
microphone = None
playback_reference = PlaybackReference()
aec_client = None
vad_client = None
shutdown_event = threading.Event()
runtime_ready = threading.Event()
stt_processing = False
face_bad_since = None
face_unknown_since = None
last_trusted_face_names = ()
face_role_first_seen = {}
face_role_last_seen = {}
face_roles_announced = set()
child_mode_latched = False
child_latch_rearm_pending = False
child_absent_since = None
female_turn_generation = None
active_reply_mode = None
active_reply_generation = None
LLM_WORK = CancellableWork("Mio-LLM-HTTP")
TTS_WORK = CancellableWork("Mio-TTS-HTTP")
RVC_WORK = CancellableWork("Mio-RVC-HTTP", capacity=1)
_rvc_config = None
_rvc_config_at = 0.0
voice_wait_since = 0.0
capture_resume_after = 0.0
last_sent_wav_at = 0.0
playback_recovery_start = None
user_phrase_active = False
pause_reply_generation = None
READY_FILE = os.path.join(MAINAPP_DIR, "..", "..", "data", "logs", "mainapp-ready.json")


def enqueue_face_wake_response(mode="Normal"):
    """Queue the editable welcome selected by the visible family member."""
    global female_turn_generation, active_reply_mode, active_reply_generation
    if mode == "Child" and "Child" in face_roles_announced:
        return  # Already greeted in this child session, even across sleep/wake.
    active_reply_mode, active_reply_generation = mode, interrupt_generation
    response_key = {"Child": "arrival_child", "Adult": "arrival_woman"}.get(mode, "wake")
    if mode == "Adult":
        female_turn_generation = interrupt_generation
    for segment in AUTO_RESPONSES[response_key]["segments"]:
        tts_queue.put((segment["text"], segment.get("language", "Japanese"), interrupt_generation))


def enqueue_japanese_error_response(generation=None):
    """Tell the user that Mio could not produce a usable spoken answer."""
    with state_lock:
        generation = interrupt_generation if generation is None else generation
        if not turn_is_current(generation):
            return
        if microphone is not None:
            microphone.clear()
        response = AUTO_RESPONSES["error"]
        tts_queue.put((response["text"], response.get("language", "Japanese"), generation, True))


def visible_face_roles(face_names):
    """Map registered face labels to the two special prompt roles."""
    normalized_faces = {
        re.sub(r"[^a-z0-9]+", "", _normalize_for_language_match(name))
        for name in face_names
    }
    child_labels = {
        re.sub(r"[^a-z0-9]+", "", _normalize_for_language_match(label))
        for label in PROMPT_CONDITIONS.get("Child", [])
    }
    woman_labels = {
        re.sub(r"[^a-z0-9]+", "", _normalize_for_language_match(label))
        for label in PROMPT_CONDITIONS.get("Adult", [])
    }
    roles = set()
    if normalized_faces & child_labels:
        roles.add("Child")
    if normalized_faces & woman_labels:
        roles.add("Adult")
    return roles


def child_face_confirmed(face_names, now=None):
    """Require continuous facial presence before selecting the child mode."""
    if "Child" not in visible_face_roles(face_names):
        return False
    since = face_role_first_seen.get("Child")
    if since is None:
        return False
    if now is None:
        now = time.monotonic()
    return now - since >= float(PROMPT_CONDITIONS["child_face_confirm_seconds"])


def select_prompt_mode(face_names, speaker_identity):
    """Select the child, woman, or default prompt from verified context."""
    global FEMALE_PROMPT_BLOCKED_UNTIL, child_mode_latched
    visible_roles = visible_face_roles(face_names)
    speaker_role = str((speaker_identity or {}).get("role") or "").casefold()
    speaker_prompt = str((speaker_identity or {}).get("prompt") or "").casefold()
    child_roles = {str(value).casefold() for value in PROMPT_CONDITIONS.get("child_roles", [])}
    woman_roles = {str(value).casefold() for value in PROMPT_CONDITIONS.get("woman_roles", [])}
    child_prompt_names = {str(value).casefold() for value in PROMPT_CONDITIONS.get("child_prompt_names", [])}
    woman_prompt_names = {str(value).casefold() for value in PROMPT_CONDITIONS.get("woman_prompt_names", [])}
    child_present = (
        speaker_role in child_roles
        or speaker_prompt in child_prompt_names
        or child_face_confirmed(face_names)
    )
    woman_present = (
        speaker_role in woman_roles
        or speaker_prompt in woman_prompt_names
        or "Adult" in visible_roles
    )
    if child_present and not child_latch_rearm_pending:
        child_mode_latched = True
    if child_present or child_mode_latched:
        return "Child"
    woman_since = face_role_first_seen.get("Adult")
    now = time.monotonic()
    woman_confirmed = (woman_since is not None and
                       now - woman_since >= float(PROMPT_CONDITIONS["woman_face_confirm_seconds"]))
    if woman_present and woman_confirmed and now >= FEMALE_PROMPT_BLOCKED_UNTIL:
        return "Adult"
    return "Normal"


def recognition_names(raw_names, *, voice=False):
    """Format only reported names; never infer a speaker from a prompt or face."""
    if not isinstance(raw_names, (list, tuple)):
        return []
    aliases = RECOGNITION_CONTEXT["aliases"]
    ignored = {name.casefold() for name in RECOGNITION_CONTEXT["ignored_names"]}
    if voice:
        ignored.update(name.casefold() for name in RECOGNITION_CONTEXT["self_voice_names"])
    names = []
    for raw in raw_names:
        if not isinstance(raw, str):
            continue
        raw = raw.strip()
        if not raw or raw.casefold() in ignored:
            continue
        name = aliases.get(raw.casefold(), raw)
        if name not in names:
            names.append(name)
    return names


def recognition_sentence(names, template):
    if not names:
        return ""
    people = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    return template.format(names=people)


def speaker_context_instruction(speaker_identity):
    identity = speaker_identity or {}
    if identity.get('source') == 'text':
        names = recognition_names(identity.get('names', []))
        return recognition_sentence(names, RECOGNITION_CONTEXT.get('text_template', "{names} is writing to you in the chat."))
    names = recognition_names(identity.get("names", []), voice=True)
    return recognition_sentence(names, RECOGNITION_CONTEXT["voice_template"])


def camera_context_instruction(state):
    if not state.camera_ready:
        return ""
    since = dict(state.recognized_since)
    delays = RECOGNITION_CONTEXT.get("face_context_confirm_seconds", {})
    confirmed = []
    for raw in state.names:
        names = recognition_names([raw])
        if not names:
            continue
        delay = max(0.0, float(delays.get(names[0], 0)))
        # Count only time covered by successful camera observations, not stale time.
        if state.last_success - since.get(raw, state.last_success) >= delay:
            confirmed.append(raw)
    names = recognition_names(confirmed)
    return recognition_sentence(names, RECOGNITION_CONTEXT["face_template"])


def load_prompts():
    """Load every editable prompt file once when MainApp starts."""
    prompt_dir = os.path.join(MAINAPP_DIR, "prompt")
    with open(os.path.join(prompt_dir, "Common.txt"), "r", encoding="utf-8-sig") as prompt_file:
        common = prompt_file.read().strip()
    if not common:
        raise ValueError("The common prompt is empty")
    prompts = {}
    for mode in ("Child", "Adult", "Normal"):
        prompt_path = os.path.join(prompt_dir, f"{mode}.txt")
        with open(prompt_path, "r", encoding="utf-8-sig") as prompt_file:
            prompts[mode] = prompt_file.read().strip()
        if not prompts[mode]:
            raise ValueError(f"The {mode} prompt is empty: {prompt_path}")
        prompts[mode] = common + "\n\n" + prompts[mode]
    logging.info("Prompts loaded into memory: %s.", ", ".join(prompts))
    return prompts


PROMPTS = load_prompts()
with open(os.path.join(MAINAPP_DIR, "prompt", "Rewrite.txt"), encoding="utf-8-sig") as prompt_file:
    REPETITION_REPAIR = prompt_file.read().strip()


vosk_process = None
vosk_ready = threading.Event()
vosk_write_lock = threading.Lock()
vosk_pending_audio = []
vosk_capture_suspended = False
vosk_assistant_was_active = False


# ============================================================
# 4) TEXT CLEANUP AND TTS LANGUAGE SELECTION
# ============================================================
def clean_text_for_tts(text: str) -> str:
    text = re.sub(r"\*.*?\*", "", text)
    text = re.sub(
        r"[^a-zA-Z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ ,.!?'’\u3040-\u30ff\u4e00-\u9faf]", " ", text
    )
    return re.sub(r"\s+", " ", text).strip()


def normalize_reply_names(text: str) -> str:
    """Apply only the pronunciations selected in customization."""
    for source, target in PRONUNCIATION['replacements'].items():
        if source:
            text = re.sub(r'(?<!\w)' + re.escape(source) + r'(?!\w)', lambda _: target, text, flags=re.I)
    return text


def clean_wake_words(text: str) -> str:
    cleaned = text
    for word in sorted(WAKE_WORDS_TO_REMOVE, key=len, reverse=True):
        pattern = re.compile(
            r"(?<!\w)" + re.escape(word) + r"(?!\w)", re.IGNORECASE
        )
        cleaned = pattern.sub("", cleaned)
    return cleaned.lstrip(" ,.!?").strip()


def _normalize_for_language_match(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_control_phrase(text: str) -> str:
    """Normalize a short voice command for exact, predictable matching."""
    normalized = _normalize_for_language_match(text)
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def is_pause_request(text: str) -> bool:
    """Recognize only explicit pause commands, not ordinary mentions of pausing."""
    normalized = normalize_control_phrase(text)
    return normalized in {normalize_control_phrase(item) for item in TRIGGER_PHRASES["pause"]}


def is_stop_only_command(text: str) -> bool:
    """Keep repeated stop words and short STT noise out of the LLM input."""
    tokens = normalize_control_phrase(text).split()
    if not tokens:
        return False
    stop_tokens = {
        token
        for phrase in TRIGGER_PHRASES["stop"]
        for token in normalize_control_phrase(phrase).split()
    }
    allowed_tokens = stop_tokens | {
        token
        for phrase in TRIGGER_PHRASES["wake"]
        for token in normalize_control_phrase(phrase).split()
    }
    if all(token in allowed_tokens for token in tokens):
        return True
    stop_count = sum(token in stop_tokens for token in tokens)
    return len(tokens) <= 8 and stop_count >= 2 and stop_count / len(tokens) >= 0.75


def is_mio_wake_request(text: str) -> bool:
    """Match a configured explicit wake phrase."""
    normalized = normalize_control_phrase(text)
    return normalized in {normalize_control_phrase(item) for item in TRIGGER_PHRASES["wake"]}


def is_short_mio_wake(text: str) -> bool:
    """Recognize the short spoken wake names when Whisper is the active path."""
    normalized = normalize_control_phrase(text)
    return normalized in {
        normalize_control_phrase(item)
        for item in TRIGGER_PHRASES["wake"]
        if len(normalize_control_phrase(item).split()) <= 2
    }


LANGUAGE_REQUEST_PATTERNS = {
    "French": [
        r"(?:フランス語|仏語)で(?:お願いします|お願い|おねがい|ください)",
        r"\b(?:parle(?:s|r)?|reponds?|repondre|dis|answer|speak|respond)\b.{0,48}\b(?:(?:en|in)\s+)?(?:francais|french)\b",
        r"(?:フランス語|仏語).{0,12}(?:で|を).{0,12}(?:話して|答えて|喋って|しゃべって)",
    ],
    "Japanese": [
        r"(?:日本語|にほんご)で(?:お願いします|お願い|おねがい|ください)",
        r"\b(?:parle(?:s|r)?|reponds?|repondre|dis|answer|speak|respond)\b.{0,48}\b(?:(?:en|in)\s+)?(?:japonais|japanese)\b",
        r"(?:日本語|にほんご).{0,12}(?:話して|話せ|答えて|喋って|喋れ|しゃべって|しゃべれ)",
    ],
    "English": [
        r"英語で(?:お願いします|お願い|おねがい|ください)",
        r"\b(?:parle(?:s|r)?|reponds?|repondre|dis|answer|speak|respond)\b.{0,48}\b(?:(?:en|in)\s+)?(?:anglais|english)\b",
        r"英語.{0,12}(?:で|を).{0,12}(?:話して|答えて|喋って|しゃべって)",
    ],
}


def requested_reply_language(text: str):
    normalized = _normalize_for_language_match(text)
    for language, patterns in LANGUAGE_REQUEST_PATTERNS.items():
        if any(re.search(pattern, normalized) for pattern in patterns):
            return language
    return None


def _french_number_under_100(value: int) -> str:
    units = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix", "onze", "douze", "treize", "quatorze", "quinze", "seize"]
    if value < len(units):
        return units[value]
    if value < 20:
        return "dix-" + units[value - 10]
    if value < 70:
        tens, remainder = divmod(value, 10)
        names = {2: "vingt", 3: "trente", 4: "quarante", 5: "cinquante", 6: "soixante"}
        return names[tens] if remainder == 0 else names[tens] + (" et un" if remainder == 1 else "-" + units[remainder])
    if value < 80:
        remainder = value - 60
        return "soixante" + (" et onze" if remainder == 11 else "-" + _french_number_under_100(remainder))
    if value < 90:
        remainder = value - 80
        return "quatre-vingts" if remainder == 0 else "quatre-vingt-" + _french_number_under_100(remainder)
    return "quatre-vingt-" + _french_number_under_100(value - 80)


def _french_integer_words(value: int) -> str:
    if value < 100:
        return _french_number_under_100(value)
    if value < 1000:
        hundreds, remainder = divmod(value, 100)
        prefix = "cent" if hundreds == 1 else _french_number_under_100(hundreds) + " cent"
        if remainder:
            return prefix + " " + _french_integer_words(remainder)
        return prefix if hundreds == 1 else prefix + "s"
    for scale, singular, plural in ((1_000_000_000, "milliard", "milliards"), (1_000_000, "million", "millions"), (1000, "mille", "mille")):
        if value >= scale:
            quotient, remainder = divmod(value, scale)
            if scale == 1000:
                prefix = "mille" if quotient == 1 else _french_integer_words(quotient) + " mille"
            else:
                prefix = _french_integer_words(quotient) + " " + (singular if quotient == 1 else plural)
            return prefix if remainder == 0 else prefix + " " + _french_integer_words(remainder)
    return " ".join(_french_number_under_100(int(digit)) for digit in str(value))


def _english_integer_words(value: int) -> str:
    small = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]
    if value < 20:
        return small[value]
    if value < 100:
        quotient, remainder = divmod(value, 10)
        return tens[quotient] + ("-" + small[remainder] if remainder else "")
    if value < 1000:
        quotient, remainder = divmod(value, 100)
        prefix = small[quotient] + " hundred"
        return prefix if remainder == 0 else prefix + " " + _english_integer_words(remainder)
    for scale, name in ((1_000_000_000, "billion"), (1_000_000, "million"), (1000, "thousand")):
        if value >= scale:
            quotient, remainder = divmod(value, scale)
            prefix = _english_integer_words(quotient) + " " + name
            return prefix if remainder == 0 else prefix + " " + _english_integer_words(remainder)
    return " ".join(small[int(digit)] for digit in str(value))


def _japanese_integer_words(value: int) -> str:
    digits = "〇一二三四五六七八九"

    def group_words(group: int) -> str:
        if group == 0:
            return ""
        parts = []
        for power, unit in ((1000, "千"), (100, "百"), (10, "十")):
            count, group = divmod(group, power)
            if count:
                special = {(3000, "千"): "三千", (8000, "千"): "八千", (300, "百"): "三百", (600, "百"): "六百", (800, "百"): "八百"}
                parts.append(special.get((count * power, unit), ("" if count == 1 else digits[count]) + unit))
        if group:
            parts.append(digits[group])
        return "".join(parts)

    if value == 0:
        return "〇"
    if value >= 10**16:
        return "".join(digits[int(digit)] for digit in str(value))
    parts = []
    for scale, unit in ((10**12, "兆"), (10**8, "億"), (10**4, "万"), (1, "")):
        count, value = divmod(value, scale)
        if count:
            parts.append(group_words(count) + unit)
    return "".join(parts)


def spell_out_numbers(text: str, language: str) -> str:
    """Convert numerals to words for the selected TTS language."""
    def replace_number(match):
        value = match.group(0)
        separator = "," if "," in value else "." if "." in value else None
        integer_text, _, fraction = value.replace(",", ".").partition(".")
        number = int(integer_text)
        if language == "Japanese":
            result = _japanese_integer_words(number)
            return result + ("点" + "".join("〇一二三四五六七八九"[int(digit)] for digit in fraction) if separator else "")
        converter = _english_integer_words if language == "English" else _french_integer_words
        result = converter(number)
        if separator:
            decimal_word = "point" if language == "English" else "virgule"
            result += " " + decimal_word + " " + " ".join(converter(int(digit)) for digit in fraction)
        return result

    return re.sub(r"\d+(?:[.,]\d+)?", replace_number, text)


def split_tts_by_language(text: str, default_language: str):
    """Separate Japanese spans from other text to choose the voice engine."""
    cleaned = clean_text_for_tts(text)
    if not cleaned:
        return []
    tokens = re.findall(
        r"\d+(?:[.,]\d+)?|[\u3040-\u30ff\u3400-\u9fff]+|[A-Za-zàâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ’']+|[^A-Za-z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ’'\u3040-\u30ff\u3400-\u9fff]+",
        cleaned,
    )
    pieces = []

    def adjacent_japanese(index, direction):
        cursor = index + direction
        while 0 <= cursor < len(tokens):
            neighbor = tokens[cursor]
            if re.search(r"[\u3040-\u30ff\u3400-\u9fff]", neighbor):
                return True
            if neighbor.casefold() in JAPANESE_UNITS or re.fullmatch(r"\d+(?:[.,]\d+)?", neighbor):
                cursor += direction
                continue
            if re.search(r"[A-Za-z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]", neighbor):
                return False
            cursor += direction
        return False

    for index, token in enumerate(tokens):
        if re.search(r"[\u3040-\u30ff]", token):
            language = "Japanese"
        elif re.search(r"[\u3400-\u9fff]", token):
            language = "Japanese"
        elif (re.fullmatch(r"\d+(?:[.,]\d+)?", token) or token.casefold() in JAPANESE_UNITS) and (
            adjacent_japanese(index, -1) or adjacent_japanese(index, 1)
        ):
            language = "Japanese"
            token = JAPANESE_UNITS.get(token.casefold(), token)
        elif re.search(r"[A-Za-z0-9àâäéèêëîïôöùûüçÀÂÄÉÈÊËÎÏÔÖÙÛÜÇ]", token):
            language = "Latin"  # Keep Latin spans separate even when the request is Japanese.
        else:
            language = pieces[-1][1] if pieces else default_language
        if pieces and pieces[-1][1] == language:
            pieces[-1] = (pieces[-1][0] + token, language)
        else:
            pieces.append((token, language))
    resolved = []
    for piece, lang in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if lang == "Latin":
            lang = (RESPONSE_LANGUAGE_GUARD.latin_language(piece, default_language)
                    if any(c.isalpha() for c in piece) else default_language)
        resolved.append((spell_out_numbers(piece, lang), lang))
    return resolved


# Piper UPMC/Jessica handles French; native MeloTTS handles Japanese and English.

def clear_tts_queue():
    while not tts_queue.empty():
        try:
            tts_queue.get_nowait()
            tts_queue.task_done()
        except queue.Empty:
            break
    while True:
        try:
            prepared_tts.get_nowait()
            prepared_tts.task_done()
            prepare_slot.release()
        except queue.Empty:
            break


def voice_pipeline_busy():
    return is_speaking or tts_generating or playback_reserved or not prepared_tts.empty()


def publish_chat_state():
    names = FACE_PRESENCE.snapshot().names
    child = child_mode_latched or child_face_confirmed(names)
    now = time.monotonic()
    woman_since = face_role_first_seen.get("Adult")
    woman = (now >= FEMALE_PROMPT_BLOCKED_UNTIL and (
        (active_reply_mode == "Adult" and active_reply_generation == interrupt_generation)
        or ("Adult" in visible_face_roles(names) and woman_since is not None
            and now - woman_since >= float(PROMPT_CONDITIONS["woman_face_confirm_seconds"]))
    ))
    chat_events.state(conversation_active and not mio_paused, interrupt_generation,
                      ready=runtime_ready.is_set(),
                      child_mode=child, family_mode="Child" if child else "Adult" if woman else "Normal")


def chat_names(identity=None):
    # Display all detected names; this list is never sent back to speaker identification.
    detected = list((identity or {}).get('names', []))
    detected.extend(FACE_PRESENCE.snapshot().names)
    aliases = {str(key).casefold(): value for key, value in RECOGNITION_CONTEXT["aliases"].items()}
    names = []
    for name in detected:
        name = str(name).strip()
        if not name or name.casefold() in {'unknown', 'inconnu'}:
            continue
        name = aliases.get(name.casefold(), name)
        if name not in names:
            names.append(name)
    return names


def _read_vosk_events(process):
    """Read JSON status/trigger messages from the isolated Vosk process."""
    try:
        for raw_line in process.stdout:
            try:
                event = json.loads(raw_line.decode("utf-8", errors="replace"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                logging.warning("Vosk message ignored because it is not JSON.")
                continue

            if event.get("type") == "ready":
                vosk_ready.set()
                logging.info("Vosk interruption keyword detection ready.")
                vosk_diagnostic_logger.info(
                    "DETECTOR READY | command list=%s",
                    TRIGGER_DIR,
                )
            elif event.get("type") == "transcript":
                text = event.get("text", "")
                sample_state = "final" if event.get("final", True) else "partial"
                candidate = event.get("candidate", "?")
                match_percent = event.get("match_percent", 0)
                acoustic_percent = event.get("acoustic_percent")
                acoustic_label = (
                    f"{acoustic_percent}%" if acoustic_percent is not None else "n/d"
                )
                level_percent = event.get("level_rms_percent")
                level_label = f"{level_percent}% RMS" if level_percent is not None else "n/d"
                blocked_reason = event.get("blocked_reason")
                action = f"none ({blocked_reason})" if blocked_reason else "none"
                message = (
                    f'SAMPLE {sample_state} | heard="{text}" | candidate="{candidate}" '
                    f"| text match={match_percent}% "
                    f"| acoustic confidence={acoustic_label} | level={level_label} "
                    f"| action={action}"
                )
                vosk_diagnostic_logger.info(message)
                logging.info(message)
            elif event.get("type") == "trigger":
                vosk_trigger_text = event.get("command", event.get("text", ""))
                vosk_trigger_kind = event.get("kind", "interrupt")
                trigger_source = event.get("source", "final")
                trigger_timing = (
                    "during playback (stable hypothesis)"
                    if trigger_source == "partial"
                    else "at the end of the utterance"
                )
                acoustic_percent = event.get("acoustic_percent")
                acoustic_label = (
                    f"{acoustic_percent}%" if acoustic_percent is not None else "n/d"
                )
                level_percent = event.get("level_rms_percent")
                vosk_diagnostic_logger.info(
                    "COMMAND VALIDATED | %s | detection=%s | text match=%s%% "
                    "| acoustic confidence=%s | RMS level=%s%% | transcription=\"%s\"",
                    vosk_trigger_text,
                    trigger_timing,
                    event.get("match_percent", 100),
                    acoustic_label,
                    level_percent if level_percent is not None else "n/d",
                    event.get("text", ""),
                )
                logging.info(
                    "Vosk command detected %s (%s, confidence %s, RMS level %s%%): %s",
                    trigger_timing,
                    vosk_trigger_text,
                    acoustic_label,
                    level_percent if level_percent is not None else "n/d",
                    event.get("text", ""),
                )
                handle_vosk_command(vosk_trigger_kind, vosk_trigger_text, trigger_source)
                if vosk_trigger_kind == "stop":
                    chat_events.emit("command", key='stop-' + str(time.monotonic_ns()),
                                     stage="STOP DETECTED", names=["Vosk"],
                                     text=f'Recognized command: « {vosk_trigger_text} ».')
    except Exception:
        logging.exception("Vosk channel read error.")
    finally:
        vosk_ready.clear()
        if process.poll() is not None:
            logging.error("Vosk detection process stopped.")


def start_vosk_trigger():
    """Start the dedicated Vosk process without opening a second microphone."""
    global vosk_process
    if not os.path.isfile(VOSK_PYTHON) or not os.path.isfile(VOSK_PIPE_SCRIPT):
        logging.warning(
            "Vosk detection disabled: Python or vosk_pipe_listener.py not found in %s.",
            VOSK_DIR,
        )
        return
    try:
        vosk_process = subprocess.Popen(
            [VOSK_PYTHON, "-u", VOSK_PIPE_SCRIPT],
            cwd=VOSK_DIR,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            bufsize=-1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        threading.Thread(
            target=_read_vosk_events,
            args=(vosk_process,),
            daemon=True,
            name="Vosk-Trigger-Events",
        ).start()
        logging.info("Starting Vosk detection in the shared Python environment.")
    except Exception:
        vosk_process = None
        logging.exception("Unable to start Vosk detection.")


def feed_vosk_trigger(chunk, assistant_active):
    """Forward MainApp's captured audio to Vosk in 100 ms PCM frames."""
    global vosk_assistant_was_active, vosk_pending_audio, vosk_capture_suspended
    process = vosk_process
    if process is None or process.poll() is not None or not vosk_ready.is_set():
        return

    with vosk_write_lock:
        suspended = False  # Stop/sleep remain available during capture.
        if assistant_active != vosk_assistant_was_active or suspended != vosk_capture_suspended:
            vosk_pending_audio.clear()
            try:
                # Control frame: reset Vosk and report whether playback is live.
                process.stdin.write(struct.pack("<I", 1 if assistant_active else 2))
                process.stdin.flush()
            except (OSError, ValueError):
                logging.exception("Unable to reset Vosk recognition.")
                vosk_ready.clear()
                return
            vosk_assistant_was_active = assistant_active
            vosk_capture_suspended = suspended

        if suspended:
            return

        vosk_pending_audio.append(chunk.copy())
        if len(vosk_pending_audio) < VOSK_FRAMES_PER_WRITE:
            return

        audio = np.concatenate(vosk_pending_audio, axis=0).reshape(-1)
        vosk_pending_audio.clear()
        pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        try:
            process.stdin.write(struct.pack("<I", len(pcm)) + pcm)
            process.stdin.flush()
        except (OSError, ValueError):
            logging.exception("Unable to send audio to Vosk.")
            vosk_ready.clear()


def turn_is_current(generation):
    """Every async result must belong to the still-authorized conversation."""
    return (
        generation == interrupt_generation and conversation_active
        and not mio_paused and not stop_requested
        and (face_bad_since is None or time.monotonic() - face_bad_since < FACE_GRACE_SECONDS)
    )


def cancel_current_turn(*, preserve_memory=False):
    global playback_recovery_start
    playback_recovery_start = None
    global interrupt_generation, capture_resume_after, pause_reply_generation
    global user_phrase_active, female_turn_generation, active_reply_mode, active_reply_generation
    # Caller holds state_lock. Old HTTP/TTS results remain invalid even after wake.
    cancelled_generation = interrupt_generation
    if progressive_stt is not None:
        progressive_stt.cancel(interrupt_generation)
    interrupt_generation += 1
    user_phrase_active = False
    female_turn_generation = None
    active_reply_mode = active_reply_generation = None
    pause_reply_generation = None
    capture_resume_after = time.monotonic() + float(RUNTIME_CONFIG["post_mio_guard_seconds"])
    playback_reference.clear()
    try:
        sd.stop()
    except Exception:
        logging.exception("Unable to stop the playback device")
    clear_tts_queue()
    while True:
        try:
            pending_buffer, _generation = utterance_queue.get_nowait()
            pending_buffer.close()
        except queue.Empty:
            break
    if microphone is not None:
        microphone.clear()
    publish_chat_state()
    if not shutdown_event.is_set() and not preserve_memory:
        try:
            cancel_memory(cancelled_generation)
        except Exception:
            logging.exception('Unable to record memory cancellation on disk')


def enter_sleep(reason, paused=False):
    global conversation_active, mio_paused, stop_requested
    with state_lock:
        cancel_current_turn(preserve_memory=True)
        conversation_active = False
        mio_paused = paused
        stop_requested = True
        publish_chat_state()
    logging.info("Sleep: %s; buffers cleared, Vosk commands still active.", reason)


def pause_mio():
    global stop_requested, voice_wait_since, pause_reply_generation
    with state_lock:
        if not conversation_active or mio_paused:
            return
        cancel_current_turn(preserve_memory=True)
        stop_requested = False
        voice_wait_since = time.monotonic()
        pause_reply_generation = interrupt_generation
        response = AUTO_RESPONSES["pause"]
        tts_queue.put((response["text"], response.get("language", "Japanese"), interrupt_generation, True))
    logging.info("Pause requested: goodbye before sleep.")


def wake_session():
    global conversation_active, mio_paused, stop_requested, face_bad_since
    global last_trusted_face_names, voice_wait_since
    with state_lock:
        if not runtime_ready.is_set():
            return False
        state = FACE_PRESENCE.snapshot()
        if not state.has_known_person:
            logging.info("Wake refused: no known face without an unknown face in the current image.")
            return False
        if conversation_active and assistant_audio_active():
            return False
        cancel_current_turn(preserve_memory=True)
        stop_requested = False
        mio_paused = False
        conversation_active = True
        publish_chat_state()
        face_bad_since = None
        last_trusted_face_names = state.names
        voice_wait_since = time.monotonic()
        visible_roles = visible_face_roles(state.names)
        for role in visible_roles:
            face_role_first_seen.setdefault(role, voice_wait_since)
            face_role_last_seen[role] = voice_wait_since
        greeting_mode = select_prompt_mode(state.names, None)
        enqueue_face_wake_response(greeting_mode)
        for role in visible_roles:
            if role == "Child" and greeting_mode != "Child":
                continue  # Still confirming presence; no child welcome has occurred.
            if role != "Adult" or greeting_mode in {"Adult", "Child"} or voice_wait_since < FEMALE_PROMPT_BLOCKED_UNTIL:
                face_roles_announced.add(role)
        if greeting_mode == "Child":
            face_roles_announced.add("Child")
        logging.info("Selected wake greeting: %s.", greeting_mode)
    logging.info("Wake accepted: welcome response queued; face and voice timers armed.")
    return True


def request_vosk_interruption(recognized_text, enter_pause=False, reply_stop=False):
    global stop_requested, voice_wait_since
    if enter_pause:
        pause_mio()
    else:
        with state_lock:
            cancel_current_turn()
            stop_requested = False
            voice_wait_since = time.monotonic()
            if reply_stop:
                response = AUTO_RESPONSES["stop"]
                tts_queue.put((response["text"], response.get("language", "Japanese"), interrupt_generation, True))
    logging.info("Vosk command applied: %s.", recognized_text)


def handle_vosk_command(kind, recognized_text, source="final"):
    global FEMALE_PROMPT_BLOCKED_UNTIL, child_mode_latched, child_latch_rearm_pending, child_absent_since
    with state_lock:
        if kind == "child_exit":
            child_mode_latched = False
            child_latch_rearm_pending = True
            child_absent_since = None
            cancel_current_turn()
            publish_chat_state()
            chat_events.emit("command", key='child-exit-' + str(time.monotonic_ns()),
                             stage="EXIT CHILD MODE", names=["Whisper" if source == "whisper" else "Vosk"],
                             text="Persistent mode cleared; a recognized child still takes priority.")
            logging.info("Child mode: persistence cleared by command, present child keeps priority.")
            return True
        if user_phrase_active and not is_speaking and kind not in {"stop", "pause"}:
            logging.info("Vosk command other than stop/sleep ignored during the utterance: %s.", recognized_text)
            return True
        if kind == "pause" and is_speaking:
            logging.info("Sleep command ignored during playback: %s.", recognized_text)
            return True
        if kind == "wake":
            wake_session()
            return True
        if mio_paused or not conversation_active:
            return True
        if kind == "flirt":
            request_vosk_interruption(recognized_text)
            FEMALE_PROMPT_BLOCKED_UNTIL = time.monotonic() + FEMALE_PROMPT_BLOCK_SECONDS
            response = AUTO_RESPONSES["stop_femme"]
            tts_queue.put((response["text"], response.get("language", "Japanese"), interrupt_generation))
            logging.info("Adult mode blocked for %s minutes; next prompt is Normal unless Child takes priority.",
                         FEMALE_PROMPT_BLOCK_SECONDS / 60)
            return True
        request_vosk_interruption(
            recognized_text, enter_pause=kind == "pause" or is_pause_request(recognized_text),
            reply_stop=kind == "stop",
        )
        return True


def on_microphone_chunk(chunk, captured_at):
    global capture_resume_after
    # This path runs in every state, including while requests.post waits for Whisper.
    feed_vosk_trigger(chunk, is_speaking)
    with state_lock:
        # STT and LLM do not stop audio assembly. Actual synthesis/playback does.
        # A queued reply waits for an already-open user phrase to finish.
        output_reserved = voice_pipeline_busy() or (not user_phrase_active and not tts_queue.empty())
        if output_reserved or not turn_is_current(interrupt_generation):
            capture_resume_after = max(capture_resume_after, captured_at + float(RUNTIME_CONFIG["post_mio_guard_seconds"]))
            return None
        return interrupt_generation


def on_microphone_error(exc):
    logging.error("Capture error: %s", exc)
    if isinstance(exc, EchoCancellationError):
        enter_sleep("echo cancellation unavailable")
        shutdown_event.set()
        return
    with state_lock:
        cancel_current_turn()
        enqueue_japanese_error_response()


def process_face_arrival(state, now):
    """Greet a newly present child or woman once, without camera-flicker repeats."""
    global child_absent_since, child_latch_rearm_pending
    roles = visible_face_roles(state.names)
    if "Child" in roles:
        child_absent_since = None
    elif state.camera_ready and not state.unknown_present and child_latch_rearm_pending:
        if child_absent_since is None:
            child_absent_since = now
        if now - child_absent_since >= float(PROMPT_CONDITIONS["face_arrival_reset_seconds"]):
            child_latch_rearm_pending = False
            face_roles_announced.discard("Child")
    else:
        child_absent_since = None
    if not state.camera_ready or state.unknown_present:
        face_role_first_seen.pop("Child", None)
        face_role_first_seen.pop("Adult", None)
        return
    reset_seconds = float(PROMPT_CONDITIONS["face_arrival_reset_seconds"])
    confirm_seconds = float(PROMPT_CONDITIONS["face_arrival_confirm_seconds"])
    for role in ("Child", "Adult"):
        if role in roles:
            face_role_first_seen.setdefault(role, now)
            face_role_last_seen[role] = now
        else:
            face_role_first_seen.pop(role, None)
            if role in face_role_last_seen and now - face_role_last_seen[role] >= reset_seconds:
                face_role_last_seen.pop(role, None)
                if role != "Child" or (not child_mode_latched and not child_latch_rearm_pending):
                    face_roles_announced.discard(role)
    if ((child_mode_latched or child_face_confirmed(state.names, now))
            and active_reply_generation == interrupt_generation
            and active_reply_mode in {"Normal", "Adult"} and assistant_audio_active()):
        cancel_current_turn()
        logging.info("Adult reply interrupted: Child mode confirmed.")
    if not state.has_known_person:
        return
    mode = select_prompt_mode(state.names, None)
    # A latched child mode is already activated (by confirmed face or voice).
    # Its pending welcome must not require a second facial confirmation.
    if mode == "Child" and child_mode_latched and mode not in face_roles_announced:
        if conversation_active:
            if assistant_audio_active() or stt_processing or user_phrase_active or transcription_pending():
                return
            enqueue_face_wake_response(mode)
            face_roles_announced.add(mode)
            logging.info("Child greeting: mode active, conversation invitation queued.")
        else:
            wake_session()
        return
    for role in roles:
        if role != mode:
            if role == "Child":
                continue  # The minute of facial confirmation is still in progress.
            if role == "Adult" and mode == "Normal" and now >= FEMALE_PROMPT_BLOCKED_UNTIL:
                # Waiting for the minute is not an announcement: greet once ready.
                continue
            # No flirt greeting in the presence of a child or while Adult mode is blocked.
            face_roles_announced.add(role)
    if mode not in roles or mode in face_roles_announced:
        return
    if mode == "Child":
        confirm_seconds = float(PROMPT_CONDITIONS["child_face_confirm_seconds"])
    if now - face_role_first_seen[mode] < confirm_seconds:
        return
    if conversation_active:
        if assistant_audio_active() or stt_processing or user_phrase_active or transcription_pending():
            return
        enqueue_face_wake_response(mode)
        face_roles_announced.add(mode)
        logging.info("Face arrival: Mio addresses mode %s.", mode)
    elif wake_session():
        logging.info("Automatic wake from face arrival: %s.", mode)


def conversation_watchdog():
    global face_bad_since, face_unknown_since, last_trusted_face_names, voice_wait_since
    while not shutdown_event.wait(0.05):
        with state_lock:
            if not vosk_ready.is_set():
                logging.error("Vosk unavailable: stopping MainApp, voice commands cannot be guaranteed.")
                runtime_ready.clear()
                enter_sleep("command detector unavailable")
                shutdown_event.set()
                continue
            now = time.monotonic()
            state = FACE_PRESENCE.snapshot()
            process_face_arrival(state, now)
            if not conversation_active:
                face_unknown_since = None
                continue
            if state.camera_ready and state.unknown_present:
                if face_unknown_since is None:
                    face_unknown_since = now
                if now - face_unknown_since >= UNKNOWN_FACE_CONFIRM_SECONDS:
                    enter_sleep("unknown face confirmed after the configured delay")
                    face_unknown_since = None
                    continue
            else:
                face_unknown_since = None
            if state.has_known_person:
                if face_bad_since is not None:
                    logging.info("Face recognized again: grace period cancelled.")
                face_bad_since = None
                last_trusted_face_names = state.names
            else:
                if face_bad_since is None:
                    face_bad_since = now
                    logging.info("Face recognition lost/unknown: %.0f second grace period.",
                                 FACE_GRACE_SECONDS)
                if now - face_bad_since >= FACE_GRACE_SECONDS:
                    enter_sleep("face recognition not restored after the grace period")
                    continue
            # These are listening deadlines: synthesis and transcription do not
            # consume the user's two minutes to start the next utterance.
            if assistant_audio_active() or stt_processing or user_phrase_active or transcription_pending():
                voice_wait_since = now
            elif now - voice_wait_since >= VOICE_IDLE_SECONDS:
                enter_sleep("no voice during the timeout period")


def assistant_audio_active():
    """Report whether Mio's turn is generating, waiting, or playing audio."""
    # Reserve response turns; capture has its own eligibility decision,
    # which permits silent STT and LLM processing.
    return llm_generating or voice_pipeline_busy() or not tts_queue.empty()


def convert_tts_audio_through_voice_changer(
    audio: np.ndarray,
    sample_rate: int,
    item_generation: int,
    leading_silence_seconds: float = 0.0,
):
    """Send TTS audio in chunks to Voice Changer REST at its configured rate."""
    global _rvc_config, _rvc_config_at
    if _rvc_config is None or time.monotonic() - _rvc_config_at >= 2.0:
        with http_session().get(URL_VC_CONFIG, timeout=3) as config_response:
            config_response.raise_for_status()
            _rvc_config = config_response.json()
            _rvc_config_at = time.monotonic()
    config = _rvc_config
    input_rate = int(config.get("input_sample_rate", 0))
    output_rate = int(config.get("output_sample_rate", 0))
    if input_rate != sample_rate or output_rate != sample_rate:
        raise ValueError(
            f"Taux incompatibles : audio TTS={sample_rate} Hz, "
            f"Voice Changer input/output={input_rate}/{output_rate} Hz. "
            "Set Voice Changer to 22050 Hz for Piper Jessica."
        )

    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    source = np.asarray(audio, dtype=np.float32).reshape(-1)
    original_sample_count = source.size
    original_source = source.copy()
    source_peak = float(np.max(np.abs(source))) if source.size else 0.0
    if source_peak > 1e-8:
        input_gain = max(1.0, min(
            float(RUNTIME_CONFIG["rvc_input_max_gain"]),
            float(RUNTIME_CONFIG["rvc_input_target_peak"]) / source_peak,
        ))
        if input_gain > 1.0:
            source = source * input_gain
            logging.info("RVC: TTS input gain x%.2f, peak %.6f -> %.6f; output level retained.",
                         input_gain, source_peak, source_peak * input_gain)
    leading_silence_samples = max(0, round(sample_rate * leading_silence_seconds))
    if leading_silence_samples:
        # Prime RVC's chunk/crossfade state so a short first syllable is not clipped.
        source = np.concatenate(
            (np.zeros(leading_silence_samples, dtype=np.float32), source)
        )
    chunk_samples = sample_rate // 2  # RVC slots use 0.5-second blocks.
    if leading_silence_samples:
        # Flush delayed RVC output after the short wake utterance.
        source = np.pad(source, (0, leading_silence_samples))
    # Voice Changer expects full 0.5-second blocks. The last block of an
    # utterance is often shorter and can break its crossfade.
    padding_samples = (-source.size) % chunk_samples
    if padding_samples:
        source = np.pad(source, (0, padding_samples))
    converted_chunks = []
    for offset in range(0, source.size, chunk_samples):
        if stop_requested or item_generation != interrupt_generation:
            return None, output_rate
        chunk = source[offset : offset + chunk_samples]
        response = http_session().post(
            URL_VC_CONVERT_CHUNK,
            files={
                "waveform": (
                    "waveform.bin",
                    np.asarray(chunk, dtype="<f4").tobytes(),
                    "application/octet-stream",
                )
            },
            # The official client sends Date.now() in milliseconds.
            headers={"x-timestamp": str(int(time.time() * 1000))},
            timeout=30,
        )
        response.raise_for_status()
        if len(response.content) % 4:
            raise ValueError("Invalid Voice Changer response: size not aligned to float32.")
        converted = np.frombuffer(response.content, dtype="<f4").copy()
        if converted.size and not np.isfinite(converted).all():
            raise ValueError("Voice Changer returned non-finite samples.")
        if converted.size:
            converted_chunks.append(converted)

    if not converted_chunks:
        return np.zeros(0, dtype=np.float32), output_rate

    result = np.concatenate(converted_chunks)[
        max(
            0,
            leading_silence_samples
            - round(sample_rate * VOICE_CHANGER_OUTPUT_PREROLL_SECONDS),
        ) : None if leading_silence_samples else original_sample_count
    ]
    source = original_source
    source_rms = float(np.sqrt(np.mean(source * source))) if source.size else 0.0
    result_rms = float(np.sqrt(np.mean(result * result))) if result.size else 0.0
    if source_rms > 1e-8 and result_rms <= 1e-8:
        raise RuntimeError("Voice Changer returned silence for audible TTS")
    if source_rms > 1e-8 and result_rms > 1e-8:
        result *= source_rms / result_rms
    peak = float(np.max(np.abs(result))) if result.size else 0.0
    if peak > 0.891:  # -1 dBFS ceiling prevents clipping during playback.
        result *= 0.891 / peak
    return result, output_rate


def balance_playback_level(audio, sample_rate):
    """Bounded per-utterance gain, measured over audible 20 ms frames."""
    mono = audio.mean(axis=1) if audio.ndim > 1 else audio
    frame_size = max(1, round(sample_rate * 0.02))
    powers = np.array([float(np.mean(mono[i:i + frame_size] ** 2))
                       for i in range(0, mono.size, frame_size)])
    if not powers.size or powers.max() <= 1e-12:
        return audio
    active = powers[powers >= max(1e-8, powers.max() * 0.01)]
    if not active.size:
        logging.info("TTS output level: no audible block at the measurement threshold; level unchanged.")
        return audio
    level = float(np.sqrt(active.mean()))
    if not np.isfinite(level) or level <= 0:
        logging.warning("Invalid TTS output level; level unchanged.")
        return audio
    peak = float(np.max(np.abs(audio)))
    gain = float(np.clip(float(RUNTIME_CONFIG["tts_output_target_rms"]) / level,
                         float(RUNTIME_CONFIG["tts_output_min_gain"]),
                         float(RUNTIME_CONFIG["tts_output_max_gain"])))
    gain = min(gain, 0.891 / peak)
    logging.info("TTS output level: active RMS %.2f%% -> %.2f%%, gain x%.2f, final peak %.2f%%.",
                 level * 100, level * gain * 100, gain, peak * gain * 100)
    return audio * gain


def unpack_tts_item(item):
    if isinstance(item, tuple):
        text, language = item[:2]
        generation = item[2] if len(item) >= 3 else interrupt_generation
        fallback = item[3] if len(item) >= 4 else False
        timing = item[4] if len(item) >= 5 else None
        return text, language, generation, fallback, timing
    return item, RESPONSE_LANGUAGE_GUARD.config.get("default_language", "English"), interrupt_generation, False, None


def prepare_tts_item(item, current=None):
    """Synthesis and RVC in order; never owns the audio output."""
    global _rvc_config
    text, tts_lang, generation, fallback, timing = unpack_tts_item(item)
    current = current or (lambda: turn_is_current(generation) and not shutdown_event.is_set())
    if not current():
        raise TurnCancelled()
    cleaned = clean_text_for_tts(text)
    if not cleaned or (len(cleaned) < 2 and tts_lang != 'Japanese'):
        return None
    if tts_lang.casefold() == 'french':
        engine, url, payload = 'Piper Jessica + RVC', URL_PIPER_TTS, {'text': cleaned}
    else:
        lang = 'JP' if tts_lang.casefold() == 'japanese' else 'EN'
        engine, url, payload = 'Melo ' + lang + ' + RVC', URL_MELO_TTS, {'text': cleaned, 'language': lang}
    synthesis_started = time.monotonic()
    for attempt in range(2):
        try:
            def synthesize():
                with http_session().post(url, json=payload, timeout=60) as response:
                    response.raise_for_status()
                    data, rate = sf.read(io.BytesIO(response.content), dtype='float32')
                if not data.size or not np.isfinite(data).all() or rate <= 0 or float(np.max(np.abs(data))) <= 1e-8:
                    raise RuntimeError(engine + ' returned invalid or silent audio')
                return data, rate
            data, sr = TTS_WORK.run(synthesize, current)
            break
        except TurnCancelled:
            raise
        except Exception:
            if attempt:
                raise
            logging.warning('%s unavailable; retrying once.', engine, exc_info=True)
            shutdown_event.wait(.2)
    synthesis_seconds = time.monotonic() - synthesis_started
    if tts_lang.casefold() != 'french' and sr == 44100:
        data, sr = resample_poly(data, 1, 2).astype(np.float32, copy=False), 22050
    original_data, original_rate = data, sr
    wake_hai = tts_lang.casefold() == 'japanese' and cleaned.strip().rstrip('！!。') in {'はい','ハイ','ハーイ'}
    conversion_started = time.monotonic()
    for attempt in range(2):
        if not current():
            raise TurnCancelled()
        if wake_hai and not attempt:
            logging.info('Wake greeting: Melo generated %.2f s, maximum amplitude %.6f.',
                         original_data.shape[0] / original_rate, float(np.max(np.abs(original_data))))
        try:
            data, sr = RVC_WORK.run(
                lambda: convert_tts_audio_through_voice_changer(
                    original_data, original_rate, generation,
                    leading_silence_seconds=WAKE_HAI_LEADING_SILENCE_SECONDS if wake_hai else 0.0),
                current)
            if data is None or not data.size or not np.isfinite(data).all():
                raise RuntimeError('Invalid Voice Changer buffer')
            break
        except TurnCancelled:
            raise
        except Exception:
            _rvc_config = None
            logging.warning('Voice Changer: attempt %s of 2 failed.', attempt + 1, exc_info=True)
            if attempt:
                data, sr = original_data, original_rate
                engine += ' (TTS fallback without RVC)'
    if not current():
        raise TurnCancelled()
    data = balance_playback_level(data, sr)
    if data.ndim == 1:
        data = np.column_stack((data, data))
    reference = playback_reference.prepare(data, sr)
    logging.info('Voice latency: synthesis %.3f s; RVC/wait %.3f s; audio %.2f s.',
                 synthesis_seconds, time.monotonic()-conversion_started, len(data)/sr)
    return data, sr, reference, engine, generation, fallback, timing, cleaned


def tts_prepare_worker():
    """At most one segment ahead of playback; one RVC stream at a time."""
    global tts_generating, pause_reply_generation
    while not shutdown_event.is_set():
        if not prepare_slot.acquire(timeout=.1):
            continue
        slot_owned, item = True, None
        generation, fallback = None, True
        try:
            try:
                item = tts_queue.get(timeout=.1)
            except queue.Empty:
                continue
            if item is None:
                return
            _, _, generation, fallback, _ = unpack_tts_item(item)
            while not shutdown_event.is_set() and turn_is_current(generation):
                with state_lock:
                    if not user_phrase_active:
                        tts_generating = True
                        break
                shutdown_event.wait(.02)
            if shutdown_event.is_set() or not turn_is_current(generation):
                continue
            preview = item[5] if isinstance(item, tuple) and len(item) > 5 else None
            prepared = preview.wait() if preview is not None else None
            if prepared is None:
                prepared = prepare_tts_item(item)
            else:
                logging.info('Voice latency: first speculative preparation reused after full validation.')
            with state_lock:
                if prepared is not None and turn_is_current(generation):
                    prepared_tts.put_nowait(prepared)
                    prepared_available.set()
                    slot_owned = False  # The playback worker or clear_tts_queue releases it.
        except TurnCancelled:
            pass
        except Exception:
            logging.exception('[TTS Error] Segment preparation')
            with state_lock:
                if generation is not None and turn_is_current(generation):
                    clear_tts_queue()
                    if pause_reply_generation == generation:
                        pause_reply_generation = None
                        enter_sleep('sleep response unavailable', paused=True)
                    elif not fallback:
                        enqueue_japanese_error_response(generation)
        finally:
            with state_lock:
                tts_generating = False
            if item is not None:
                tts_queue.task_done()
            if slot_owned:
                prepare_slot.release()


def tts_worker():
    """Playback only; the following segment may be prepared concurrently."""
    global is_speaking, playback_reserved, pause_reply_generation
    global playback_recovery_start, capture_resume_after
    output_latency_logged = False
    while not shutdown_event.is_set():
        prepared_available.wait()
        if shutdown_event.is_set():
            break
        with state_lock:
            prepared_available.clear()
            try:
                prepared = prepared_tts.get_nowait()
            except queue.Empty:
                prepared = None
            if prepared is not None:
                playback_reserved = True
                prepare_slot.release()
        if prepared is None:
            continue
        data, sr, reference, engine, generation, fallback, timing, spoken_text = prepared
        try:
            with state_lock:
                if not turn_is_current(generation):
                    continue
                playback_reference.start(reference, time.monotonic())
                sd.play(data, samplerate=sr, device=TTS_DEVICE_INDEX)
            stream = sd.get_stream()
            deadline = time.monotonic() + .5
            while stream is not None and not stream.active and time.monotonic() < deadline and turn_is_current(generation):
                shutdown_event.wait(.005)
                stream = sd.get_stream()
            if not turn_is_current(generation):
                sd.stop()
                continue
            if stream is None or not stream.active:
                raise RuntimeError("Audio playback did not start")
            is_speaking = True
            if timing is None:
                with state_lock:
                    if turn_is_current(generation):
                        chat_events.message('auto-' + str(time.monotonic_ns()), spoken_text,
                                            ['Mio'], complete=True, mio=True)
            if not output_latency_logged:
                logging.info('Actual speaker stream latency: %.1f ms; WebRTC estimates acoustic delay.', stream.latency*1000)
                output_latency_logged = True
            logging.info("Audio playback %s has started; Vosk keeps listening.", engine)
            if timing is not None and not timing.get('spoken'):
                timing['spoken'] = True
                logging.info('Turn latency %s: Turbo result -> first voice %.3f s; detected end -> voice %.3f s.',
                             timing['id'], time.monotonic()-timing['finalized_at'],
                             time.monotonic()-timing['finished_at'])
            while not shutdown_event.is_set():
                if not turn_is_current(generation):
                    sd.stop()
                    break
                stream = sd.get_stream()
                if stream is None or not stream.active:
                    with state_lock:
                        if (turn_is_current(generation) and tts_queue.empty()
                                and prepared_tts.empty() and not tts_generating and microphone is not None):
                            ended_at = time.monotonic()
                            playback_recovery_start = ended_at-float(RUNTIME_CONFIG['mio_tail_preroll_seconds'])
                            microphone.recover_playback_tail(playback_recovery_start, ended_at, generation)
                            capture_resume_after = ended_at+float(RUNTIME_CONFIG['post_mio_guard_seconds'])
                            logging.info('Mio finished: %.2f s of cleaned microphone audio available in the pre-buffer.',
                                         float(RUNTIME_CONFIG['mio_tail_preroll_seconds']))
                    break
                shutdown_event.wait(.01)
        except Exception:
            playback_reference.clear()
            logging.exception('[TTS Error] Segment playback')
            with state_lock:
                if not fallback and turn_is_current(generation):
                    clear_tts_queue()
                    enqueue_japanese_error_response(generation)
        finally:
            with state_lock:
                is_speaking = False
                playback_reserved = False
                if pause_reply_generation == generation:
                    pause_reply_generation = None
                    enter_sleep('sleep command after the reply', paused=True)
            prepared_tts.task_done()


# ============================================================
# 7) WHISPER TURBO RECORDING AND TRANSCRIPTION
# ============================================================
def record_audio():
    """Build one complete utterance from the single, continuously open input."""
    global capture_resume_after, last_sent_wav_at, user_phrase_active, voice_wait_since
    while not shutdown_event.is_set():
        with state_lock:
            generation = interrupt_generation
            active = voice_pipeline_busy() or not tts_queue.empty()
            can_capture = (runtime_ready.is_set() and turn_is_current(generation) and not active
                           and microphone.ready.is_set() and time.monotonic() >= capture_resume_after)
        if can_capture:
            break
        time.sleep(0.02)
    if shutdown_event.is_set():
        return None
    # Keep the continuously captured FIFO; eligibility was stamped at capture.
    guard_end = capture_resume_after
    history_floor = max(
        0.0,
        guard_end - float(RUNTIME_CONFIG["post_mio_guard_seconds"]),
        last_sent_wav_at + 1e-6,
    )
    if playback_recovery_start is not None:
        history_floor = max(last_sent_wav_at + 1e-6, min(history_floor, playback_recovery_start))
    frame_seconds = VOSK_FRAME_SAMPLES / SAMPLE_RATE
    audio_chunks = []
    stream = None
    complete = False
    silent_chunks = 0
    silence_limit = int(np.ceil(float(RUNTIME_CONFIG["sentence_silence_seconds"]) / frame_seconds))
    vad_threshold = float(RUNTIME_CONFIG["phrase_vad_speech_probability"])
    vad_continue_threshold = float(RUNTIME_CONFIG["phrase_vad_continue_probability"])
    start_frames = int(RUNTIME_CONFIG["phrase_vad_start_frames"])
    onset_frames = 0
    dropped_at_start = microphone.dropped_frames
    vad_stats_started = time.monotonic()
    vad_stats_count = 0
    vad_stats_max = 0.0
    vad_stats_above = 0
    try:
        vad_client.reset()
        # No arbitrary sixteen-second cutoff: only a sentence end or cancellation.
        while turn_is_current(generation) and not voice_pipeline_busy():
            if stream is not None and stream.closed:
                logging.warning("Capture discarded: progressive processing unavailable.")
                return None
            if not microphone.ready.is_set():
                return None  # on_microphone_error already purged and queued the reply.
            try:
                captured_at, chunk, frame_generation = microphone.read()
            except queue.Empty:
                continue
            if frame_generation != generation or captured_at <= guard_end:
                continue
            if microphone.dropped_frames != dropped_at_start:
                logging.error("Utterance discarded: blocks lost before Silero, incomplete audio.")
                return None
            vad_probability = vad_client.probability(chunk)
            vad_stats_count += 1
            vad_stats_max = max(vad_stats_max, vad_probability)
            vad_stats_above += int(vad_probability >= vad_threshold)
            if time.monotonic() - vad_stats_started >= 5.0:
                logging.info("Silero diagnostics: max score %.3f; %s/%s blocks above onset %.2f; utterance open=%s.",
                             vad_stats_max, vad_stats_above, vad_stats_count, vad_threshold, bool(audio_chunks))
                vad_stats_started = time.monotonic()
                vad_stats_count = vad_stats_above = 0
                vad_stats_max = 0.0
            if not audio_chunks:
                onset_frames = onset_frames + 1 if vad_probability >= vad_threshold else 0
            speech = (bool(audio_chunks) and vad_probability >= vad_continue_threshold) or onset_frames >= start_frames
            if speech:
                if not audio_chunks:
                    with state_lock:
                        if not turn_is_current(generation) or voice_pipeline_busy() or not tts_queue.empty():
                            return None
                        user_phrase_active = True
                    preceding = microphone.before(captured_at, generation, history_floor)
                    audio_chunks.extend(preceding)
                    stream = progressive_stt.begin(generation)
                    for previous_chunk in preceding:
                        stream.append(previous_chunk)
                    logging.info("Speech start: %.2f s recovered from the FIFO pre-buffer.",
                                 len(preceding) * frame_seconds)
                audio_chunks[:] = [chunk]
                stream.append(chunk)
                onset_frames = 0
                silent_chunks = 0
                with state_lock:
                    voice_wait_since = time.monotonic()
            elif audio_chunks:
                audio_chunks[:] = [chunk]
                stream.append(chunk)
                silent_chunks += 1
                if silent_chunks >= silence_limit:
                    logging.info("End of utterance detected: %.2f s without voice according to Silero VAD; sending to Whisper Turbo.",
                                 silent_chunks * frame_seconds)
                    break
        if not turn_is_current(generation) or voice_pipeline_busy() or not audio_chunks:
            return None
        with state_lock:
            capture_resume_after = max(capture_resume_after, captured_at)
            last_sent_wav_at = captured_at
        complete = True
        return stream, generation
    except VoiceActivityError:
        logging.exception("Silero VAD unavailable: capture stopped.")
        enter_sleep("speech detector unavailable")
        shutdown_event.set()
        return None
    except Exception:
        logging.exception("Unable to prepare WAV.")
        audio_chunks.clear()
        enqueue_japanese_error_response(generation)
        return None
    finally:
        if stream is not None and not complete:
            stream.close()
        with state_lock:
            user_phrase_active = False


def capture_utterances():
    """Mic/Silero never wait for HTTP. Windows are transcribed during capture."""
    while not shutdown_event.is_set():
        captured = record_audio()
        if captured is None:
            continue
        stream, generation = captured
        with state_lock:
            if not turn_is_current(generation):
                stream.close()
                continue
            progressive_stt.finish(stream)
            logging.info("End of speech: finalizing the last Turbo words.")


def publish_provisional(text, generation):
    with state_lock:
        if turn_is_current(generation):
            print(f"\nToi [provisoire] : {text}", flush=True)


def publish_chat_transcription(text, generation, phrase_id, identity, complete):
    with state_lock:
        if not turn_is_current(generation):
            return
        if identity.get('mio_only'):
            chat_events.emit('remove', key='user-' + phrase_id)
        elif complete == 'error':
            chat_events.emit('error', key='user-' + phrase_id, text=text,
                             names=chat_names(identity), mio=False)
        elif text:
            chat_events.message('user-' + phrase_id, text, chat_names(identity), complete=complete)
        elif complete:
            chat_events.emit('remove', key='user-' + phrase_id)


def consume_transcribed_control(result):
    """Exact child-exit fallback, before waiting behind an older spoken response."""
    text, confidence, language, identity, generation = result
    if not text or identity.get('mio_only'):
        return False
    language_key = language.split('-', maxsplit=1)[0]
    if not language or not WHISPER_ALLOWED_LANGUAGES.get(language_key, WHISPER_ALLOWED_LANGUAGES.get(language)):
        return False
    minimum = {'ja': WHISPER_JA_MIN_TOKEN_CONFIDENCE,
               'en': WHISPER_EN_MIN_TOKEN_CONFIDENCE}.get(language_key, WHISPER_MIN_TOKEN_CONFIDENCE)
    if not confidence >= minimum:
        return False
    if normalize_control_phrase(text) not in {normalize_control_phrase(p) for p in TRIGGER_PHRASES['child_exit']}:
        return False
    with state_lock:
        if not turn_is_current(generation):
            return False
        publish_chat_transcription(text, generation, identity['_timing']['id'], identity, True)
        handle_vosk_command('child_exit', text, source='whisper')
    logging.info('End Child mode command recovered from validated Whisper text.')
    return True


def transcription_pending():
    return progressive_stt is not None and progressive_stt.busy()


memory_quiet_since = time.monotonic()


def memory_can_extract():
    global memory_quiet_since
    now = time.monotonic()
    busy = (not runtime_ready.is_set() or shutdown_event.is_set()
            or assistant_audio_active() or conversation_pending.is_set() or user_phrase_active
            or stt_processing or transcription_pending())
    if busy:
        memory_quiet_since = now
        return False
    return now - memory_quiet_since >= float(RUNTIME_CONFIG.get("memory_quiet_seconds", 30.0))


def transcribe_audio(audio_data, generation):
    if not audio_data or not turn_is_current(generation):
        return "", 0.0, ""

    for attempt in range(2):
        if not turn_is_current(generation):
            return "", 0.0, ""
        try:
            audio_data.seek(0)
            res = requests.post(
                URL_STT,
                files={"file": ("audio.wav", audio_data, "audio/wav")},
                data={
                    "temperature": "0.0",
                    "no_speech_threshold": "0.6",
                },
                timeout=(5, float(RUNTIME_CONFIG["stt_timeout_seconds"])),
            )
            if res.status_code != 200:
                logging.error("[STT HTTP %s] %s", res.status_code, res.text[:2000])
                continue
            if not turn_is_current(generation):
                logging.info("Whisper Turbo transcription cancelled by a state change.")
                return "", 0.0, ""
            result = res.json()
            text = str(result.get("text", "")).strip()
            if not text:
                # Silence/no text is not a language error and needs no identical retry.
                logging.info("Turbo: no text; silently resuming listening.")
                return "", 0.0, ""
            confidence = result.get("token_confidence")
            raw_lang = str(result.get("language", "auto")).strip().lower()
            language_key = raw_lang.split("-", maxsplit=1)[0]
            if not WHISPER_ALLOWED_LANGUAGES.get(
                language_key, WHISPER_ALLOWED_LANGUAGES.get(raw_lang, "")
            ):
                return "", 0.0, raw_lang
            if (not text or confidence is None
                    or result.get("confidence_method") != "mean_token_probability"):
                logging.warning("Whisper Turbo did not provide an utterance and a verifiable score.")
                continue
            confidence = float(confidence)
            if not np.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("Invalid Whisper score")
            logging.info(
                "Whisper Turbo transcription (language(s) %s, token score %.1f%%): %s",
                raw_lang,
                confidence * 100,
                text,
            )
            return text, confidence, raw_lang
        except Exception:
            logging.exception("Whisper Turbo transfer failed, attempt %s of 2.", attempt + 1)

    logging.error("Whisper Turbo did not provide a usable transcription after one retry.")
    try:
        audio_data.seek(0)
        audio_data.truncate(0)
    except (AttributeError, OSError, ValueError):
        pass
    # No usable STT text is often microphone noise or loudspeaker bleed.
    # Resume listening silently instead of feeding an error reply back into the microphone.
    return "", 0.0, ""


# ============================================================
# 8) LM STUDIO CONVERSATION AND TTS OUTPUT
# ============================================================
def request_llm_text(messages, generation, on_text=None):
    def receive():
        parts = []
        started = time.monotonic()
        first_text_at = None
        with LLM_SCHEDULER.acquire(lambda: turn_is_current(generation)):
            admitted_at = time.monotonic()
            logging.info('LLM latency: scheduler wait %.3f s.', admitted_at - started)
            return receive_stream(parts, started, admitted_at, first_text_at)

    def receive_stream(parts, started, admitted_at, first_text_at):
        with http_session().post(
            URL_LLM,
            json={"model": LLM_MODEL_NAME, "messages": with_current_time(messages),
                  "temperature": float(RESPONSE_LANGUAGE_GUARD.config["temperature"]), "stream": True,
                  **conversation_options(),
                  **generation_options(LLM_MODEL_NAME)},
            stream=True, timeout=(10, 60),
        ) as response:
            response.raise_for_status()
            logging.info('Latence LLM : ouverture HTTP %.3f s.', time.monotonic() - admitted_at)
            for line in response.iter_lines(chunk_size=1):
                if not turn_is_current(generation):
                    raise TurnCancelled()
                if not line or not line.startswith(b"data: "):
                    continue
                value = line[6:].decode("utf-8", errors="replace").strip()
                if value == "[DONE]":
                    text = "".join(parts)
                    if not text.strip():
                        raise RuntimeError("LM Studio returned an empty response")
                    logging.info('LLM latency, including wait: %.3f s.', time.monotonic() - started)
                    if first_text_at is not None:
                        logging.info('LLM latency: first text -> finish %.3f s.', time.monotonic() - first_text_at)
                    return text
                try:
                    choice = json.loads(value)["choices"][0]
                    if choice.get('finish_reason') == 'length':
                        logging.warning('LLM response reached the %s token limit; response may be incomplete.',
                                        conversation_options()['max_tokens'])
                    content = choice.get("delta", {}).get("content", "") or ""
                    if content and first_text_at is None:
                        first_text_at = time.monotonic()
                        logging.info('LLM latency: request -> first text %.3f s.', first_text_at - admitted_at)
                    parts.append(content)
                    if on_text is not None:
                        on_text(content)
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
        raise RuntimeError("LM Studio did not complete a usable response")
    return LLM_WORK.run(receive, lambda: turn_is_current(generation))


def ask_llm(user_text, request_generation, speaker_identity=None, detected_language="fr"):
    global llm_generating, female_turn_generation, active_reply_mode, active_reply_generation
    with state_lock:
        if not turn_is_current(request_generation):
            return
    now = time.monotonic()
    timing = (speaker_identity or {}).get('_timing') or {'id':str(request_generation), 'finished_at':now, 'finalized_at':now}
    logging.info('Turn latency %s: Turbo result -> conversation start %.3f s.',
                 timing['id'], now-timing['finalized_at'])
    detected_language = detected_language.split("-", maxsplit=1)[0].lower()
    reply_language = requested_reply_language(user_text) or {
        "fr": "French", "en": "English", "ja": "Japanese"
    }.get(detected_language, RESPONSE_LANGUAGE_GUARD.config.get("default_language", "English"))
    language_labels = {
        "French": "French",
        "Japanese": "Japanese",
        "English": "English",
    }
    language_label = language_labels.get(reply_language, "English")
    visible_names = last_trusted_face_names
    if not visible_names or not turn_is_current(request_generation):
        logging.info("LLM call cancelled: no registered face recognized at send time.")
        return
    with state_lock:
        if not turn_is_current(request_generation):
            return
        prompt_mode = select_prompt_mode(visible_names, speaker_identity)
        chat_history = chat_histories[prompt_mode]
        previous_history = []
        for entry in chat_history:
            clean_entry = dict(entry)
            if clean_entry.get("role") == "user" and isinstance(clean_entry.get("content"), str):
                clean_entry["content"] = re.sub(
                    r"^\[Noms détectés globalement dans ce passage : [^\]]+\]\s*", "",
                    clean_entry["content"], flags=re.IGNORECASE)
            previous_history.append(clean_entry)
        conversation = previous_history[-6:] + [{"role": "user", "content": user_text}]
        active_reply_mode, active_reply_generation = prompt_mode, request_generation
        llm_generating = True
        if prompt_mode == "Adult":
            female_turn_generation = request_generation
    if prompt_mode == "Child":
        reply_language = RESPONSE_LANGUAGE_GUARD.config.get("child_language", "English")
    elif prompt_mode == "Adult" and reply_language == "Japanese":
        reply_language = RESPONSE_LANGUAGE_GUARD.config.get("default_language", "English")
    language_label = language_labels.get(reply_language, "English")
    # Common and mode files carry the durable rules once; only the turn varies here.
    turn_instruction = RESPONSE_LANGUAGE_GUARD.config["turn_instruction"].format(language=language_label)
    logging.info("Prompt selected for this turn: %s.", prompt_mode)
    try:
        relevant_memories = LLM_WORK.run(lambda: recall(user_text, prompt_mode, previous_history),
                                        lambda: turn_is_current(request_generation))
    except TurnCancelled:
        if chat_history and chat_history[-1].get("role") == "user":
            chat_history.pop()
        llm_generating = False
        return
    if relevant_memories:
        logging.info("Vector memory: %s relevant memories for context %s.",
                     len(relevant_memories), prompt_mode)
    turn_instruction += " " + camera_context_instruction(FACE_PRESENCE.snapshot())
    turn_instruction += " " + speaker_context_instruction(speaker_identity)
    system_message = {
        "role": "system",
        "content": PROMPTS.get(prompt_mode, PROMPTS["Normal"]) + " " + turn_instruction
                   + " " + memory_instruction(relevant_memories),
    }
    messages = [system_message, *conversation]

    preview = None
    def select_first_segment(text):
        text = normalize_reply_names(text)
        sentences = re.split(r"(?:(?<=[!?。！？\n])|(?<=\.)(?<!\d\.))\s*", text)
        if len(sentences) < 2 or not sentences[0].strip():
            return None
        for part, lang in split_tts_by_language(sentences[0].strip(), reply_language):
            cleaned = clean_text_for_tts(part)
            if cleaned and (len(cleaned) >= 2 or lang == 'Japanese'):
                return part, lang, request_generation, False, timing
        return None

    try:
        llm_generating = True
        full_reply = ""
        llm_error = None
        interrupted = False
        print("Mio : ", end="", flush=True)

        # Keep generated text in memory until the stream finishes. If the
        # transfer fails, Mio can retry once without speaking a partial answer.
        for attempt in range(2):
            if not turn_is_current(request_generation):
                interrupted = True
                break
            full_reply = ""
            if preview is not None:
                preview.cancel()
            preview = ReplyPreview(select_first_segment, prepare_tts_item,
                                   lambda: turn_is_current(request_generation) and not shutdown_event.is_set())
            try:
                full_reply = normalize_reply_names(request_llm_text(messages, request_generation, preview.feed))
                rejected = RESPONSE_LANGUAGE_GUARD.rejected_language(full_reply, reply_language, mode=prompt_mode)
                if rejected:
                    preview.cancel()
                    logging.warning("LLM response rejected (%s), attempt %s/2: %r",
                                    rejected, attempt + 1, full_reply[:240])
                    if attempt == 0:
                        messages = [*messages, {
                            "role": "system",
                            "content": RESPONSE_LANGUAGE_GUARD.config["child_repair_instruction" if prompt_mode == "Child" else "repair_instruction"].format(
                                language=language_label),
                        }]
                        continue
                    raise RuntimeError("Response still outside allowed languages after rewriting.")
                repeated = repetition_reason(full_reply, user_text, previous_history)
                if repeated:
                    preview.cancel()
                    logging.warning('Repetitive response rejected before playback: %s (attempt %s/2).', repeated, attempt + 1)
                    if attempt == 0:
                        # Do not invite the model to copy its own bad prose again.
                        messages = [message for message in messages if message['role'] != 'assistant']
                        messages.append({'role': 'system', 'content': REPETITION_REPAIR})
                        continue
                    raise RuntimeError('Response still repetitive after rewriting.')
                llm_error = None
                break
            except TurnCancelled:
                preview.cancel()
                interrupted = True
                break
            except Exception as exc:
                preview.cancel()
                llm_error = exc
                logging.warning(
                    "LLM response failed, attempt %s of 2.", attempt + 1,
                    exc_info=True,
                )
                if attempt == 0:
                    time.sleep(0.2)
        print()
        if interrupted or stop_requested or request_generation != interrupt_generation:
            return
        if llm_error is not None:
            logging.error("LLM returned no response after one retry.")
            if chat_history and chat_history[-1].get("role") == "user":
                chat_history.pop()
            enqueue_japanese_error_response(request_generation)
            return

        # The accepted immutable full_reply was already checked in the loop above.

        # Keep list numbers and decimals attached to their following context.
        sentences = re.split(r"(?:(?<=[!?。！？\n])|(?<=\.)(?<!\d\.))\s*", full_reply.strip())
        spoken_parts = 0
        for sentence in sentences:
            clean_sentence = sentence.strip()
            if not clean_sentence:
                continue
            tts_parts = split_tts_by_language(clean_sentence, reply_language)
            print(" ".join(part for part, _lang in tts_parts) + " ", end="", flush=True)
            for tts_text, tts_lang in tts_parts:
                with state_lock:
                    if not turn_is_current(request_generation):
                        return
                    cleaned_part = clean_text_for_tts(tts_text)
                    if cleaned_part and (len(cleaned_part) >= 2 or tts_lang == "Japanese"):
                        item = (tts_text, tts_lang, request_generation, False, timing)
                        prepared_preview = preview.claim(item) if spoken_parts == 0 and preview is not None else None
                        tts_queue.put((*item, prepared_preview))
                        spoken_parts += 1
        if not spoken_parts:
            enqueue_japanese_error_response(request_generation)
            return
        print(flush=True)

        display_reply = full_reply.strip()
        with state_lock:
            if not turn_is_current(request_generation):
                return
            chat_history.extend([
                {"role": "user", "content": user_text},
                {"role":"assistant", "content":display_reply},
            ])
            chat_events.message('reply-' + timing['id'],
                                display_reply,
                                ['Mio'], complete=True, mio=True)
        try:
            capture_async(
                user_text, prompt_mode, URL_LLM, LLM_MODEL_NAME,
                lambda: request_generation == interrupt_generation, memory_can_extract,
                generation=request_generation,
                speaker_names=(speaker_identity or {}).get('names', []), recent_history=previous_history,
            )
        except Exception:
            logging.exception('Memory: queue unavailable; conversation response retained.')
    except Exception as e:
        logging.exception("[LLM Error] %s", e)
        if chat_history and chat_history[-1].get("role") == "user":
            chat_history.pop()
        enqueue_japanese_error_response(request_generation)
    finally:
        if preview is not None and not preview.claimed:
            preview.cancel()
        if request_generation != interrupt_generation and chat_history and chat_history[-1].get("role") == "user":
            chat_history.pop()
        llm_generating = False


def verify_startup_services():
    """Check loaded models, not just an open TCP port."""
    checks = (
        ("Whisper Turbo", "http://127.0.0.1:9000/health",
         lambda data: data.get("ready") and data.get("service") == "WhisperTurbo"
         and data.get("confidence_method") == "mean_token_probability"
         and data.get("progressive_protocol") == 1),
        ("Piper Jessica", "http://127.0.0.1:9881/health",
         lambda data: data.get("service") == "PiperTTS"),
        ("Melo JP/EN", "http://127.0.0.1:9882/health",
         lambda data: data.get("service") == "MeloTTS" and {"JP", "EN-US"}.issubset(data.get("voices", []))),
        ("Voice Changer", URL_VC_CONFIG,
         lambda data: data.get("input_sample_rate") == 22050 and data.get("output_sample_rate") == 22050),
        ("LM Studio / LLM", COMPONENTS['llm']['health_url'],
         lambda data: any(model.get("state") == "loaded" and LLM_MODEL_NAME in model.get("id", "")
                          for model in data.get("data", []))),
    )
    for name, url, check in checks:
        response = requests.get(url, timeout=3)
        response.raise_for_status()
        if not check(response.json()):
            raise RuntimeError(f"{name} is not ready or uses an old version")


# UI commands are blocking reads, not polling. Only the current UI token is accepted.
ui_text_queue = queue.Queue(maxsize=8)
reload_main_requested = threading.Event()

def read_ui_commands():
    for line in sys.stdin:
        try:
            command = json.loads(line)
            if not os.environ.get('MIO_UI_TOKEN') or command.get('token') != os.environ['MIO_UI_TOKEN']:
                continue
            if command.get('action') == 'reload':
                reload_main_requested.set()
                cancel_current_turn()
                shutdown_event.set()
                return
            if command.get('action') == 'text':
                text = str(command.get('text', '')).strip()
                if text:
                    identity = author_identity(command.get('author'))
                    message_id = command.get('id')
                    if not isinstance(message_id, str) or not re.fullmatch(r'typed-[a-f0-9]{32}', message_id):
                        message_id = 'typed-' + uuid.uuid4().hex
                    payload = {'text': text, 'identity': identity, 'id': message_id}
                    ui_text_queue.put_nowait((payload, interrupt_generation))
                    chat_events.message('user-' + message_id, text, identity['names'], complete=True)
        except queue.Full:
            chat_events.emit('error', key='typed-queue-full', text='Too many pending messages. Wait before sending again.')
        except (ValueError, TypeError, OSError) as error:
            chat_events.emit('error', key='typed-input-' + str(time.monotonic_ns()),
                             text='Message not sent: ' + str(error))

def handle_ui_text(payload):
    text = payload['text']
    # Typed input is not voice identification and never bypasses facial access.
    if not FACE_PRESENCE.snapshot().has_known_person:
        chat_events.emit('error', key='typed-face-' + str(time.monotonic_ns()),
                         text='Message not sent: a recognized face is required. Copy the message below to try again: ' + text)
        return
    if not conversation_active or mio_paused:
        wake_session()
    generation = interrupt_generation
    if not turn_is_current(generation):
        chat_events.emit('error', key='typed-not-ready', text='Mio is not ready. Please send the message again: ' + text)
        return
    now = time.monotonic()
    identity = dict(payload['identity'])
    identity['_timing'] = {'id': payload['id'], 'finished_at': now, 'finalized_at': now}
    chat_events.message('user-' + identity['_timing']['id'], text, identity['names'], complete=True)
    ask_llm(text, generation, speaker_identity=identity)


def main():
    global microphone, stt_processing, voice_wait_since, aec_client, vad_client, capture_thread, progressive_stt
    if os.environ.get('MIO_UI_TOKEN'):
        threading.Thread(target=read_ui_commands, daemon=True, name='Mio-UI-input').start()
    status = RuntimeStatus(READY_FILE)
    status_thread = None
    final_reason = "MainApp stopped"

    def publish_status():
        while not shutdown_event.wait(1.0):
            with state_lock:
                publish_chat_state()
            ready = (vosk_ready.is_set() and microphone.ready.is_set()
                     and FACE_PRESENCE.snapshot().camera_ready
                     and aec_client is not None and aec_client.process is not None
                      and aec_client.process.poll() is None
                      and vad_client is not None and vad_client.process is not None
                      and vad_client.process.poll() is None
                      and capture_thread is not None and capture_thread.is_alive()
                      and progressive_stt is not None and progressive_stt.worker.is_alive())
            try:
                status.write(ready, "Ready" if ready else "Microphone, WebRTC, Silero VAD, Vosk or camera unavailable")
            except OSError:
                logging.exception("Unable to publish MainApp state")

    try:
        logging.info("Initializing Mio; optional speaker tags in parallel, empty references ignored.")
        threading.Thread(target=SPEAKER_RECOGNIZER.warm_up, daemon=True, name="Mio-Speaker-Warmup").start()
        progressive_stt = ProgressiveTranscriber(URL_STT, RUNTIME_CONFIG, turn_is_current,
                                                SPEAKER_RECOGNIZER, publish_provisional,
                                                publish_details=publish_chat_transcription,
                                                consume_result=consume_transcribed_control)
        progressive_stt.start()
        aec_client = EchoClient(playback_reference)
        aec_client.start()
        logging.info("WebRTC AEC3 ready: microphone cleaned before Vosk and Whisper.")
        vad_client = VoiceActivityClient()
        vad_client.start()
        logging.info("Silero VAD ready: Whisper utterance endings detected in cleaned audio.")
        start_vosk_trigger()
        if vosk_process is None:
            raise RuntimeError("Vosk did not start")
        FACE_PRESENCE.start()
        threading.Thread(target=tts_worker, daemon=True, name="Mio-TTS").start()
        threading.Thread(target=tts_prepare_worker, daemon=True, name="Mio-TTS-Preparation").start()
        with open(os.path.join(MAINAPP_DIR, "config", "peripheriques_audio.json"), encoding="utf-8") as audio_config_file:
            audio_config = json.load(audio_config_file)
        logging.info("VB Cable gate before WebRTC: threshold %.2f%% RMS, hold %s ms.",
                     100 * float(audio_config["vb_cable_gate_rms"]),
                     audio_config["vb_cable_gate_hold_ms"])
        microphone = MicrophoneInput(
            resolve_microphone_device(), SAMPLE_RATE, VOSK_FRAME_SAMPLES,
            float(RUNTIME_CONFIG["microphone_queue_seconds"]), on_microphone_chunk, on_microphone_error,
            preroll_seconds=float(RUNTIME_CONFIG["audio_preroll_seconds"]),
            process_chunk=aec_client.process_chunk,
            gate_rms_threshold=float(audio_config["vb_cable_gate_rms"]),
            gate_hold_seconds=float(audio_config["vb_cable_gate_hold_ms"]) / 1000,
            whisper_gate_rms_threshold=float(audio_config["whisper_gate_rms"]),
        )
        microphone.start()
        deadline = time.monotonic() + float(RUNTIME_CONFIG["startup_timeout_seconds"])
        last_error = "Waiting for microphone, Vosk and camera"
        while time.monotonic() < deadline:
            if vosk_process.poll() is not None:
                raise RuntimeError("Vosk stopped during initialization")
            if (vosk_ready.is_set() and microphone.ready.is_set()
                    and FACE_PRESENCE.snapshot().camera_ready):
                try:
                    verify_startup_services()
                    break
                except (requests.RequestException, ValueError, RuntimeError) as exc:
                    last_error = str(exc)
            status.write(False, last_error)
            time.sleep(1)
        else:
            raise RuntimeError(f"Incomplete startup: {last_error}; micro : {microphone.error}")

        threading.Thread(target=conversation_watchdog, daemon=True, name="Mio-State").start()
        runtime_ready.set()
        capture_thread = threading.Thread(target=capture_utterances, daemon=True, name="Mio-Phrases")
        capture_thread.start()
        try:
            start_memory_worker(URL_LLM, LLM_MODEL_NAME, memory_can_extract)
        except Exception:
            logging.exception('Persistent memory unavailable; conversation continues.')
        status.write(True, "Models, Vosk, microphone and camera ready")
        status_thread = threading.Thread(target=publish_status, daemon=True, name="Mio-Status")
        status_thread.start()
        print("System ready. Mio is asleep; Vosk keeps listening.", flush=True)

        while not shutdown_event.is_set():
            # Finished WAVs survive HTTP/LLM latency; never read the mic here.
            if assistant_audio_active():
                shutdown_event.wait(0.02)
                continue
            try:
                typed = ui_text_queue.get_nowait()
            except queue.Empty:
                typed = None
            if typed is not None:
                typed, typed_generation = typed
                if typed_generation != interrupt_generation:
                    chat_events.emit('error', key='typed-cancelled-' + str(time.monotonic_ns()), text='Message cancelled after a state change: ' + typed['text'])
                    continue
                conversation_pending.set()
                try:
                    handle_ui_text(typed)
                finally:
                    conversation_pending.clear()
                continue
            try:
                txt, confidence, language, identity, generation = progressive_stt.results.get(timeout=0.1)
            except queue.Empty:
                continue
            conversation_pending.set()
            try:
                voice_wait_since = time.monotonic()
                if not turn_is_current(generation):
                    continue
                if identity.get("mio_only"):
                    logging.info("Passage recognized only as the Mio voice: reply ignored.")
                    continue
                language_key = language.split("-", maxsplit=1)[0]
                if language and not WHISPER_ALLOWED_LANGUAGES.get(language_key, WHISPER_ALLOWED_LANGUAGES.get(language)):
                    logging.info("Utterance rejected: language not allowed (%s).", language)
                    publish_chat_transcription(txt + ' — Language not allowed.', generation,
                                               identity['_timing']['id'], identity, 'error')
                    enqueue_japanese_error_response(generation)
                    continue
                minimum_confidence = {
                    "ja": WHISPER_JA_MIN_TOKEN_CONFIDENCE,
                    "en": WHISPER_EN_MIN_TOKEN_CONFIDENCE,
                }.get(language_key, WHISPER_MIN_TOKEN_CONFIDENCE)
                if txt and confidence < minimum_confidence:
                    logging.info("Utterance rejected: mean token probability %.1f%% < %.1f%%.",
                                 confidence * 100, minimum_confidence * 100)
                    publish_chat_transcription(txt + ' — Transcription trop incertaine.', generation,
                                               identity['_timing']['id'], identity, 'error')
                    enqueue_japanese_error_response(generation)
                    continue
                if not txt:
                    continue
                # Vosk is primary; exact commands in a valid Whisper result are a fallback.
                if is_pause_request(txt):
                    pause_mio()
                    continue
                if is_mio_wake_request(txt) or is_short_mio_wake(txt):
                    wake_session()
                    continue
                if normalize_control_phrase(txt) in {normalize_control_phrase(p) for p in TRIGGER_PHRASES["flirt"]}:
                    handle_vosk_command("flirt", txt)
                    continue
                if is_stop_only_command(txt):
                    continue
                clean = clean_wake_words(txt)
                while (turn_is_current(generation) and not shutdown_event.is_set()
                       and (assistant_audio_active() or user_phrase_active)):
                    shutdown_event.wait(0.02)
                if len(clean) > 1 and turn_is_current(generation):
                    print(f"\nToi : {clean}", flush=True)
                    ask_llm(clean, generation, speaker_identity=identity, detected_language=language)
            finally:
                conversation_pending.clear()
    except KeyboardInterrupt:
        logging.info("Shutdown requested")
    except Exception as exc:
        final_reason = str(exc)
        status.write(False, str(exc), failed=True)
        raise
    finally:
        runtime_ready.clear()
        shutdown_event.set()
        prepared_available.set()
        close_memory()
        if status_thread is not None:
            status_thread.join(timeout=2)
        with state_lock:
            enter_sleep("MainApp shutdown")
        if microphone is not None:
            microphone.closed.set()
            microphone.thread.join(timeout=2)
        if capture_thread is not None:
            capture_thread.join(timeout=2)
        if progressive_stt is not None:
            progressive_stt.close()
        if not reload_main_requested.is_set():
            SPEAKER_RECOGNIZER.close()
        if aec_client is not None:
            aec_client.close()
        if vad_client is not None:
            vad_client.close()
        FACE_PRESENCE.stop()
        if vosk_process is not None and vosk_process.poll() is None:
            vosk_process.terminate()
            try:
                vosk_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                vosk_process.kill()
                vosk_process.wait(timeout=5)
        status.write(False, final_reason, failed=True)
        status.close()


if __name__ == "__main__":
    main()
