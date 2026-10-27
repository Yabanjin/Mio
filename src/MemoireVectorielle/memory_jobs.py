"""Persistent pending extractions; source IDs make replay idempotent."""
import json
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from pathlib import Path


class MemoryJobs:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.session = uuid.uuid4().hex
        with self.lock, closing(self.connect()) as db, db:
            db.execute('''CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, generation INTEGER NOT NULL,
                context TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                retry_at REAL NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '')''')
            db.execute("UPDATE jobs SET status='pending' WHERE status='running'")

    def connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def put(self, payload, generation):
        job_id = uuid.uuid4().hex
        with self.lock, closing(self.connect()) as db, db:
            db.execute('INSERT INTO jobs(id,session,generation,context,payload,created) VALUES(?,?,?,?,?,?)',
                       (job_id, self.session, generation, payload['context'], json.dumps(payload, ensure_ascii=False), time.time()))
        return job_id

    def take(self, size=2):
        with self.lock, closing(self.connect()) as db, db:
            rows = db.execute("SELECT id,session,generation,context,payload,created FROM jobs WHERE status='pending' ORDER BY created LIMIT ?", (size,)).fetchall()
            selected = []
            for job_id, session, generation, context, raw, created in rows:
                if selected and context != selected[0]['context']:
                    break
                retry_at = db.execute('SELECT retry_at FROM jobs WHERE id=?', (job_id,)).fetchone()[0]
                if retry_at > time.time():
                    break  # FIFO even after a temporary service error.
                selected.append({**json.loads(raw), 'id': job_id, 'session': session,
                                 'generation': generation, 'created': created})
                db.execute("UPDATE jobs SET status='running' WHERE id=?", (job_id,))
            return selected

    def valid(self, job):
        with self.lock, closing(self.connect()) as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (job['id'],)).fetchone()
            return bool(row and row[0] in {'pending', 'running'})

    def cancel(self, generation):
        with self.lock, closing(self.connect()) as db, db:
            db.execute("UPDATE jobs SET status='cancelled' WHERE session=? AND generation<=? AND status IN ('pending','running')",
                       (self.session, generation))

    def finish(self, job, status='done', error=''):
        with self.lock, closing(self.connect()) as db, db:
            db.execute("UPDATE jobs SET status=?,error=? WHERE id=? AND status='running'", (status, error[:300], job['id']))

    def retry(self, job, error='', interrupted=False):
        with self.lock, closing(self.connect()) as db, db:
            db.execute("""UPDATE jobs SET status='pending',error=?,attempts=attempts+?,retry_at=?
                          WHERE id=? AND status='running'""",
                       (error[:300], 0 if interrupted else 1, time.time() + (0 if interrupted else 15), job['id']))

    def next_delay(self):
        """None means empty: wake only on enqueue/cancel/close."""
        with self.lock, closing(self.connect()) as db:
            row = db.execute("SELECT retry_at FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            return max(0.0, row[0] - time.time()) if row else None

    def statistics(self):
        with self.lock, closing(self.connect()) as db:
            count, oldest = db.execute("SELECT count(*),min(created) FROM jobs WHERE status IN ('pending','running')").fetchone()
            return count, max(0, time.time() - oldest) if oldest else 0
