#!/usr/bin/env python3
"""Entry point for the wake-word gated Reachy Mini conversation client."""

from __future__ import annotations

import asyncio

from aiohttp.client_exceptions import ClientConnectorCertificateError
from reachy_mini import ReachyMini

from interaction import VoiceInteractionApp
from wakeword import WakeWordDetector


async def async_main() -> None:
    """初始化唤醒检测和 Reachy 音频设备，然后运行交互客户端。

    Initialize wake detection and Reachy audio, then run the interaction client.
    """
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
    """启动异步客户端，并格式化常见 TLS 错误和 Ctrl+C 退出。

    Launch the async client and handle common TLS errors and Ctrl+C shutdown.
    """
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
