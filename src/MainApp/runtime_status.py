"""Process ownership and a fresh readiness acknowledgement for the BAT launcher."""

import json
import msvcrt
import os
import threading
import time
import uuid


class RuntimeStatus:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.lock_file = open(self.path + ".lock", "a+b")
        if os.path.getsize(self.path + ".lock") == 0:
            self.lock_file.write(b"0")
            self.lock_file.flush()
        self.lock_file.seek(0)
        try:
            msvcrt.locking(self.lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            self.lock_file.close()
            raise RuntimeError("A MainApp instance is already active") from None
        self.run_id = os.environ.get("MIO_RUN_ID") or uuid.uuid4().hex
        self.write_lock = threading.Lock()
        self.write(False, "Initialisation")

    def write(self, ready, reason="", failed=False):
        with self.write_lock:
            temporary = self.path + f".{os.getpid()}.tmp"
            with open(temporary, "w", encoding="utf-8") as target:
                json.dump({"pid": os.getpid(), "run_id": self.run_id, "ready": bool(ready),
                           "failed": bool(failed), "updated_at": time.time(), "reason": reason}, target)
            for attempt in range(10):
                try:
                    os.replace(temporary, self.path)
                    break
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.1)

    def close(self):
        self.lock_file.close()
