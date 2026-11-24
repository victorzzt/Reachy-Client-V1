"""Shared configuration for the Reachy Mini conversation client."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1] if APP_DIR.parent.name == "src" else APP_DIR
load_dotenv(APP_DIR / ".env")
if PROJECT_ROOT != APP_DIR:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

INPUT_SAMPLE_RATE = 16_000
MIC_CHUNK_SAMPLES = 1_024  # 64 ms at 16 kHz
CONVERSATION_TIMEOUT_SECONDS = float(
    os.getenv("CONVERSATION_TIMEOUT_SECONDS", "300")
)
SPEECH_RMS_THRESHOLD = float(os.getenv("SPEECH_RMS_THRESHOLD", "0.015"))
CONNECT_BUFFER_CHUNKS = 100  # bounded ~6.4 s wake pre-roll



