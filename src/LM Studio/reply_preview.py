"""Prepare at most one speech segment ahead, never authorize its playback."""
import logging
import threading


_CAPACITY = threading.BoundedSemaphore(1)


class ReplyPreview:
    def __init__(self, select, prepare, current):
        self.select = select
        self.prepare = prepare
        self.current = current
        self.cancelled = threading.Event()
        self.done = threading.Event()
        self.buffer = ''
        self.item = None
        self.result = None
        self.claimed = False
        self.decided = False

    def valid(self):
        return not self.cancelled.is_set() and self.current()

    def feed(self, content):
        if self.decided or not content or not self.valid():
            return
        self.buffer += content
        try:
            item = self.select(self.buffer)
        except Exception:
            self.decided = True
            logging.warning('Speculative preparation skipped: segmentation unavailable.', exc_info=True)
            return
        if item is None:
            return
        self.decided = True
        self.buffer = ''
        if not _CAPACITY.acquire(blocking=False):
            return  # Never delay the LLM or queue speculative work.
        self.item = item
        try:
            threading.Thread(target=self._run, name='Mio-First-Voice', daemon=True).start()
        except Exception:
            self.item = None
            _CAPACITY.release()
            logging.warning('Speculative preparation unavailable; normal path retained.', exc_info=True)

    def _run(self):
        try:
            if self.valid():
                result = self.prepare(self.item, current=self.valid)
                if self.valid():
                    self.result = result
        except Exception:
            if self.valid():
                logging.warning('Speculative preparation failed; normal processing resumes after validation.', exc_info=True)
        finally:
            self.done.set()
            _CAPACITY.release()

    def claim(self, item):
        # Called only after full response validation. Exact text/language/turn match.
        if self.item is not None and self.item[:3] == item[:3] and self.valid():
            self.claimed = True
            return self
        self.cancel()
        return None

    def wait(self):
        while self.valid():
            if self.done.wait(.025):
                return self.result if self.valid() else None
        return None

    def cancel(self):
        self.cancelled.set()
        self.buffer = ''
