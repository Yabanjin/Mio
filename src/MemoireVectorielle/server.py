"""Local vector memory for short, explicitly stated facts from Mio's users."""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import json
import os
import re
from pathlib import Path
import sqlite3
import threading
import time

import numpy as np
ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
os.environ["CUDA_VISIBLE_DEVICES"] = CONFIG["gpu_uuid"]
import onnxruntime as ort
ort.preload_dlls(directory="")
from fastembed import TextEmbedding
from memory_policy import normalized, legacy_state, legacy_subject, evidence_state, entity_key, CORRECTION, PROPERTY_MARKERS


DATABASE = ROOT.parent.parent / "data" / "memory" / "souvenirs.sqlite3"
DATABASE.parent.mkdir(parents=True, exist_ok=True)
MODEL = TextEmbedding(model_name=CONFIG["model"], cache_dir=os.environ.get('MIO_MEMORY_MODELS', str(ROOT / "models")), local_files_only=True,
                      threads=max(1, int(CONFIG.get("cpu_threads", 2))),
                      providers=[("CUDAExecutionProvider", {"device_id": 0, "arena_extend_strategy": "kSameAsRequested"})])
if "CUDAExecutionProvider" not in MODEL.model.model.get_providers():
    raise RuntimeError("Memory CUDA requested but unavailable")
print("Vector memory CUDA ready on " + CONFIG["gpu_uuid"], flush=True)
MODEL_LOCK = threading.Lock()
DB_LOCK = threading.Lock()
READ_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="Memory-Read")
SCHEMA_READY = False


def database():
    global SCHEMA_READY
    connection = sqlite3.connect(DATABASE, timeout=10)
    if SCHEMA_READY:
        return connection
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY,
        context TEXT NOT NULL,
        fact TEXT NOT NULL,
        normalized_fact TEXT NOT NULL,
        vector BLOB NOT NULL,
        created_at INTEGER NOT NULL,
        UNIQUE(context, normalized_fact)
    )""")
    connection.execute("""CREATE TABLE IF NOT EXISTS memory_details (
        memory_id INTEGER PRIMARY KEY, entity TEXT NOT NULL DEFAULT '',
        property_name TEXT NOT NULL DEFAULT '', source_text TEXT NOT NULL DEFAULT '',
        source_id TEXT NOT NULL DEFAULT '', voice_names TEXT NOT NULL DEFAULT '[]',
        source_time INTEGER, state TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
        superseded_by INTEGER, FOREIGN KEY(memory_id) REFERENCES memories(id)
    )""")
    for memory_id, fact in connection.execute(
        'SELECT id, fact FROM memories WHERE id NOT IN (SELECT memory_id FROM memory_details)'
    ).fetchall():
        state, reason = legacy_state(fact)
        entity, property_name = legacy_subject(fact) if state == 'legacy' else ('', '')
        connection.execute('INSERT INTO memory_details(memory_id,state,reason,entity,property_name) VALUES (?,?,?,?,?)',
                           (memory_id, state, reason, entity, property_name))
    connection.execute('CREATE INDEX IF NOT EXISTS memory_details_state ON memory_details(state)')
    connection.commit()
    SCHEMA_READY = True
    return connection


@lru_cache(maxsize=int(CONFIG.get("embedding_cache_size", 128)))
def embed(text):
    with MODEL_LOCK:
        vector = np.asarray(next(MODEL.embed([text])), dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if not norm:
        raise ValueError("Vecteur vide")
    normalized = vector / norm
    normalized.setflags(write=False)
    return normalized


def remember(context, fact, evidence=None):
    fact = " ".join(fact.split()).strip()
    if not 8 <= len(fact) <= int(CONFIG["max_fact_chars"]):
        raise ValueError("Invalid memory length")
    if context not in {"Normal", "Adult", "Child", "Mio", "Family"}:
        raise ValueError("Unknown context")
    evidence = evidence or {}
    source = str(evidence.get('source_text', ''))
    entity = str(evidence.get('entity', '')).strip()[:100]
    property_name = str(evidence.get('property', ''))
    if source and normalized(fact) not in normalized(source):
        raise ValueError('Quote not found in the source')
    state, reason = evidence_state(
        fact, entity, property_name, evidence.get('durable') is True,
        mio_addressee=context == 'Mio' and evidence.get('entity_basis') == 'mio_addressee')
    if not source:
        state, reason = 'review', 'source absente'
    vector = embed(fact)
    with DB_LOCK, closing(database()) as db:
        with db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO memories(context, fact, normalized_fact, vector, created_at) VALUES (?, ?, ?, ?, ?)",
                (context, fact, fact.casefold(), vector.tobytes(), int(time.time())),
            )
            stored = bool(cursor.rowcount)
            if stored:
                memory_id = cursor.lastrowid
                voice_names = [str(n)[:100] for n in evidence.get('voice_names', [])
                               if str(n).casefold() not in {'unknown', 'inconnu'}][:4]
                db.execute('''INSERT INTO memory_details
                    (memory_id,entity,property_name,source_text,source_id,voice_names,source_time,state,reason)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (memory_id, entity, property_name, source[:16000], str(evidence.get('source_id', ''))[:100],
                     json.dumps(voice_names, ensure_ascii=False), evidence.get('source_time'), state, reason))
                # Only explicit corrections to a single-valued, evidenced property replace a fact.
                # Other statements coexist; no semantic guess silently deletes a memory.
                # Mio has multiple avatars: a correction may concern only one appearance.
                multi_avatar = entity_key(entity) in {'mio', 'ミオ'} and property_name in {'hair_color', 'eye_color'}
                if state == 'active' and property_name in PROPERTY_MARKERS and CORRECTION.search(fact) and not multi_avatar:
                    candidates = db.execute('''SELECT d.memory_id,d.entity FROM memory_details d
                        JOIN memories m ON m.id=d.memory_id
                        WHERE d.state IN ('active','legacy') AND d.property_name=? AND m.context=? AND d.memory_id<>?''',
                        (property_name, context, memory_id)).fetchall()
                    for previous_id, previous_entity in candidates:
                        if entity_key(previous_entity) == entity_key(entity):
                            db.execute("UPDATE memory_details SET state='superseded',superseded_by=?,reason=? WHERE memory_id=?",
                                       (memory_id, 'explicit correction retained with its source', previous_id))
            else:
                state, reason = db.execute('''SELECT d.state,d.reason FROM memory_details d
                    JOIN memories m ON m.id=d.memory_id WHERE m.context=? AND m.normalized_fact=?''',
                    (context, fact.casefold())).fetchone()
            return {'stored': stored, 'state': state, 'reason': reason}


def read_memories(context):
    contexts = (context, "Mio", "Family")
    with DB_LOCK, closing(database()) as db:
        return db.execute(
            "SELECT m.context,m.fact,m.vector,m.id,m.created_at,d.entity,d.property_name,d.state "
            "FROM memories m JOIN memory_details d ON d.memory_id=m.id "
            "WHERE m.context IN (?, ?, ?) AND m.id >= ? AND d.state IN ('active','legacy')",
            (*contexts, int(CONFIG.get("first_active_id", 1))),
        ).fetchall()


def search(context, query):
    if context not in {"Normal", "Adult", "Child", "Mio", "Family"}:
        raise ValueError("Unknown context")
    if not 1 <= len(query) <= 2000:
        raise ValueError("Invalid query")
    # Independent work overlaps; keep the existing model and SQLite locks.
    rows_future = READ_WORKERS.submit(read_memories, context)
    try:
        vector = embed(query)
        rows = rows_future.result()
    except BaseException:
        rows_future.cancel()
        raise
    results = []
    for saved_context, fact, blob, memory_id, created_at, entity, property_name, state in rows:
        saved = np.frombuffer(blob, dtype=np.float32)
        if saved.shape != vector.shape:
            continue
        score = float(np.dot(vector, saved))
        if score >= float(CONFIG["min_similarity"]):
            results.append({"context": saved_context, "fact": fact, "score": round(score, 3),
                            "id": memory_id, "created_at": created_at, 'entity': entity,
                            'property': property_name, 'state': state})
    results.sort(key=lambda item: (item['score'], item['created_at'], item['id']), reverse=True)
    # Only typography-equivalent duplicates: similar wording can contain a conflicting value.
    chosen = []
    for item in results:
        wording = re.sub(r'[^\w]+', ' ', normalized(item['fact'])).strip()
        duplicate = False
        for prior in chosen:
            if not item['entity'] or (entity_key(item['entity']), item['property']) != (entity_key(prior['entity']), prior['property']):
                continue
            other = re.sub(r'[^\w]+', ' ', normalized(prior['fact'])).strip()
            if wording == other:
                duplicate = True
        if not duplicate:
            chosen.append(item)
        if len(chosen) >= int(CONFIG['max_results']):
            break
    return chosen


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"service": "MemoireVectorielle", "ready": True, "model": CONFIG["model"], 'memory_protocol': 2})
        elif self.path == '/review':
            with DB_LOCK, closing(database()) as db:
                rows = db.execute('''SELECT m.id,m.context,m.fact,d.reason FROM memories m
                    JOIN memory_details d ON d.memory_id=m.id WHERE d.state='review' ORDER BY m.id''').fetchall()
            self.reply(200, {'memories': [dict(zip(('id','context','fact','reason'), row)) for row in rows]})
        else:
            self.reply(404, {"error": "Unknown route"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 1 <= length <= 131072:
                raise ValueError("Invalid request size")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/search":
                self.reply(200, {"memories": search(str(payload["context"]), str(payload["query"]))})
            elif self.path == "/remember":
                self.reply(200, remember(str(payload["context"]), str(payload["fact"]), payload.get('evidence')))
            else:
                self.reply(404, {"error": "Unknown route"})
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
            self.reply(400, {"error": str(error)})
        except Exception as error:
            self.reply(500, {"error": str(error)})

    def log_message(self, format_string, *args):
        print("[MemoireVectorielle] " + format_string % args, flush=True)


if __name__ == "__main__":
    with closing(database()):
        pass
    print("Local vector memory ready.", flush=True)
    ThreadingHTTPServer((CONFIG["host"], int(CONFIG["port"])), Handler).serve_forever()
