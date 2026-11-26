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
FEATURE_MODEL_SPECS = {
    "melspectrogram": (
        "https://github.com/dscripka/openWakeWord/releases/download/"
        "v0.5.1/melspectrogram.onnx",
        "ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f",
    ),
    "embedding_model": (
        "https://github.com/dscripka/openWakeWord/releases/download/"
        "v0.5.1/embedding_model.onnx",
        "70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f",
    ),
}
MODEL_FRAME_SAMPLES = 1_280  # 80 ms at 16 kHz


def configured_model_path() -> tuple[Path, bool]:
    """读取唤醒模型路径设置，并指出是否使用默认模型。

    Read the configured wake-word model path and indicate whether it is the default.
    """
    configured = os.getenv("WAKEWORD_MODEL_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = APP_DIR / path
        return path, False
    return APP_DIR / "models" / MODEL_NAME, True


def ensure_verified_download(path: Path, url: str, expected_sha256: str) -> None:
    """下载固定版本的 ONNX 模型，并在使用前校验 SHA-256。

    Download a pinned ONNX model once, then verify it before loading.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != expected_sha256:
            raise RuntimeError(
                f"Model checksum mismatch at {path}; replace it with the pinned model"
            )
        return

    temporary_path = path.with_name(path.name + ".download")
    digest = hashlib.sha256()
    try:
        print(f"Downloading ONNX model to {path}...")
        with urlopen(url, timeout=60) as response, temporary_path.open("wb") as output:
            while block := response.read(64 * 1024):
                output.write(block)
                digest.update(block)
        if digest.hexdigest() != expected_sha256:
            raise RuntimeError(f"Downloaded model checksum did not match for {path.name}")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def ensure_default_model(path: Path) -> None:
    """下载并校验默认的 Reachy 唤醒词模型。

    Download and verify the default Reachy wake-word model.
    """
    ensure_verified_download(path, MODEL_URL, MODEL_SHA256)


def ensure_feature_models() -> tuple[Path, Path]:
    """确保 openWakeWord 的 ONNX 特征模型位于应用目录。

    Ensure openWakeWord's ONNX feature models are stored beside the app.
    """
    directory = APP_DIR / "models" / "openwakeword"
    paths = {}
    for name, (url, sha256) in FEATURE_MODEL_SPECS.items():
        path = directory / f"{name}.onnx"
        ensure_verified_download(path, url, sha256)
        paths[name] = path
    return paths["melspectrogram"], paths["embedding_model"]


class WakeWordDetector:
    """在本机检测唤醒词；待机音频不会上传。

    Detect the spoken name locally; standby audio is never uploaded.
    """

    def __init__(self) -> None:
        """加载并配置 ONNX 模型及连续命中阈值。

        Load and configure the ONNX models and consecutive-hit threshold.
        """
        model_path, is_default = configured_model_path()
        if is_default:
            ensure_default_model(model_path)
        elif not model_path.is_file():
            raise FileNotFoundError(f"WAKEWORD_MODEL_PATH does not exist: {model_path}")

        try:
            from openwakeword.model import Model
        except ImportError as exc:
            if (
                Path("/venvs/apps_venv").is_dir()
                and Path("/venvs/mini_daemon").is_dir()
            ):
                install_hint = (
                    "install it in the Reachy OS environment with "
                    "`/venvs/apps_venv/bin/pip install --no-deps "
                    "openwakeword==0.6.0`"
                )
            else:
                install_hint = (
                    "install it in the active host Conda environment; run "
                    "`conda activate reachy_mini_env`, then "
                    "`python -m pip install --no-deps openwakeword==0.6.0`"
                )
            raise RuntimeError(
                f"Wake-word detection needs openWakeWord; {install_hint}."
            ) from exc

        melspectrogram_path, embedding_model_path = ensure_feature_models()
        self._model = Model(
            wakeword_models=[str(model_path)],
            inference_framework="onnx",
            melspec_model_path=str(melspectrogram_path),
            embedding_model_path=str(embedding_model_path),
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
        """处理单声道 16 kHz PCM，并返回检测结果及剩余音频。

        Process mono 16 kHz PCM and return detection status plus trailing audio.
        """
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
        """清除音频缓冲区、连续命中计数和模型内部状态。

        Clear the audio buffer, consecutive-hit counter, and model state.
        """
        self._pcm_buffer.clear()
        self._consecutive_hits = 0
        self._model.reset()
