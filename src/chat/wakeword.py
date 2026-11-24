"""Local, privacy-preserving Reachy wake-word detection."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

import numpy as np


APP_DIR = Path(__file__).resolve().parent
MODEL_NAME = "reechy-spk150-steps100k-acc98.15-rec97.50.onnx"
MODEL_URL = (
    "https://raw.githubusercontent.com/andyjmorgan/reachy-wake-word/"
    f"main/models/{MODEL_NAME}"
)
MODEL_SHA256 = "bcd551a49315e443b11877ff52e11f30e42ecdf024b6c051dcaad80faee1e14f"
MODEL_FRAME_SAMPLES = 1_280  # 80 ms at 16 kHz


def configured_model_path() -> tuple[Path, bool]:
    configured = os.getenv("WAKEWORD_MODEL_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = APP_DIR / path
        return path, False
    return APP_DIR / "models" / MODEL_NAME, True


def ensure_default_model(path: Path) -> None:
    """Download the pinned model once, then verify it before loading."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != MODEL_SHA256:
            raise RuntimeError(
                f"Wake-word model checksum mismatch at {path}; remove it and retry"
            )
        return

    temporary_path = path.with_name(path.name + ".download")
    digest = hashlib.sha256()
    try:
        print(f"Downloading local Reachy wake-word model to {path}...")
        with urlopen(MODEL_URL, timeout=60) as response, temporary_path.open("wb") as output:
            while block := response.read(64 * 1024):
                output.write(block)
                digest.update(block)
        if digest.hexdigest() != MODEL_SHA256:
            raise RuntimeError("Downloaded wake-word model checksum did not match")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


class WakeWordDetector:
    """Detect the spoken name locally; standby audio is never uploaded."""

    def __init__(self) -> None:
        model_path, is_default = configured_model_path()
        if is_default:
            ensure_default_model(model_path)
        elif not model_path.is_file():
            raise FileNotFoundError(f"WAKEWORD_MODEL_PATH does not exist: {model_path}")

        try:
            from openwakeword.model import Model
        except ImportError as exc:
            raise RuntimeError(
                "Wake-word detection needs openWakeWord; install src/chat/requirements.txt "
                "in /venvs/apps_venv"
            ) from exc

        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
        )
        self.threshold = float(os.getenv("WAKEWORD_THRESHOLD", "0.5"))
        self.required_hits = int(os.getenv("WAKEWORD_REQUIRED_HITS", "2"))
        if not 0.0 < self.threshold <= 1.0:
            raise ValueError("WAKEWORD_THRESHOLD must be greater than 0 and at most 1")
        if self.required_hits < 1:
            raise ValueError("WAKEWORD_REQUIRED_HITS must be at least 1")

        self._pcm_buffer = bytearray()
        self._consecutive_hits = 0

    def feed(self, pcm_s16le: bytes) -> tuple[bool, bytes]:
        """Return (detected, audio-after-detection) for mono 16 kHz PCM."""
        self._pcm_buffer.extend(pcm_s16le)
        frame_bytes = MODEL_FRAME_SAMPLES * 2

        while len(self._pcm_buffer) >= frame_bytes:
            frame = bytes(self._pcm_buffer[:frame_bytes])
            del self._pcm_buffer[:frame_bytes]
            samples = np.frombuffer(frame, dtype="<i2")
            scores = self._model.predict(samples)
            score = max((float(value) for value in scores.values()), default=0.0)
            if score >= self.threshold:
                self._consecutive_hits += 1
            else:
                self._consecutive_hits = 0

            if self._consecutive_hits >= self.required_hits:
                trailing_audio = bytes(self._pcm_buffer)
                self.reset()
                return True, trailing_audio

        return False, b""

    def reset(self) -> None:
        self._pcm_buffer.clear()
        self._consecutive_hits = 0
        self._model.reset()
