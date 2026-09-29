"""
object_detector.py — YOLO Object Detection Pipeline
====================================================

Uses YOLOv8n (ultralytics) to detect prohibited items in a live webcam frame.
The model is downloaded automatically on first run (~6 MB for YOLOv8n).

Monitored COCO classes:
    0   person        — extra person in the room
    67  cell phone    — mobile device
    73  book          — notebook / textbook
    63  laptop        — another computer / tablet

Usage:
    detector = ObjectDetector()
    detections = detector.detect(bgr_frame)   # returns list[Detection]

Requirements:
    pip install ultralytics
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional import
# ---------------------------------------------------------------------------

try:
    from ultralytics import YOLO as _YOLO
    AVAILABLE = True
    logger.info("ultralytics loaded — object detection enabled.")
except ImportError:
    _YOLO = None
    AVAILABLE = False
    logger.warning(
        "ultralytics not installed — object detection disabled.\n"
        "Install: pip install ultralytics"
    )


# ---------------------------------------------------------------------------
# COCO classes to watch
# ---------------------------------------------------------------------------

WATCHED_CLASSES = {
    0:  "person",
    67: "phone",
    73: "book",
    63: "laptop",
}

# Minimum confidence to report a detection
MIN_CONFIDENCE = 0.45

# Colours for bounding boxes — BGR
_BOX_COLORS = {
    "person": (0,   140, 255),   # orange
    "phone":  (0,    30, 220),   # red
    "book":   (30,  200, 230),   # yellow
    "laptop": (0,    30, 220),   # red
}


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------

@dataclass
class Detection:
    label:      str           # "person", "phone", "book", "laptop"
    confidence: float         # 0–1
    bbox:       Tuple[int, int, int, int]   # (x1, y1, x2, y2) pixel coords


@dataclass
class DetectionResult:
    available:    bool              = False
    detections:   List[Detection]   = field(default_factory=list)

    @property
    def has_phone(self) -> bool:
        return any(d.label == "phone" for d in self.detections)

    @property
    def has_extra_person(self) -> bool:
        # The student themselves will always be detected as 1 person.
        # Only flag when 2+ persons are visible (someone else entered frame).
        return sum(1 for d in self.detections if d.label == "person") > 1

    @property
    def has_book(self) -> bool:
        return any(d.label == "book" for d in self.detections)

    @property
    def has_laptop(self) -> bool:
        return any(d.label == "laptop" for d in self.detections)

    def labels(self) -> List[str]:
        seen = set()
        out  = []
        for d in self.detections:
            if d.label not in seen:
                seen.add(d.label)
                out.append(d.label.upper())
        return out


# ---------------------------------------------------------------------------
# ObjectDetector
# ---------------------------------------------------------------------------

class ObjectDetector:
    """
    Wraps YOLOv8n for real-time object detection.

    Call detect() every N frames (e.g. every 5) to keep CPU usage low.
    The last result is cached and available via `last_result`.
    """

    MODEL_NAME = "yolov8n.pt"   # nano model — fastest; auto-downloaded

    def __init__(self) -> None:
        self._model: Optional[object] = None
        self.last_result = DetectionResult(available=AVAILABLE)
        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not AVAILABLE:
            return
        try:
            self._model = _YOLO(self.MODEL_NAME)
            # Suppress ultralytics verbose output after first load
            self._model.overrides["verbose"] = False
            logger.info("YOLOv8n loaded (%s).", self.MODEL_NAME)
        except Exception as exc:
            logger.error("Failed to load YOLO model: %s", exc)
            self._model = None

    # ------------------------------------------------------------------

    def detect(self, bgr_frame: np.ndarray) -> DetectionResult:
        """
        Run YOLO on *bgr_frame* and return detections for watched classes.
        Also updates self.last_result.
        """
        if not AVAILABLE or self._model is None:
            return DetectionResult(available=False)

        try:
            results = self._model(
                bgr_frame,
                classes=list(WATCHED_CLASSES.keys()),
                conf=MIN_CONFIDENCE,
                verbose=False,
            )
        except Exception as exc:
            logger.debug("YOLO inference error: %s", exc)
            return self.last_result

        detections: List[Detection] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls.item())
                label  = WATCHED_CLASSES.get(cls_id)
                if label is None:
                    continue
                conf = float(box.conf.item())
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                detections.append(Detection(label=label, confidence=conf,
                                            bbox=(x1, y1, x2, y2)))

        self.last_result = DetectionResult(available=True, detections=detections)
        return self.last_result

    # ------------------------------------------------------------------

    @staticmethod
    def draw(canvas: np.ndarray, result: DetectionResult) -> None:
        """
        Draw bounding boxes and labels from *result* onto *canvas* in-place.
        Draws on the full-resolution original frame coordinates — call this
        BEFORE fitting the frame to the window, or pass the fitted canvas
        with scaled bbox (see draw_scaled).
        """
        if not result.available:
            return

        import cv2
        for det in result.detections:
            color = _BOX_COLORS.get(det.label, (200, 200, 200))
            x1, y1, x2, y2 = det.bbox
            # Box
            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            # Label background
            tag  = f"{det.label.upper()} {det.confidence:.0%}"
            (tw, th), bl = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.52, 1)
            cv2.rectangle(canvas, (x1, y1 - th - bl - 4), (x1 + tw + 4, y1), color, -1)
            cv2.putText(canvas, tag, (x1 + 2, y1 - bl - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

    @staticmethod
    def draw_scaled(
        canvas: np.ndarray,
        result: DetectionResult,
        orig_w: int, orig_h: int,
        disp_w: int, disp_h: int,
        offset_x: int = 0, offset_y: int = 0,
    ) -> None:
        """
        Draw bounding boxes scaled from original frame coords to display coords.
        Use this when the frame has been fitted/resized to the window.
        """
        if not result.available:
            return

        import cv2
        sx = disp_w / orig_w
        sy = disp_h / orig_h

        for det in result.detections:
            color = _BOX_COLORS.get(det.label, (200, 200, 200))
            x1 = int(det.bbox[0] * sx) + offset_x
            y1 = int(det.bbox[1] * sy) + offset_y
            x2 = int(det.bbox[2] * sx) + offset_x
            y2 = int(det.bbox[3] * sy) + offset_y

            cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
            tag  = f"{det.label.upper()} {det.confidence:.0%}"
            (tw, th), bl = cv2.getTextSize(tag, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
            cv2.rectangle(canvas, (x1, y1 - th - bl - 4), (x1 + tw + 4, y1), color, -1)
            cv2.putText(canvas, tag, (x1 + 2, y1 - bl - 2),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.48, (255, 255, 255), 1, cv2.LINE_AA)
