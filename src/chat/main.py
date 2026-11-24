#!/usr/bin/env python3
"""Reachy Mini voice chat client for the Dementia Speech System backend."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import aiohttp
import numpy as np
from dotenv import load_dotenv
from reachy_mini import ReachyMini


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

INPUT_SAMPLE_RATE = 16_000
MIC_CHUNK_SAMPLES = 1_024  # 64 ms at 16 kHz


@dataclass
class AudioFrame:
    response_id: int
    samples: np.ndarray
    last: bool


class BackendClient:
    """JWT login and primary-chat WebSocket transport."""

    def __init__(self) -> None:
        self.base_url = os.getenv("BASE_HTTP_URL", "https://cognibot.org").rstrip("/")
        self.ws_path = os.getenv("WS_PATH", "/ws/chat/")
        if not self.ws_path.startswith("/"):
            self.ws_path = "/" + self.ws_path
        self.source = os.getenv("SOURCE", "reachyrobot").strip().lower()
        if self.source != "reachyrobot":
            raise RuntimeError("This Reachy Mini client requires SOURCE=reachyrobot")
        self.username = os.getenv("USERNAME")
        self.password = os.getenv("PASSWORD")
        self.session: aiohttp.ClientSession | None = None
        self.ws: aiohttp.ClientWebSocketResponse | None = None
        self._send_lock = asyncio.Lock()
        self._pending_commands: dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        if not self.username or not self.password:
            raise RuntimeError("Set USERNAME and PASSWORD in the project-root .env file")

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
        query = urlencode({"token": access_token, "source": self.source})
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


class VoiceChat:
    def __init__(self, mini: ReachyMini) -> None:
        self.mini = mini
        self.backend = BackendClient()
        self.output_rate = mini.media.get_output_audio_samplerate()
        self.input_rate = mini.media.get_input_audio_samplerate()
        self.capture_enabled = asyncio.Event()
        self.stop_event = asyncio.Event()
        self.audio_queue: asyncio.Queue[AudioFrame | None] = asyncio.Queue()
        self.user_messages_seen: set[str] = set()
        self.audio_started: set[int] = set()
        self.cancelled_responses: set[int] = set()
        self.speech_active = False
        self._reader_error: Exception | None = None
        self._reader_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.backend.connect()
        self._reader_task = asyncio.create_task(self.listen_backend())
        print("Connected to the conversation service.")
        await self.backend.send_command("set_response_mode", {"mode": "manual"})
        await self.backend.send_command("set_listening", {"state": "active"})
        self.capture_enabled.set()
        print("Speak, then press Enter to send. Type a message to send text; /q ends chat.")

    async def capture_microphone(self) -> None:
        while not self.stop_event.is_set():
            sample = await asyncio.to_thread(self.mini.media.get_audio_sample)
            if sample is None:
                await asyncio.sleep(0.01)
                continue
            if not self.capture_enabled.is_set():
                continue

            pcm = microphone_pcm(sample, self.input_rate)
            if not pcm:
                continue
            bytes_per_chunk = MIC_CHUNK_SAMPLES * 2
            for offset in range(0, len(pcm), bytes_per_chunk):
                if not self.capture_enabled.is_set() or self.stop_event.is_set():
                    break
                await self.backend.send_audio(pcm[offset : offset + bytes_per_chunk])

    async def listen_backend(self) -> None:
        try:
            async for payload in self.backend.messages():
                await self.handle_message(payload)
                if self.stop_event.is_set():
                    return
        except Exception as exc:
            self._reader_error = exc
            print(f"\n[backend] Connection ended: {exc}")
        finally:
            self.stop_event.set()
            await self.audio_queue.put(None)

    async def handle_message(self, payload: dict) -> None:
        message_type = payload.get("type")
        data = payload.get("data")

        if message_type == "command_ack" and isinstance(data, dict):
            self.backend.resolve_command_ack(data)
        elif message_type == "message" and isinstance(data, dict):
            if data.get("role") == "user":
                text = str(data.get("content", "")).strip()
                if text and text not in self.user_messages_seen:
                    self.user_messages_seen.add(text)
                    print(f"\nYou: {text}")
        elif message_type == "user_utt" and isinstance(data, str):
            text = data.strip()
            if text and text not in self.user_messages_seen:
                self.user_messages_seen.add(text)
                print(f"\nYou: {text}")
        elif message_type == "llm_response":
            text = data.get("text", "") if isinstance(data, dict) else data
            if text:
                print(f"\nReachy: {text}")
            self.speech_active = True
            self.capture_enabled.clear()
            await self.backend.send_command(
                "set_listening", {"state": "paused"}, wait_for_ack=False
            )
            response_id = payload.get("responseId")
            if isinstance(response_id, int):
                asyncio.create_task(self.resume_if_audio_missing(response_id))
        elif message_type == "audio_chunk" and isinstance(data, dict):
            response_id = data.get("responseId")
            if not isinstance(response_id, int) or response_id in self.cancelled_responses:
                return
            samples = speaker_samples(data, self.output_rate)
            if samples is None:
                return
            self.speech_active = True
            self.capture_enabled.clear()
            await self.audio_queue.put(
                AudioFrame(response_id=response_id, samples=samples, last=data.get("last") is True)
            )
        elif message_type == "cancel_audio":
            await self.cancel_audio(data if isinstance(data, dict) else {})
        elif message_type == "stream_status" and isinstance(data, dict):
            if data.get("status") == "paused":
                self.capture_enabled.clear()
            elif data.get("status") == "active" and not self.speech_active:
                self.capture_enabled.set()
        elif message_type == "chat_ended":
            print("\nThe conversation has ended.")
            self.stop_event.set()
        elif message_type == "robot_action":
            action = data if isinstance(data, dict) else {}
            print(f"\n[robot action] {action.get('kind')}: {action.get('value')}")

    async def resume_if_audio_missing(self, response_id: int) -> None:
        await asyncio.sleep(20)
        if response_id not in self.audio_started and self.speech_active:
            print("\n[ audio ] No speech audio arrived; resuming the microphone.")
            await self.resume_listening()

    async def playback_audio(self) -> None:
        started_responses: set[int] = set()
        try:
            while True:
                frame = await self.audio_queue.get()
                try:
                    if frame is None:
                        return
                    if frame.response_id in self.cancelled_responses:
                        continue

                    if frame.response_id not in started_responses:
                        started_responses.add(frame.response_id)
                        self.audio_started.add(frame.response_id)
                        await self.backend.send_json(
                            {
                                "type": "tts_playback",
                                "data": {"responseId": frame.response_id, "state": "started"},
                            }
                        )

                    self.mini.media.push_audio_sample(frame.samples)
                    if self.output_rate > 0:
                        await asyncio.sleep(frame.samples.size / self.output_rate)

                    if frame.last:
                        await self.backend.send_json(
                            {
                                "type": "tts_playback",
                                "data": {"responseId": frame.response_id, "state": "finished"},
                            }
                        )
                        self.speech_active = False
                        await self.resume_listening()
                finally:
                    self.audio_queue.task_done()
        except Exception as exc:
            print(f"\n[audio] Playback failed: {exc}")
            self.stop_event.set()

    async def cancel_audio(self, data: dict) -> None:
        response_ids = data.get("responseIds")
        if not isinstance(response_ids, list):
            response_ids = list(self.audio_started)
        cancelled = {item for item in response_ids if isinstance(item, int)}
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
            for response_id in cancelled & self.audio_started:
                await self.backend.send_json(
                    {
                        "type": "tts_playback",
                        "data": {"responseId": response_id, "state": "interrupted"},
                    }
                )
            self.speech_active = False
            await self.resume_listening()

    async def resume_listening(self) -> None:
        await self.backend.send_command(
            "set_listening", {"state": "active"}, wait_for_ack=False
        )
        self.capture_enabled.set()

    async def run_console(self) -> None:
        commands: queue.Queue[str] = queue.Queue()
        threading.Thread(target=read_console, args=(commands,), daemon=True).start()

        while not self.stop_event.is_set():
            try:
                entry = commands.get_nowait().strip()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue

            if entry.lower() in {"/q", "/quit", "/exit"}:
                self.capture_enabled.clear()
                try:
                    await self.backend.send_command(
                        "set_listening", {"state": "paused"}, wait_for_ack=False
                    )
                    await self.backend.send_end_chat()
                except (ConnectionError, RuntimeError):
                    pass
                self.stop_event.set()
                break

            if entry:
                self.capture_enabled.clear()
                await self.backend.send_command(
                    "set_listening", {"state": "paused"}, wait_for_ack=False
                )
                await self.backend.send_transcription(entry)

            try:
                await self.backend.send_command("reply_now")
            except Exception as exc:
                print(f"\n[backend] Could not request a reply: {exc}")
                self.capture_enabled.set()

    async def run(self) -> None:
        tasks: list[asyncio.Task] = []
        try:
            await self.start()
            tasks = [
                asyncio.create_task(self.capture_microphone()),
                self._reader_task,
                asyncio.create_task(self.playback_audio()),
            ]
            await self.run_console()
            if self._reader_error is None:
                try:
                    await asyncio.wait_for(self.audio_queue.join(), timeout=3)
                except asyncio.TimeoutError:
                    pass
        finally:
            self.stop_event.set()
            for task in tasks:
                if task is not None:
                    task.cancel()
            if self._reader_task is not None and self._reader_task not in tasks:
                self._reader_task.cancel()
                tasks.append(self._reader_task)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await self.backend.close()


def read_console(commands: queue.Queue[str]) -> None:
    while True:
        try:
            commands.put(input("\nEnter = send speech | text = send text | /q = end chat\n> "))
        except EOFError:
            commands.put("/q")
            return


async def async_main() -> None:
    print("Connecting to Reachy Mini audio...")
    with ReachyMini(media_backend="default") as mini:
        mini.media.start_recording()
        mini.media.start_playing()
        try:
            await VoiceChat(mini).run()
        finally:
            mini.media.stop_recording()
            mini.media.stop_playing()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        print("\nChat stopped.")


if __name__ == "__main__":
    main()
