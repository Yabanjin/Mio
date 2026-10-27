"""Bounded background I/O; abandoning a turn never waits for its socket."""
import threading
import queue
from concurrent.futures import Future, TimeoutError


class TurnCancelled(Exception):
    pass


class CancellableWork:
    def __init__(self, name, capacity=2):
        self.name = name
        self.slots = threading.BoundedSemaphore(capacity)
        self.work = queue.Queue(maxsize=capacity)
        for index in range(capacity):
            threading.Thread(target=self._worker, name=f'{name}-{index}', daemon=True).start()

    def _worker(self):
        while True:
            operation, current, future = self.work.get()
            try:
                if not current():
                    raise TurnCancelled()
                future.set_result(operation())
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                self.slots.release()
                self.work.task_done()

    def run(self, operation, current):
        while current():
            if self.slots.acquire(timeout=0.025):
                break
        else:
            raise TurnCancelled()
        future = Future()

        self.work.put((operation, current, future))
        while current():
            try:
                result = future.result(timeout=0.025)
                if not current():
                    raise TurnCancelled()
                return result
            except TimeoutError:
                if future.done():
                    # A TimeoutError raised by the operation is not our poll timeout.
                    return future.result()
        raise TurnCancelled()
