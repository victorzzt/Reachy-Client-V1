"""Wake, reply-action, and sleep-pose control for Reachy Mini."""

from __future__ import annotations

import asyncio
import random

import numpy as np
from reachy_mini import ReachyMini


EMOTION_DATASET = "pollen-robotics/reachy-mini-emotions-library"
REPLY_ACTION_NAMES = ("cheerful1", "loving1", "laughing1")


def play_move_and_restore_pose(mini: ReachyMini, move) -> None:
    """播放一个无音效动作，并恢复到展开时的头部和天线姿势。

    Play a silent recorded move, then restore the awake head and antenna pose.
    """
    head_pose = np.asarray(mini.get_current_head_pose(), dtype=np.float64).copy()
    antennas = list(mini.get_present_antenna_joint_positions())
    try:
        mini.play_move(move, initial_goto_duration=0.5)
    finally:
        mini.goto_target(
            head=head_pose,
            antennas=antennas,
            body_yaw=None,
            duration=0.6,
        )


class ReachyMotionController:
    """串行管理 Reachy 的唤醒、回复动作和休眠转换。

    Serialize Reachy's wake, reply motions, and sleep transitions.
    """

    def __init__(self, mini: ReachyMini) -> None:
        """保存机器人连接，并初始化动作队列和当前姿态状态。

        Store the robot handle and initialize motion-task and pose state.
        """
        self.mini = mini
        self._wake_task: asyncio.Task | None = None
        self._action_tasks: set[asyncio.Task] = set()
        self._motion_lock = asyncio.Lock()
        self._emotion_library = None
        self._last_action_name: str | None = None
        self._motors_enabled = False
        self._awake = False
        self._leaving = False

    def start_wake(self) -> None:
        """启用电机并异步展开 Reachy 的头部。

        Enable the motors and extend Reachy's head asynchronously.
        """
        self._leaving = False
        self._wake_task = asyncio.create_task(self._wake())

    async def wait_until_awake(self) -> bool:
        """等待唤醒动作结束，并返回机器人是否已成功展开。

        Wait for the wake motion and report whether Reachy is awake.
        """
        if self._wake_task is not None:
            await asyncio.gather(self._wake_task, return_exceptions=True)
        return self._awake

    async def _wake(self) -> None:
        """执行 Reachy SDK 的唤醒姿态序列。

        Run the Reachy SDK wake-up pose sequence.
        """
        try:
            await asyncio.to_thread(self.mini.enable_motors)
            self._motors_enabled = True
            await asyncio.to_thread(self.mini.wake_up)
            self._awake = True
            print("Reachy is awake and ready.")
        except Exception as exc:
            print(f"\n[motion] Could not extend Reachy's head: {exc}")

    def schedule_reply_action(self) -> None:
        """为一条助手回复排入一个随机表情动作。

        Queue one random expression motion for an assistant reply.
        """
        if self._leaving:
            return
        task = asyncio.create_task(self._play_reply_action())
        self._action_tasks.add(task)
        task.add_done_callback(self._action_tasks.discard)

    async def _play_reply_action(self) -> None:
        """播放一个不带音效的随机表情动作，并串行保护机器人运动。

        Play one silent random expression while serializing robot motion.
        """
        if not await self.wait_until_awake() or self._leaving:
            return

        async with self._motion_lock:
            if self._leaving or not self._awake:
                return
            try:
                if self._emotion_library is None:
                    from reachy_mini.motion.recorded_move import RecordedMoves

                    self._emotion_library = await asyncio.to_thread(
                        RecordedMoves, EMOTION_DATASET
                    )

                candidates = tuple(
                    name
                    for name in REPLY_ACTION_NAMES
                    if name != self._last_action_name
                ) or REPLY_ACTION_NAMES
                action_name = random.choice(candidates)
                recorded_move = self._emotion_library.get(action_name)

                # 回复时不播放动作附带音效，避免覆盖 TTS 语音。
                # Omit the sidecar sound so the motion does not mask reply TTS.
                from reachy_mini.motion.recorded_move import RecordedMove

                silent_move = RecordedMove(recorded_move.move, sound_path=None)
                self._last_action_name = action_name
                print(f"\n[motion] Playing {action_name} with this reply.")
                await asyncio.to_thread(
                    play_move_and_restore_pose, self.mini, silent_move
                )
            except Exception as exc:
                print(f"\n[motion] Could not play a random reply action: {exc}")

    async def sleep(self) -> None:
        """等待动作完成、收起头部和天线，并禁用电机。

        Wait for motion to finish, tuck the head and antennas, and disable motors.
        """
        self._leaving = True
        await self.wait_until_awake()
        pending_actions = tuple(self._action_tasks)
        if pending_actions:
            await asyncio.gather(*pending_actions, return_exceptions=True)

        if self._motors_enabled:
            if self._awake:
                try:
                    await asyncio.to_thread(self.mini.goto_sleep)
                    print("Reachy returned to its sleep pose.")
                except Exception as exc:
                    print(f"\n[motion] Could not reach the sleep pose: {exc}")
            try:
                await asyncio.to_thread(self.mini.disable_motors)
            except Exception as exc:
                print(f"\n[motion] Could not disable the motors: {exc}")

        self._awake = False
        self._motors_enabled = False
        self._wake_task = None
        self._leaving = False
