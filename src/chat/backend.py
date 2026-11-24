"""JWT, WebSocket, and streamed audio handling for the backend."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

import aiohttp
import numpy as np
from reachy_mini import ReachyMini

from audio import speaker_samples
from config import INPUT_SAMPLE_RATE


@dataclass
class AudioFrame:
    """一段待播放的助手语音及其 WebSocket 响应元数据。

    One assistant audio chunk and its WebSocket response metadata.
    """

    response_id: int
    samples: np.ndarray
    last: bool


class BackendClient:
    """负责 JWT 登录和聊天 WebSocket 传输。

    Handle JWT login and the primary chat WebSocket transport.
    """

    def __init__(self) -> None:
        """读取后端设置并初始化连接状态。

        Load backend settings and initialize connection state.
        """
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
        """登录后端并建立带有聊天参数的 WebSocket 连接。

        Log in to the backend and open a WebSocket with chat parameters.
        """
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
        """在线程安全的发送锁内发送一条 JSON 消息。

        Send one JSON message while holding the transport send lock.
        """
        if self.ws is None or self.ws.closed:
            raise ConnectionError("Backend WebSocket is not connected")
        async with self._send_lock:
            await self.ws.send_json(payload)

    async def send_audio(self, pcm: bytes) -> None:
        """按客户端协议发送单声道 16-bit PCM 麦克风音频。

        Send mono 16-bit PCM microphone audio using the client protocol.
        """
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
        """将键入的备用文本作为转写消息发送到后端。

        Send typed fallback text to the backend as a transcription message.
        """
        await self.send_json(
            {"type": "transcription", "data": text, "time": time.time()}
        )

    async def send_command(
        self, name: str, data: dict | None = None, *, wait_for_ack: bool = True
    ) -> dict:
        """发送带唯一 ID 的控制命令，并可等待后端确认。

        Send a uniquely identified control command and optionally await its acknowledgement.
        """
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
        """通知后端结束当前聊天会话。

        Notify the backend that the current chat session should end.
        """
        await self.send_json({"type": "end_chat"})

    def resolve_command_ack(self, payload: dict) -> None:
        """使用匹配的确认消息唤醒等待中的命令。

        Resolve the matching pending command with its acknowledgement payload.
        """
        waiter = self._pending_commands.get(payload.get("id"))
        if waiter is not None and not waiter.done():
            waiter.set_result(payload)

    async def messages(self):
        """逐条产出 WebSocket 中有效的 JSON 对象消息。

        Yield valid JSON object messages received from the WebSocket.
        """
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
        """拒绝未完成的命令，并关闭 WebSocket 与 HTTP 会话。

        Fail pending commands and close the WebSocket and HTTP session.
        """
        for waiter in self._pending_commands.values():
            if not waiter.done():
                waiter.set_exception(ConnectionError("Backend connection closed"))
        self._pending_commands.clear()
        if self.ws is not None and not self.ws.closed:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()


class BackendConversation:
    """管理一次自动语音会话和助手语音播放队列。

    Manage one automatic voice conversation and its assistant audio queue.
    """

    def __init__(
        self,
        mini: ReachyMini,
        on_user_speech,
        on_assistant_response,
        on_user_text: Callable[[str], bool] | None = None,
    ) -> None:
        """保存机器人与活动回调，并初始化会话任务和音频队列。

        Store the robot and activity callbacks, then initialize session tasks and audio queues.
        """
        self.mini = mini
        self.backend = BackendClient()
        self.on_user_speech = on_user_speech
        self.on_assistant_response = on_assistant_response
        self.on_user_text = on_user_text or (lambda text: False)
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
        """连接后端、启动接收与播放任务，并启用自动对话模式。

        Connect to the backend, start reader and player tasks, and enable automatic chat mode.
        """
        await self.backend.connect()
        self.reader_task = asyncio.create_task(self._listen_backend())
        self.player_task = asyncio.create_task(self._play_audio())
        await self.backend.send_command("set_response_mode", {"mode": "automatic"})
        await self.backend.send_command("set_listening", {"state": "active"})
        self.audio_allowed.set()
        print("Conversation connected; speak naturally without pressing Enter.")

    async def send_audio(self, pcm: bytes) -> None:
        """仅在后端允许且会话仍有效时转发麦克风音频。

        Forward microphone audio only while the backend allows an active session.
        """
        if self.audio_allowed.is_set() and not self.done.is_set():
            await self.backend.send_audio(pcm)

    async def send_text(self, text: str) -> None:
        """把用户键入的文本转发为后端转写消息。

        Forward user-typed text as a backend transcription message.
        """
        await self.backend.send_transcription(text)

    async def _listen_backend(self) -> None:
        """持续读取后端消息，并在连接结束时通知播放队列。

        Read backend messages and notify the audio player when the connection ends.
        """
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
        """分派协议消息，处理转写、回复、音频和会话状态。

        Dispatch protocol messages for transcripts, replies, audio, and session state.
        """
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
                self.on_assistant_response()
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
        """显示用户转写并分类；命中本地指令后立即停止接收后端回复。

        Display the transcript, reset inactivity, and stop reading backend replies on a local command.
        """
        text = text.strip()
        if not text:
            return
        self.on_user_speech()
        if self.on_user_text(text):
            self.audio_allowed.clear()
            self.done.set()
        if text not in self.user_messages_seen:
            self.user_messages_seen.add(text)
            print(f"\nYou: {text}")

    async def _play_audio(self) -> None:
        """按序播放助手语音块，并回报 TTS 播放状态。

        Play assistant audio chunks in order and report TTS playback state.
        """
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
        """丢弃指定响应的待播音频，并向后端报告中断。

        Discard queued audio for cancelled responses and report playback interruption.
        """
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
        """停止会话任务，按需发结束命令并释放网络资源。

        Stop conversation tasks, optionally send the end command, and release network resources.
        """
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
