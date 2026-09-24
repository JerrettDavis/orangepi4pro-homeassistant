from __future__ import annotations
import time
from pathlib import Path
from .common import ApplianceError, atomic_json


class Presence:
    """Debounce positive frames and expire presence; stream failure means unavailable."""
    def __init__(self, hold: float = 20, hits: int = 2):
        self.hold, self.hits = hold, hits
        self.streak = 0
        self.last_seen: float | None = None

    def update(self, detected: bool, now: float, available: bool = True) -> bool:
        if not available:
            self.streak = 0
            self.last_seen = None
            return False
        self.streak = self.streak + 1 if detected else 0
        if self.streak >= self.hits:
            self.last_seen = now
        return self.last_seen is not None and now - self.last_seen <= self.hold


class HogDetector:
    def __init__(self, threshold: float = 0.6):
        try:
            import cv2
        except ImportError as exc:
            raise ApplianceError("Install python3-opencv for the CPU vision service") from exc
        cv2.setNumThreads(1)
        self.cv2, self.threshold = cv2, threshold
        self.hog = cv2.HOGDescriptor()
        self.hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())

    def detect(self, frame) -> int:
        h, w = frame.shape[:2]
        if h < 128 or w < 64:
            return 0
        if w > 640:
            frame = self.cv2.resize(frame, (640, max(128, int(h * 640 / w))))
        _, weights = self.hog.detectMultiScale(frame, winStride=(8, 8), padding=(8, 8), scale=1.08)
        return sum(float(weight) >= self.threshold for weight in weights)


def run_vision(cfg: dict) -> None:
    import cv2
    v = cfg["vision"]
    detector = HogDetector(v["threshold"])
    latch = Presence(v["hold_seconds"], v["hit_count"])
    output = Path(cfg["status_dir"]) / "vision.json"
    # Only go2rtc owns the camera. Detection consumes its localhost RTSP restream.
    source = "rtsp://127.0.0.1:8554/local"
    period = 1.0 / v["fps"]
    while True:
        atomic_json(output, {"timestamp": time.time(), "available": False, "person": False}, 0o644)
        capture = cv2.VideoCapture()
        try:
            opened = capture.open(source, cv2.CAP_FFMPEG,
                                  [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000, cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            if not opened:
                time.sleep(3)
                continue
            last_detection = 0.0
            while True:
                good, frame = capture.read()
                if not good:
                    break
                now = time.monotonic()
                # Drain the stream instead of sleeping with queued stale frames.
                if now - last_detection < period:
                    continue
                last_detection = now
                started = time.perf_counter()
                count = detector.detect(frame)
                present = latch.update(count > 0, now)
                atomic_json(output, {"timestamp": time.time(), "available": True, "person": present,
                                     "detections": count, "inference_ms": round((time.perf_counter() - started) * 1000, 2)}, 0o644)
        finally:
            capture.release()
            latch.update(False, time.monotonic(), available=False)
            atomic_json(output, {"timestamp": time.time(), "available": False, "person": False}, 0o644)
        time.sleep(2)
