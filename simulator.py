"""Automatic fake adult patients. No raw readings are written to disk."""
import hashlib
import math
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from client import send_reading


class FakePatient:
    def __init__(self, patient):
        seed = int.from_bytes(hashlib.sha256(patient['id'].encode()).digest()[:8], 'big')
        self.rng = random.Random(seed)
        self.baseline = [self.rng.uniform(68, 78), self.rng.uniform(97, 99), self.rng.uniform(13, 17)]
        self.current = self.baseline[:]
        self.period = self.rng.uniform(210, 330)
        self.delay = self.rng.uniform(35, 75)
        self.peak = self.rng.uniform(.65, 1.0)

    def reading(self, patient, now):
        elapsed = max(0, now - patient['created_at'] - self.delay)
        phase = elapsed % self.period
        # Smooth rising/falling episodes, separated by baseline periods.
        severity = self.peak * math.sin(math.pi * phase / 105) ** 2 if phase < 105 else 0
        targets = [self.baseline[0] + 90 * severity,
                   self.baseline[1] - 15 * severity,
                   self.baseline[2] + 17 * severity]
        noise = [.45, .08, .12]
        for i in range(3):
            self.current[i] += .22 * (targets[i] - self.current[i]) + self.rng.gauss(0, noise[i])
        return {'heart_rate': round(max(45, min(190, self.current[0])), 1),
                'oxygen_saturation': round(max(78, min(100, self.current[1])), 1),
                'respiratory_rate': round(max(8, min(40, self.current[2])), 1), 'age': patient['age']}


class Engine:
    def __init__(self, store, sender=send_reading):
        self.store, self.sender = store, sender
        self.lock = threading.RLock()
        self.latest = {}  # Only ONE latest reading per patient, RAM only.
        self.generators = {}
        self.generations = {}
        self.failures = set()
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name='fake-patients', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=30)

    def invalidate(self, pid):
        # Invalidates pending in-flight results on unplug, replug or removal.
        self.generations[pid] = self.generations.get(pid, 0) + 1
        self.latest.pop(pid, None)
        self.generators.pop(pid, None)
        self.failures.discard(pid)

    def run(self):
        if self.stop_event.wait(1):
            return
        while not self.stop_event.is_set():
            started = time.monotonic()
            try:
                self.tick()
            except Exception:
                # Never log payloads or raw readings. A failed cycle becomes stale.
                pass
            self.stop_event.wait(max(.2, 3 - (time.monotonic() - started)))

    def tick(self):
        with self.lock:
            patients = self.store.active()
            live_ids = {p['id'] for p in patients}
            for pid in list(self.latest):
                if pid not in live_ids:
                    self.invalidate(pid)
            jobs = []
            for p in patients:
                if not p['connected']:
                    continue
                if p['id'] not in self.generators:
                    self.generators[p['id']] = FakePatient(p)
                generator = self.generators[p['id']]
                now = time.time()
                jobs.append((p, generator.reading(p, now), now, self.generations.get(p['id'], 0)))
        if not jobs:
            return
        with ThreadPoolExecutor(max_workers=4) as pool:
            for p, vitals, measured_at, generation, result in pool.map(self.process, jobs):
                if self.stop_event.is_set():
                    return
                with self.lock:
                    if generation != self.generations.get(p['id'], 0):
                        continue
                    with self.store.connect() as db:
                        current = db.execute('SELECT * FROM patients WHERE id=? AND removed_at IS NULL AND connected=1', (p['id'],)).fetchone()
                        if current is None:
                            continue
                        if result is None and p['id'] not in self.failures:
                            self.store.event(db, current, 'INFERENCE_UNAVAILABLE')
                            self.failures.add(p['id'])
                        elif result is not None and p['id'] in self.failures:
                            self.store.event(db, current, 'INFERENCE_RESTORED')
                            self.failures.discard(p['id'])
                    if result is not None:
                        self.store.record_status(p['id'], result['status'])
                    self.latest[p['id']] = {'vitals': vitals, 'measured_at': measured_at,
                                            'status': result['status'] if result else 'OFFLINE'}

    def process(self, job):
        patient, vitals, measured_at, generation = job
        if self.stop_event.is_set():
            return patient, vitals, measured_at, generation, None
        try:
            result = self.sender(patient['id'], vitals, measured_at)
        except Exception:
            result = None
        return patient, vitals, measured_at, generation, result
