"""Wake-word state machine and user-facing conversation loop."""

from __future__ import annotations

import asyncio
import queue
import threading
import time
from collections import deque

import numpy as np
from reachy_mini import ReachyMini

from audio import microphone_pcm
from backend import BackendConversation
from config import (
    CONNECT_BUFFER_CHUNKS,
    CONVERSATION_TIMEOUT_SECONDS,
    MIC_CHUNK_SAMPLES,
    SPEECH_RMS_THRESHOLD,
)
from motion import ReachyMotionController
from wakeword import WakeWordDetector


class VoiceInteractionApp:
    """管理本地唤醒待机、免按键语音会话及超时退出。

    Manage local wake standby, hands-free voice chat, and inactivity timeouts.
    """

    def __init__(self, mini: ReachyMini, wakeword: WakeWordDetector) -> None:
        """保存机器人与唤醒检测器，并初始化会话状态。

        Store the robot and wake-word detector, then initialize conversation state.
        """
        self.mini = mini
        self.wakeword = wakeword
        self.input_rate = mini.media.get_input_audio_samplerate()
        self.state = "standby"
        self.session: BackendConversation | None = None
        self.connect_task: asyncio.Task | None = None
        self.motion = ReachyMotionController(mini)
        self.preroll: deque[bytes] = deque(maxlen=CONNECT_BUFFER_CHUNKS)
        self.last_user_speech_at = 0.0
        self.stop_requested = False
        self.command_queue: queue.Queue[str] = queue.Queue()
        self._doa_unavailable = False
        if CONVERSATION_TIMEOUT_SECONDS <= 0:
            raise ValueError("CONVERSATION_TIMEOUT_SECONDS must be greater than 0")

    async def run(self) -> None:
        """运行音频主循环，并在退出时关闭会话和动作控制。

        Run the audio loop and close the session and motion controller on exit.
        """
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
            else:
                await self.motion.sleep()

    async def _process_audio(self, pcm: bytes) -> None:
        """按状态处理音频：本地唤醒、连接预缓冲或实时上传。

        Route audio by state: local wake detection, connection pre-roll, or live upload.
        """
        chunk_bytes = MIC_CHUNK_SAMPLES * 2
        for offset in range(0, len(pcm), chunk_bytes):
            frame = pcm[offset : offset + chunk_bytes]
            if self.state == "standby":
                detected, trailing_audio = self.wakeword.feed(frame)
                if detected:
                    print("\nWake word detected. Starting conversation...")
                    self.state = "connecting"
                    self.motion.start_wake()
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
        """缓存连接期间的短音频块，避免丢失唤醒后的语音。

        Buffer short audio chunks during connection setup to preserve speech after wake-up.
        """
        chunk_bytes = MIC_CHUNK_SAMPLES * 2
        for offset in range(0, len(pcm), chunk_bytes):
            if len(self.preroll) == self.preroll.maxlen:
                print("\n[backend] Connection slow; dropping oldest wake pre-roll audio")
            self.preroll.append(pcm[offset : offset + chunk_bytes])

    async def _connect_session(self) -> BackendConversation:
        """创建并启动 WebSocket 会话及其用户活动回调。

        Create and start the WebSocket conversation with its user-activity callbacks.
        """
        session = BackendConversation(
            self.mini,
            self._mark_user_speech,
            self.motion.schedule_reply_action,
        )
        try:
            await session.start()
            return session
        except Exception:
            await session.close(send_end_chat=False)
            raise

    def _return_to_standby(self) -> None:
        """清理会话状态，重置唤醒检测并返回待机模式。

        Clear session state, reset wake detection, and return to standby.
        """
        self.session = None
        self.connect_task = None
        self.preroll.clear()
        self.last_user_speech_at = 0.0
        self.wakeword.reset()
        self.state = "standby"
        print("\nStandby: say 'Reachy' to start another conversation.")

    async def _finish_connection_if_ready(self) -> None:
        """收取连接结果，等待机器人展开并发送唤醒预缓冲音频。

        Collect the connection result, wait for wake motion, and send buffered audio.
        """
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
            await self.motion.sleep()
            self._return_to_standby()
            return

        await self.motion.wait_until_awake()

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
        """检查后端断开状态及用户静默超时。

        Check for backend disconnection and user inactivity timeout.
        """
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
        """关闭当前会话、收起机器人并回到唤醒待机。

        Close the current session, park Reachy, and return to wake-word standby.
        """
        session = self.session
        self.session = None
        if session is not None:
            if not send_end_chat:
                try:
                    await asyncio.wait_for(session.audio_queue.join(), timeout=20)
                except asyncio.TimeoutError:
                    pass
            await session.close(send_end_chat=send_end_chat)
        await self.motion.sleep()
        self._return_to_standby()

    def _mark_user_speech(self) -> None:
        """记录最近一次用户语音活动时间。

        Record the time of the most recent user speech activity.
        """
        self.last_user_speech_at = time.monotonic()

    def _speech_detected(self, sample: np.ndarray) -> bool:
        """优先使用麦克风阵列 VAD；不可用时回退到 RMS 音量检测。

        Use the Reachy mic-array VAD, with a small RMS fallback.
        """
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
        """处理退出指令，以及活动会话中的键盘备用文本。

        Handle quit commands and typed fallback text during an active session.
        """
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
    """在后台线程读取终端输入，并将内容送入异步主循环队列。

    Read terminal input on a background thread and enqueue it for the async loop.
    """
    while True:
        try:
            commands.put(input("\nType a fallback message while active, or /quit to exit\n> "))
        except EOFError:
            commands.put("/quit")
            return
