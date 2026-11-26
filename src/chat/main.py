#!/usr/bin/env python3
"""Entry point for the wake-word gated Reachy Mini conversation client."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

EXPECTED_PYTHON = (3, 12)


def is_reachy_os() -> bool:
    """识别 Reachy OS 标配的机器人应用和 daemon 虚拟环境。

    Detect the dedicated app and daemon environments shipped with Reachy OS.
    """
    return Path("/venvs/apps_venv").is_dir() and Path("/venvs/mini_daemon").is_dir()


def check_python_version(on_reachy_os: bool) -> None:
    """要求项目使用 Python 3.12，并给出对应环境的启动提示。

    Require Python 3.12 and show the appropriate environment hint.
    """
    if sys.version_info[:2] == EXPECTED_PYTHON:
        return

    current_version = f"{sys.version_info.major}.{sys.version_info.minor}"
    if on_reachy_os:
        hint = "Run this client with /venvs/apps_venv/bin/python."
    else:
        hint = "Did you forget to activate Conda? Run `conda activate reachy_mini_env`."
    print(f"Python 3.12 is required; current Python is {current_version}. {hint}")
    raise SystemExit(1)


async def async_main(on_reachy_os: bool) -> None:
    """初始化唤醒检测和 Reachy 音频设备，然后运行交互客户端。

    Initialize wake detection and Reachy audio, then run the interaction client.
    """
    from reachy_mini import ReachyMini

    from interaction import VoiceInteractionApp
    from wakeword import WakeWordDetector

    wakeword = WakeWordDetector()
    print("Connecting to Reachy Mini audio...")
    if on_reachy_os:
        mini_context = ReachyMini(media_backend="default")
    else:
        mini_context = ReachyMini(
            host="127.0.0.1",
            port=8000,
            connection_mode="network",
            media_backend="local",
        )

    with mini_context as mini:
        if not on_reachy_os:
            print("Connected to simulator over SSH tunnel")
        mini.media.start_recording()
        mini.media.start_playing()
        try:
            await VoiceInteractionApp(mini, wakeword).run()
        finally:
            mini.media.stop_recording()
            mini.media.stop_playing()


def main() -> None:
    """启动异步客户端，并格式化常见 TLS 错误和 Ctrl+C 退出。

    Launch the async client and handle common TLS errors and Ctrl+C shutdown.
    """
    on_reachy_os = is_reachy_os()
    check_python_version(on_reachy_os)

    from aiohttp.client_exceptions import ClientConnectorCertificateError

    try:
        asyncio.run(async_main(on_reachy_os))
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
