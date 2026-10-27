"""Bounded, cancellable STT windows. No microphone or playback ownership."""
from __future__ import annotations

import io
import logging
import queue
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import numpy as np
import requests
import soundfile as sf
from http_sessions import http_session


RATE = 16000


class Phrase:
    def __init__(self, generation, step, overlap, changed):
        self.step = step
        self.overlap = overlap
        self.changed = changed
        self.generation = generation
        self.lock = threading.Lock()
        self.chunks = []
        self.base = 0
        self.total = 0
        self.cut = 0
        self.finished = False
        self.closed = False
        self.words = []
        self.score_sum = 0.0
        self.token_count = 0
        self.languages = set()
        self.speakers = {}
        self.speaker_future = None
        self.trace_id = uuid.uuid4().hex[:8]
        self.finished_at = None

    def append(self, chunk):
        with self.lock:
            if not self.closed:
                audio = np.asarray(chunk, dtype=np.float32).reshape(-1).copy()
                self.chunks.append(audio)
                previous_total = self.total
                self.total += len(audio)
                # Notify only when a complete progressive window becomes ready.
                if previous_total < self.cut + self.step + self.overlap <= self.total:
                    self.changed.set()

    def close(self):
        with self.lock:
            self.closed = True
            self.chunks.clear()
            self.words.clear()
            if self.speaker_future:
                self.speaker_future.cancel()


class ProgressiveTranscriber:
    def __init__(self, url, config, current, speaker, publish, publish_details=None, consume_result=None):
        self.url = url
        self.root_url = url.split('/v1/')[0]
        self.config = config
        self.current = current
        self.speaker = speaker
        self.publish = publish
        self.publish_details = publish_details
        self.consume_result = consume_result
        self.session = uuid.uuid4().hex
        self.lock = threading.Lock()
        self.phrases = []
        self.results = queue.Queue(maxsize=int(config['utterance_queue_size']))
        self.closed = threading.Event()
        self.changed = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='Mio-Speaker')
        self.http_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='Mio-STT-HTTP')
        self.http_pending = []
        self.speaker_pending = None
        self.worker = threading.Thread(target=self._run, name='Mio-Turbo-Progressif', daemon=True)

    def start(self):
        self.worker.start()

    def _display(self, text, phrase, identity, complete):
        if self.publish_details is not None:
            try:
                self.publish_details(text, phrase.generation, phrase.trace_id, identity, complete)
            except Exception:
                logging.warning('Chat display unavailable; transcription retained.', exc_info=True)

    def begin(self, generation):
        with self.lock:
            self.phrases = [p for p in self.phrases if not p.closed]
            if len(self.phrases) >= int(self.config['utterance_queue_size']):
                raise RuntimeError('Progressive utterance queue full; no reply to incomplete audio')
            phrase = Phrase(generation, int(float(self.config["progressive_step_seconds"]) * RATE),
                            int(float(self.config["progressive_overlap_seconds"]) * RATE), self.changed)
            self.phrases.append(phrase)
        return phrase

    def finish(self, phrase):
        with phrase.lock:
            phrase.finished = True
            phrase.finished_at = time.monotonic()
        self.changed.set()

    def busy(self):
        with self.lock:
            return any(not p.closed for p in self.phrases) or not self.results.empty()

    def cancel(self, generation):
        with self.lock:
            for phrase in self.phrases:
                if phrase.generation <= generation:
                    phrase.close()
            self.phrases = [p for p in self.phrases if not p.closed]
            while True:
                try:
                    self.results.get_nowait()
                except queue.Empty:
                    break
        # Never perform HTTP on the Vosk/capture thread or under Mio's state lock.
        def notify():
            try:
                requests.post(self.root_url + '/cancel', json={'group': self.group(generation)}, timeout=(.5, 1))
            except requests.RequestException:
                logging.info('Local cancellation active; Turbo notification unavailable.')
        threading.Thread(target=notify, daemon=True, name='Mio-Annulation-Turbo').start()
        self.changed.set()

    def group(self, generation):
        return f'{self.session}:{generation}'

    def _valid(self, phrase):
        return not self.closed.is_set() and not phrase.closed and self.current(phrase.generation)

    def _snapshot(self, phrase):
        step = int(float(self.config['progressive_step_seconds']) * RATE)
        overlap = int(float(self.config['progressive_overlap_seconds']) * RATE)
        with phrase.lock:
            if phrase.closed:
                return None
            target = phrase.cut + step
            if not phrase.finished and phrase.total < target + overlap:
                return None
            end = min(phrase.total, target + overlap)
            final = phrase.finished and end == phrase.total
            start = max(phrase.base, phrase.cut - overlap)
            # Keep at most a bounded backlog, never silently drop speech.
            if phrase.total - phrase.base > int(float(self.config['progressive_backlog_seconds']) * RATE):
                raise RuntimeError('Turbo cannot keep up: maximum audio backlog exceeded')
            audio = np.concatenate(phrase.chunks) if phrase.chunks else np.empty(0, dtype=np.float32)
            window = audio[start - phrase.base:end - phrase.base].copy()
            return window, start, target, end, final

    @staticmethod
    def _wav(audio):
        buffer = io.BytesIO()
        sf.write(buffer, audio, RATE, format='WAV', subtype='PCM_16')
        return buffer.getvalue()

    def _collect_speakers(self, phrase, wait=0):
        future = phrase.speaker_future
        if future is None:
            return
        try:
            result = future.result(timeout=wait)
        except TimeoutError:
            return
        except Exception:
            result = {}
        phrase.speaker_future = None
        if not self._valid(phrase):
            return
        for entry in result.get('speakers', []):
            name = entry.get('name')
            if name and str(name).lower() not in {'unknown', 'inconnu'}:
                phrase.speakers[name] = entry

    def _identity(self, phrase):
        entries = list(phrase.speakers.values())
        family = [p for p in entries if p.get('role') != 'assistant']
        chosen = next((p for p in family if p.get('role') == 'child'), family[0] if family else {})
        return {**chosen, 'names': [p['name'] for p in family], 'speakers': entries,
                'authorized': bool(family), 'mio_only': bool(entries) and not family}

    def _http(self, phrase, url, **kwargs):
        """Abandon a stale HTTP wait immediately; at most two sockets survive.

        Server cancellation skips old queued jobs. One CUDA call may finish, but
        the acquisition/next turn never waits for the old HTTP read timeout.
        """
        while self._valid(phrase):
            self.http_pending = [f for f in self.http_pending if not f.done()]
            if len(self.http_pending) < 2:
                break
            self.closed.wait(.025)
        if not self._valid(phrase):
            return None
        future = self.http_pool.submit(lambda: http_session().post(url, **kwargs))
        self.http_pending.append(future)
        while self._valid(phrase):
            try:
                return future.result(timeout=.025)
            except TimeoutError:
                if future.done():
                    return future.result()
                continue
        future.cancel()
        return None

    def _process(self, phrase, snapshot):
        started = time.monotonic()
        audio, start, target, end, final = snapshot
        if not len(audio):
            self._complete(phrase)
            return
        payload = self._wav(audio)
        self._collect_speakers(phrase)
        # Bounded best-effort parallel work: no queue of stale identity requests.
        if phrase.speaker_future is None and (self.speaker_pending is None or self.speaker_pending.done()):
            phrase.speaker_future = self.pool.submit(self.speaker.identify, io.BytesIO(payload))
            self.speaker_pending = phrase.speaker_future
        result = None
        for attempt in range(2):
            if not self._valid(phrase):
                return
            try:
                response = self._http(phrase, self.url, files={'file': ('chunk.wav', payload, 'audio/wav')},
                                         data={'progressive': '1', 'group': self.group(phrase.generation)},
                                         timeout=(2, float(self.config['stt_timeout_seconds'])))
                if response is None:
                    return
                response.raise_for_status()
                result = response.json()
                response.close()
                if result.get('cancelled'):
                    return
                if result.get('confidence_method') != 'mean_token_probability':
                    raise ValueError('Turbo server lacks a compatible scoring protocol')
                if result.get('text') and not any(s.get('words') for s in result.get('segments', [])):
                    raise ValueError('Restart Turbo: aligned words are missing')
                break
            except (requests.RequestException, ValueError):
                if attempt:
                    raise
                logging.warning('Turbo chunk: first failure, retrying once.')
        if not self._valid(phrase):
            return
        logging.info('STT latency %s: %.2f s audio chunk processed in %.3f s; final=%s.',
                     phrase.trace_id, len(audio)/RATE, time.monotonic()-started, final)
        selected = []
        for segment in result.get('segments', []):
            for word in segment.get('words', []):
                word_end = start + round(float(word['end']) * RATE)
                word_start = start + round(float(word['start']) * RATE)
                midpoint = (word_start + word_end) / 2
                if midpoint <= phrase.cut or (not final and midpoint > target):
                    continue
                selected.append((word, word_end))
        with phrase.lock:
            if not self._valid(phrase):
                return
            for word, _ in selected:
                phrase.words.append(str(word['word']))
                phrase.score_sum += float(word['probability_sum'])
                phrase.token_count += int(word['token_count'])
            if selected:
                phrase.languages.add(str(result.get('detected_language', '')))
            # Commit at a word boundary. Keep the uncommitted tail and left context.
            phrase.cut = end if final else (selected[-1][1] if selected else target)
            overlap = int(float(self.config['progressive_overlap_seconds']) * RATE)
            keep = max(phrase.base, phrase.cut - overlap)
            all_audio = np.concatenate(phrase.chunks)
            phrase.chunks = [all_audio[keep - phrase.base:].copy()]
            phrase.base = keep
            preview = ''.join(phrase.words).strip()
        self._collect_speakers(phrase)
        if selected and self._valid(phrase):
            if self.publish_details is not None:
                self._display(preview, phrase, self._identity(phrase), False)
            else:
                self.publish(preview, phrase.generation)
        if final:
            self._collect_speakers(phrase, float(self.config['speaker_final_wait_seconds']))
            self._complete(phrase)

    def _complete(self, phrase):
        if not self._valid(phrase):
            return
        text = ''.join(phrase.words).strip()
        languages = phrase.languages - {''}
        language = next(iter(languages)) if len(languages) == 1 else 'mixed'
        if text:
            response = self._http(phrase, self.root_url + '/validate', json={'text': text, 'language': language},
                                     timeout=(2, float(self.config['stt_timeout_seconds'])))
            if response is None:
                return
            response.raise_for_status()
            language = response.json()['language']
            response.close()
        # Validation may take long enough for the pending identity to arrive.
        self._collect_speakers(phrase)
        if phrase.speaker_future is not None:
            logging.info('Speaker tags pending at finalization; text retained without late tags.')
        identity = self._identity(phrase)
        now = time.monotonic()
        identity['_timing'] = {'id':phrase.trace_id, 'finished_at':phrase.finished_at or now, 'finalized_at':now}
        logging.info('STT latency %s: end of utterance -> final text %.3f s.',
                     phrase.trace_id, now - (phrase.finished_at or now))
        result = (text, phrase.score_sum / phrase.token_count if phrase.token_count else 0.0,
                  language if text else '', identity, phrase.generation)
        if self._valid(phrase):
            logging.info('Turbo final: language %s, token score %.1f%%, names %s | %s',
                         result[2], result[1] * 100, result[3].get('names', []), text or 'no text')
            # Outside self.lock: a consumed control command may cancel the STT queue.
            if self.consume_result is not None and self.consume_result(result):
                phrase.close()
                return
            if self.publish_details is not None:
                self._display(text, phrase, identity, True)
        # Serializes enqueue against cancel(); stale results are also checked by main.
        with self.lock:
            if self._valid(phrase):
                self.results.put_nowait(result)
            phrase.close()

    def _run(self):
        while not self.closed.is_set():
            # Clear before inspecting state so a concurrent append/finish is never lost.
            self.changed.clear()
            worked = False
            with self.lock:
                phrases = list(self.phrases)
            for phrase in phrases:
                if not self._valid(phrase):
                    phrase.close()
                    continue
                try:
                    snapshot = self._snapshot(phrase)
                    if snapshot is None:
                        continue
                    worked = True
                    self._process(phrase, snapshot)
                except Exception:
                    if self._valid(phrase):
                        logging.exception('Progressive utterance explicitly discarded; no incomplete text sent to the LLM.')
                        if self.publish_details is not None:
                            self._display('Decoding interrupted; check the logs.', phrase,
                                          self._identity(phrase), 'error')
                    phrase.close()
                if self.closed.is_set():
                    break
            if not worked and not self.closed.is_set():
                self.changed.wait()

    def close(self):
        self.closed.set()
        with self.lock:
            for phrase in self.phrases:
                phrase.close()
        self.changed.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.http_pool.shutdown(wait=False, cancel_futures=True)
