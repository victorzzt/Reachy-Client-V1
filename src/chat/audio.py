"""Audio format conversion helpers for the Reachy Mini client."""

from __future__ import annotations

import base64

import numpy as np

from config import INPUT_SAMPLE_RATE


def microphone_pcm(sample: np.ndarray, sample_rate: int) -> bytes:
    """将 Reachy 的浮点麦克风采样转换为 16 kHz 单声道 s16le。

    Convert Reachy's float microphone samples to 16 kHz mono s16le.
    """
    samples = np.asarray(sample, dtype=np.float32)
    if samples.ndim == 2:
        samples = samples.mean(axis=1, dtype=np.float32)
    elif samples.ndim != 1:
        return b""

    if sample_rate <= 0 or samples.size == 0:
        return b""
    if sample_rate != INPUT_SAMPLE_RATE:
        target_length = max(1, round(samples.size * INPUT_SAMPLE_RATE / sample_rate))
        source_positions = np.arange(samples.size, dtype=np.float64) / sample_rate
        target_positions = np.arange(target_length, dtype=np.float64) / INPUT_SAMPLE_RATE
        samples = np.interp(target_positions, source_positions, samples).astype(np.float32)

    samples = np.clip(samples, -1.0, 1.0)
    return (samples * 32767.0).astype("<i2").tobytes()


def speaker_samples(payload: dict, output_rate: int) -> np.ndarray | None:
    """解码后端 16-bit PCM 语音块，转换为 Reachy 所需的浮点音频。

    Decode a backend 16-bit PCM TTS chunk for Reachy's float audio API.
    """
    try:
        raw = base64.b64decode(payload["b64"], validate=True)
        source_rate = int(payload.get("sampleRate", 24_000))
        channels = int(payload.get("channels", 1))
        bits_per_sample = int(payload.get("bitsPerSample", 16))
    except (KeyError, TypeError, ValueError) as exc:
        print(f"[audio] Ignoring malformed speech chunk: {exc}")
        return None

    if bits_per_sample != 16 or source_rate <= 0 or channels <= 0:
        print("[audio] Ignoring unsupported speech format")
        return None

    pcm = np.frombuffer(raw, dtype="<i2")
    if pcm.size == 0 or pcm.size % channels:
        return None
    if channels > 1:
        pcm = pcm.reshape(-1, channels).astype(np.float32).mean(axis=1)
    samples = pcm.astype(np.float32) / 32768.0

    if output_rate > 0 and source_rate != output_rate:
        target_length = max(1, round(samples.size * output_rate / source_rate))
        source_positions = np.arange(samples.size, dtype=np.float64) / source_rate
        target_positions = np.arange(target_length, dtype=np.float64) / output_rate
        samples = np.interp(target_positions, source_positions, samples).astype(np.float32)
    return samples.astype(np.float32, copy=False)
