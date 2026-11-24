#!/usr/bin/env python3
"""Wake-word gated, hands-free Reachy Mini conversation client."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import aiohttp
import numpy as np
from aiohttp.client_exceptions import ClientConnectorCertificateError
from dotenv import load_dotenv
from reachy_mini import ReachyMini

from wakeword import WakeWordDetector


APP_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = APP_DIR.parents[1] if APP_DIR.parent.name == "src" else APP_DIR
load_dotenv(APP_DIR / ".env")
if PROJECT_ROOT != APP_DIR:
    load_dotenv(PROJECT_ROOT / ".env", override=False)

INPUT_SAMPLE_RATE = 16_000
MIC_CHUNK_SAMPLES = 1_024  # 64 ms at 16 kHz, as in the Reachy protocol guide
CONVERSATION_TIMEOUT_SECONDS = float(
    os.getenv("CONVERSATION_TIMEOUT_SECONDS", "300")
)
SPEECH_RMS_THRESHOLD = float(os.getenv("SPEECH_RMS_THRESHOLD", "0.015"))
CONNECT_BUFFER_CHUNKS = 100  # bounded ~6.4 s pre-roll while opening the backend session


@dataclass
class AudioFrame:
    response_id: int
    samples: np.ndarray
    last: bool


class BackendClient:
    """JWT login and the primary chat WebSocket transport."""

    def __init__(self) -> None:
        self.base_url = os.getenv(
            "BASE_HTTP_URL", "https://sandbox2.cognibot.org"
        ).rstrip("/")
        self.ws_path = os.getenv("WS_PATH", "/ws/chat/")
        if not self.ws_path.startswith("/"):
            self.ws_path = "/" + self.ws_path
        self.source = os.getenv("SOURCE", "reachyrobot").strip().lower()
        if self.source != "reachyrobot":
            raise RuntimeError("This client requires SOURCE=reachyrobot")
        self.chat_type = os.getenv("CHAT_TYPE", "activity").strip()
        self.username = os.getenv("USERNAME")
        self.password = os.getenv("PASSWORD")
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._pending_commands: dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        if not self.username or not self.password:
            raise RuntimeError("Set USERNAME and PASSWORD in the chat .env file")

        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
        )
        async with self.session.post(
            f"{self.base_url}/api/token/",
            json={"username": self.username, "password": self.password},
        ) as response:
            if response.status != 200:
                raise RuntimeError(
                    f"Backend login failed ({response.status}): {await response.text()}"
                )
            token_data = await response.json()

        access_token = token_data.get("access")
        if not access_token:
            raise RuntimeError("Backend login response did not contain an access token")

        base = urlsplit(self.base_url)
        scheme = "wss" if base.scheme == "https" else "ws"
        query = urlencode(
            {
                "token": access_token,
                "source": self.source,
                "chat_type": self.chat_type,
            }
        )
        websocket_url = f"{scheme}://{base.netloc}{self.ws_path}?{query}"
        self.ws = await self.session.ws_connect(
            websocket_url,
            headers={"Origin": self.base_url},
            heartbeat=20,
        )

    async def send_json(self, payload: dict) -> None:
        if self.ws is None or self.ws.closed:
            raise ConnectionError("Backend WebSocket is not connected")
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def send_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        await self.send_json(
            {
                "type": "audio_data",
                "data": base64.b64encode(pcm).decode("ascii"),
                "sampleRate": INPUT_SAMPLE_RATE,
                "channels": 1,
                "bitsPerSample": 16,
                "encoding": "pcm_s16le",
            }
        )

    async def send_transcription(self, text: str) -> None:
        await self.send_json(
            {"type": "transcription", "data": text, "time": time.time()}
        )

    async def send_command(
        self, name: str, data: dict | None = None, *, wait_for_ack: bool = True
    ) -> dict:
        command_id = uuid4().hex
        command = {"id": command_id, "name": name}
        if data is not None:
            command["data"] = data

        waiter = None
        if wait_for_ack:
            waiter = asyncio.get_running_loop().create_future()
            self._pending_commands[command_id] = waiter

        try:
            await self.send_json({"type": "command", "data": command})
            if waiter is None:
                return {}
            ack = await asyncio.wait_for(waiter, timeout=8)
            if not ack.get("ok"):
                raise RuntimeError(ack.get("message") or f"Backend rejected {name}")
            return ack
        finally:
            self._pending_commands.pop(command_id, None)

    async def send_end_chat(self) -> None:
        await self.send_json({"type": "end_chat"})

    def resolve_command_ack(self, payload: dict) -> None:
        waiter = self._pending_commands.get(payload.get("id"))
        if waiter is not None and not waiter.done():
            waiter.set_result(payload)

    async def messages(self):
        if self.ws is None:
            return
        async for message in self.ws:
            if message.type == aiohttp.WSMsgType.TEXT:
                try:
                    payload = json.loads(message.data)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict):
                    yield payload
            elif message.type == aiohttp.WSMsgType.ERROR:
                raise ConnectionError(f"WebSocket error: {self.ws.exception()}")

    async def close(self) -> None:
        for waiter in self._pending_commands.values():
            if not waiter.done():
                waiter.set_exception(ConnectionError("Backend connection closed"))
        self._pending_commands.clear()
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()


def microphone_pcm(sample: np.ndarray, sample_rate: int) -> bytes:
    """Convert Reachy's float microphone samples to 16 kHz mono s16le."""
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
    """Decode a backend 16-bit PCM TTS chunk for Reachy's float audio API."""
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


class BackendConversation:
    """One automatic Reachy conversation: microphone PCM in, backend TTS out."""

    def __init__(self, mini: ReachyMini, on_user_speech) -> None:
        self.mini = mini
        self.backend = BackendClient()
        self.on_user_speech = on_user_speech
        self.output_rate = mini.media.get_output_audio_samplerate()
        self.audio_allowed = asyncio.Event()
        self.done = asyncio.Event()
        self.audio_queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
        self.user_messages_seen: set[str] = set()
        self.cancelled_responses: set[int] = set()
        self.started_responses: set[int] = set()
        self.current_response_id: int | None = None
        self.reader_task: asyncio.Task | None = None
        self.player_task: asyncio.Task | None = None
        self.reader_error: Exception | None = None

    async def start(self) -> None:
        await self.backend.connect()
        self.reader_task = asyncio.create_task(self._listen_backend())
        self.player_task = asyncio.create_task(self._play_audio())
        await self.backend.send_command("set_response_mode", {"mode": "automatic"})
        await self.backend.send_command("set_listening", {"state": "active"})
        self.audio_allowed.set()
        print("Conversation connected; speak naturally without pressing Enter.")

    async def send_audio(self, pcm: bytes) -> None:
        if self.audio_allowed.is_set() and not self.done.is_set():
            await self.backend.send_audio(pcm)

    async def send_text(self, text: str) -> None:
        await self.backend.send_transcription(text)

    async def _listen_backend(self) -> None:
        try:
            async for payload in self.backend.messages():
                await self._handle_message(payload)
                if self.done.is_set():
                    return
        except Exception as exc:
            self.reader_error = exc
            print(f"\n[backend] Conversation disconnected: {exc}")
        finally:
            self.done.set()
            await self.audio_queue.put(None)

    async def _handle_message(self, payload: dict) -> None:
        message_type = payload.get("type")
        data = payload.get("data")

        if message_type == "command_ack" and isinstance(data, dict):
            self.backend.resolve_command_ack(data)
        elif message_type == "user_utt" and isinstance(data, str):
            self._show_user_text(data)
        elif message_type == "message" and isinstance(data, dict):
            if data.get("role") == "user":
                self._show_user_text(str(data.get("content", "")))
        elif message_type == "llm_response":
            text = data.get("text", "") if isinstance(data, dict) else data
            if text:
                print(f"\nReachy: {text}")
        elif message_type == "audio_chunk" and isinstance(data, dict):
            response_id = data.get("responseId")
            if type(response_id) is not int or response_id in self.cancelled_responses:
                return
            samples = speaker_samples(data, self.output_rate)
            if samples is not None:
                await self.audio_queue.put(
                    AudioFrame(
                        response_id=response_id,
                        samples=samples,
                        last=data.get("last") is True,
                    )
                )
        elif message_type == "cancel_audio":
            await self._cancel_audio(data if isinstance(data, dict) else {})
        elif message_type == "stream_status" and isinstance(data, dict):
            if data.get("status") == "paused":
                self.audio_allowed.clear()
            elif data.get("status") == "active":
                self.audio_allowed.set()
        elif message_type == "chat_ended":
            print("\nThe backend ended this conversation.")
            self.done.set()
        elif message_type == "robot_action":
            action = data if isinstance(data, dict) else {}
            print(f"\n[robot action] {action.get('kind')}: {action.get('value')}")

    def _show_user_text(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.on_user_speech()
        if text not in self.user_messages_seen:
            self.user_messages_seen.add(text)
            print(f"\nYou: {text}")

    async def _play_audio(self) -> None:
        try:
            while True:
                frame = await self.audio_queue.get()
                try:
                    if frame is None:
                        return
                    if frame.response_id in self.cancelled_responses:
                        continue

                    if frame.response_id not in self.started_responses:
                        self.started_responses.add(frame.response_id)
                        await self.backend.send_json(
                            {
                                "type": "tts_playback",
                                "data": {
                                    "responseId": frame.response_id,
                                    "state": "started",
                                },
                            }
                        )

                    self.current_response_id = frame.response_id
                    self.mini.media.push_audio_sample(frame.samples)
                    if self.output_rate > 0:
                        await asyncio.sleep(frame.samples.size / self.output_rate)
                    if frame.response_id in self.cancelled_responses:
                        continue

                    if frame.last:
                        await self.backend.send_json(
                            {
                                "type": "tts_playback",
                                "data": {
                                    "responseId": frame.response_id,
                                    "state": "finished",
                                },
                            }
                        )
                        self.current_response_id = None
                finally:
                    self.audio_queue.task_done()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"\n[audio] Playback failed: {exc}")
            self.reader_error = exc
            self.done.set()

    async def _cancel_audio(self, data: dict) -> None:
        response_ids = data.get("responseIds")
        if isinstance(response_ids, list):
            cancelled = {value for value in response_ids if isinstance(value, int)}
        else:
            cancelled = set(self.started_responses)
            if self.current_response_id is not None:
                cancelled.add(self.current_response_id)
        self.cancelled_responses.update(cancelled)

        retained: list[AudioFrame | None] = []
        while True:
            try:
                frame = self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            self.audio_queue.task_done()
            if frame is not None and frame.response_id not in cancelled:
                retained.append(frame)
        for frame in retained:
            await self.audio_queue.put(frame)

        if cancelled:
            self.mini.media.stop_playing()
            self.mini.media.start_playing()
            for response_id in cancelled & self.started_responses:
                await self.backend.send_json(
                    {
                        "type": "tts_playback",
                        "data": {
                            "responseId": response_id,
                            "state": "interrupted",
                        },
                    }
                )
            if self.current_response_id in cancelled:
                self.current_response_id = None

    async def close(self, *, send_end_chat: bool) -> None:
        self.audio_allowed.clear()
        if send_end_chat and self.backend.ws is not None and not self.backend.ws.closed:
            try:
                await self.backend.send_end_chat()
            except Exception:
                pass
            self.mini.media.stop_playing()
            self.mini.media.start_playing()

        self.done.set()
        await self.audio_queue.put(None)
        tasks = [task for task in (self.reader_task, self.player_task) if task]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.backend.close()


class VoiceInteractionApp:
    """Local wake standby plus an automatic, hands-free WebSocket session."""

    def __init__(self, mini: ReachyMini, wakeword: WakeWordDetector) -> None:
        self.mini = mini
        self.wakeword = wakeword
        self.input_rate = mini.media.get_input_audio_samplerate()
        self.state = "standby"
        self.session: BackendConversation | None = None
        self.connect_task: asyncio.Task | None = None
        self.preroll: deque[bytes] = deque(maxlen=CONNECT_BUFFER_CHUNKS)
        self.last_user_speech_at = 0.0
        self.stop_requested = False
        self.command_queue: queue.Queue[str] = queue.Queue()
        self._doa_unavailable = False
        if CONVERSATION_TIMEOUT_SECONDS <= 0:
            raise ValueError("CONVERSATION_TIMEOUT_SECONDS must be greater than 0")

    async def run(self) -> None:
        threading.Thread(
            target=read_console,
            args=(self.command_queue,),
            daemon=True,
        ).start()
        print(
            "Standby: say 'Reachy' to start. Speak naturally for follow-up turns; "
            "five minutes without speech returns to standby. Ctrl+C or /quit exits."
        )

        try:
            while not self.stop_requested:
                await self._handle_console_input()
                await self._finish_connection_if_ready()
                await self._check_session_state()

                sample = await asyncio.to_thread(self.mini.media.get_audio_sample)
                if sample is None:
                    await asyncio.sleep(0.01)
                    continue

                pcm = microphone_pcm(sample, self.input_rate)
                if not pcm:
                    continue

                if self.state == "active" and self._speech_detected(sample):
                    self._mark_user_speech()

                await self._process_audio(pcm)
        finally:
            if self.connect_task is not None and not self.connect_task.done():
                self.connect_task.cancel()
                await asyncio.gather(self.connect_task, return_exceptions=True)
            if self.session is not None:
                await self._leave_session("process stopped", send_end_chat=True)

    async def _process_audio(self, pcm: bytes) -> None:
        chunk_bytes = MIC_CHUNK_SAMPLES * 2
        for offset in range(0, len(pcm), chunk_bytes):
            frame = pcm[offset : offset + chunk_bytes]
            if self.state == "standby":
                detected, trailing_audio = self.wakeword.feed(frame)
                if detected:
                    print("\nWake word detected. Starting conversation...")
                    self.state = "connecting"
                    self.last_user_speech_at = time.monotonic()
                    self.preroll.clear()
                    if trailing_audio:
                        self._buffer_preroll(trailing_audio)
                    remainder = pcm[offset + len(frame) :]
                    if remainder:
                        self._buffer_preroll(remainder)
                    self.connect_task = asyncio.create_task(self._connect_session())
                    return
            elif self.state == "connecting":
                self._buffer_preroll(frame)
            elif self.state == "active" and self.session is not None:
                try:
                    await self.session.send_audio(frame)
                except Exception as exc:
                    print(f"\n[backend] Could not send microphone audio: {exc}")
                    self.session.done.set()
                    return

    def _buffer_preroll(self, pcm: bytes) -> None:
        chunk_bytes = MIC_CHUNK_SAMPLES * 2
        for offset in range(0, len(pcm), chunk_bytes):
            if len(self.preroll) == self.preroll.maxlen:
                print("\n[backend] Connection slow; dropping oldest wake pre-roll audio")
            self.preroll.append(pcm[offset : offset + chunk_bytes])

    async def _connect_session(self) -> BackendConversation:
        session = BackendConversation(self.mini, self._mark_user_speech)
        try:
            await session.start()
            return session
        except Exception:
            await session.close(send_end_chat=False)
            raise

    async def _finish_connection_if_ready(self) -> None:
        if self.state != "connecting" or self.connect_task is None:
            return
        if not self.connect_task.done():
            return

        task = self.connect_task
        self.connect_task = None
        try:
            self.session = task.result()
        except Exception as exc:
            print(f"\n[backend] Could not start conversation: {exc}")
            self._return_to_standby()
            return

        try:
            while self.preroll:
                await self.session.send_audio(self.preroll.popleft())
        except Exception as exc:
            print(f"\n[backend] Could not send buffered microphone audio: {exc}")
            await self._leave_session("audio stream failed", send_end_chat=True)
            return

        self.last_user_speech_at = time.monotonic()
        self.state = "active"

    async def _check_session_state(self) -> None:
        if self.state != "active" or self.session is None:
            return
        if self.session.done.is_set():
            reason = "backend ended the session"
            if self.session.reader_error is not None:
                reason = f"backend disconnected: {self.session.reader_error}"
            print(f"\n{reason}; returning to wake-word standby.")
            await self._leave_session(reason, send_end_chat=False)
            return

        idle_seconds = time.monotonic() - self.last_user_speech_at
        if idle_seconds >= CONVERSATION_TIMEOUT_SECONDS:
            print("\nFive minutes without speech; ending the chat and returning to standby.")
            await self._leave_session("inactivity timeout", send_end_chat=True)

    async def _leave_session(self, reason: str, *, send_end_chat: bool) -> None:
        session = self.session
        self.session = None
        if session is not None:
            if not send_end_chat:
                try:
                    await asyncio.wait_for(session.audio_queue.join(), timeout=20)
                except asyncio.TimeoutError:
                    pass
            await session.close(send_end_chat=send_end_chat)
        self._return_to_standby()

    def _return_to_standby(self) -> None:
        self.session = None
        self.connect_task = None
        self.preroll.clear()
        self.last_user_speech_at = 0.0
        self.wakeword.reset()
        self.state = "standby"
        print("\nStandby: say 'Reachy' to start another conversation.")

    def _mark_user_speech(self) -> None:
        self.last_user_speech_at = time.monotonic()

    def _speech_detected(self, sample: np.ndarray) -> bool:
        """Use the Reachy mic-array VAD, with a small RMS fallback."""
        try:
            _, detected = self.mini.media.get_DoA()
            return bool(detected)
        except Exception as exc:
            if not self._doa_unavailable:
                print(f"\n[voice activity] Reachy VAD unavailable; using RMS fallback: {exc}")
                self._doa_unavailable = True
            values = np.asarray(sample, dtype=np.float32)
            return bool(values.size and float(np.sqrt(np.mean(values * values))) >= SPEECH_RMS_THRESHOLD)

    async def _handle_console_input(self) -> None:
        while True:
            try:
                entry = self.command_queue.get_nowait().strip()
            except queue.Empty:
                return

            if entry.lower() in {"/q", "/quit", "/exit"}:
                self.stop_requested = True
                return
            if not entry:
                continue
            if self.state == "active" and self.session is not None:
                try:
                    await self.session.send_text(entry)
                    self._mark_user_speech()
                except Exception as exc:
                    print(f"\n[backend] Could not send typed text: {exc}")
            else:
                print("\nText input is available after saying 'Reachy'.")


def read_console(commands: queue.Queue[str]) -> None:
    while True:
        try:
            commands.put(input("\nType a fallback message while active, or /quit to exit\n> "))
        except EOFError:
            commands.put("/quit")
            return


async def async_main() -> None:
    wakeword = WakeWordDetector()
    print("Connecting to Reachy Mini audio...")
    with ReachyMini(media_backend="default") as mini:
        mini.media.start_recording()
        mini.media.start_playing()
        try:
            await VoiceInteractionApp(mini, wakeword).run()
        finally:
            mini.media.stop_recording()
            mini.media.stop_playing()


def main() -> None:
    try:
        asyncio.run(async_main())
    except ClientConnectorCertificateError as exc:
        print(
            "TLS certificate hostname mismatch. Set BASE_HTTP_URL in .env to the "
            "backend hostname covered by its certificate. For the current test "
            "backend, use https://sandbox2.cognibot.org. Certificate checks remain enabled."
        )
        print(f"Details: {exc}")
        raise SystemExit(1) from None
    except KeyboardInterrupt:
        print("\nChat stopped.")


if __name__ == "__main__":
    main()
