"""One admitted Qwen request; conversation waiters precede memory jobs."""
import threading
from contextlib import contextmanager
from cancellable_work import TurnCancelled


class PriorityScheduler:
    def __init__(self):
        self.condition = threading.Condition()
        self.busy = False
        self.conversations = 0

    @contextmanager
    def acquire(self, current, *, memory=False, quiet=lambda: True):
        acquired = False
        with self.condition:
            if not memory:
                self.conversations += 1
            try:
                while current():
                    if not self.busy and (not memory or (not self.conversations and quiet())):
                        self.busy = acquired = True
                        break
                    self.condition.wait(.05)
                if not acquired:
                    raise TurnCancelled()
            finally:
                if not memory:
                    self.conversations -= 1
        try:
            yield
        finally:
            with self.condition:
                self.busy = False
                self.condition.notify_all()

    def conversation_waiting(self):
        with self.condition:
            return bool(self.conversations)


LLM_SCHEDULER = PriorityScheduler()
