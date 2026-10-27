"""Read registered people from the existing Agent DVR and CodeProject.AI services.

This integration deliberately does not open the camera itself. Agent DVR remains
the only camera owner; this module asks its local snapshot endpoint for a frame
and sends that frame to the local CodeProject.AI face-recognition API.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, replace

import requests


@dataclass(frozen=True)
class FaceSnapshot:
    names: tuple[str, ...] = ()
    unknown_present: bool = False
    last_success: float = 0.0
    camera_ready: bool = False
    error: str = ""
    recognized_since: tuple[tuple[str, float], ...] = ()

    @property
    def has_known_person(self) -> bool:
        # Fail closed: only a registered identity authorizes Whisper input.
        return self.camera_ready and bool(self.names) and not self.unknown_present


class FacePresence:
    """Poll the configured Agent DVR camera and keep the latest known faces."""

    def __init__(
        self,
        *,
        agent_snapshot_url: str = "http://127.0.0.1:8090/liveimage.jpg?oid=1&size=640x480",
        face_recognition_url: str = "http://127.0.0.1:32168/v1/vision/face/recognize",
        interval_seconds: float = 1.0,
        min_confidence: float = 0.60,
        stale_after_seconds: float = 3.0,
        request_timeout: tuple[float, float] = (2.0, 5.0),
    ) -> None:
        self.agent_snapshot_url = agent_snapshot_url
        self.face_recognition_url = face_recognition_url
        self.interval_seconds = interval_seconds
        self.min_confidence = min_confidence
        self.stale_after_seconds = stale_after_seconds
        self.request_timeout = request_timeout
        self._state = FaceSnapshot()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_error_log = 0.0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._poll_loop,
            name="AgentDVR-FacePresence",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def snapshot(self) -> FaceSnapshot:
        with self._lock:
            state = self._state
        if not state.last_success or time.monotonic() - state.last_success > self.stale_after_seconds:
            return FaceSnapshot(error=state.error or "face data is stale")
        return state

    def _poll_once(self, session: requests.Session) -> FaceSnapshot:
        image_response = session.get(
            self.agent_snapshot_url,
            timeout=self.request_timeout,
        )
        image_response.raise_for_status()
        content_type = image_response.headers.get("content-type", "").lower()
        if not content_type.startswith("image/") or not image_response.content:
            raise ValueError("Agent DVR returned no camera image")

        result_response = session.post(
            self.face_recognition_url,
            files={"image": ("camera.jpg", image_response.content, content_type)},
            data={"min_confidence": str(self.min_confidence)},
            timeout=self.request_timeout,
        )
        result_response.raise_for_status()
        result = result_response.json()
        if not result.get("success"):
            raise RuntimeError(result.get("error") or result.get("message") or "recognition failed")

        names = set()
        unknown_present = False
        for prediction in result.get("predictions", []):
            confidence = float(prediction.get("confidence", 0.0) or 0.0)
            name = prediction.get("userid") or prediction.get("userId")
            if name and str(name).strip().casefold() != "unknown" and confidence >= self.min_confidence:
                names.add(str(name).strip())
            else:
                unknown_present = True

        return FaceSnapshot(
            names=tuple(sorted(name for name in names if name)),
            unknown_present=unknown_present,
            last_success=time.monotonic(),
            camera_ready=True,
        )

    def _poll_loop(self) -> None:
        session = requests.Session()
        while not self._stop.is_set():
            started = time.monotonic()
            try:
                state = self._poll_once(session)
                with self._lock:
                    previous_names = self._state.names
                    previous_unknown = self._state.unknown_present
                    previous_since = dict(self._state.recognized_since)
                    if state.last_success - self._state.last_success > self.stale_after_seconds:
                        previous_since = {}
                    state = replace(state, recognized_since=tuple(
                        (name, previous_since.get(name, state.last_success)) for name in state.names
                    ))
                    self._state = state
                if state.names != previous_names or state.unknown_present != previous_unknown:
                    if state.unknown_present:
                        logging.info("Unknown face detected; grace period and authorization are managed by MainApp.")
                    if state.names:
                        logging.info("Faces recognized by CodeProject.AI: %s", ", ".join(state.names))
                    else:
                        logging.info("No registered face recognized; state forwarded to MainApp.")
            except Exception as exc:
                with self._lock:
                    self._state = FaceSnapshot(error=str(exc))
                now = time.monotonic()
                if now - self._last_error_log >= 10.0:
                    logging.warning(
                        "Face recognition unavailable; timeout managed by MainApp (Agent DVR camera 1 / CodeProject.AI): %s",
                        exc,
                    )
                    self._last_error_log = now

            elapsed = time.monotonic() - started
            self._stop.wait(max(0.0, self.interval_seconds - elapsed))

