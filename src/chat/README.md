# Reachy Mini 对话客户端 / Reachy Mini Conversation Client

客户端启动后只在 Reachy 本机监听唤醒词 “Reachy”。待机音频只送入本地 openWakeWord 模型，不上传到后端；检测到唤醒词后才建立聊天 WebSocket。唤醒后无需每轮重复唤醒，直接连续说话即可。

At startup, the client listens for “Reachy” locally on the robot. Standby audio is processed only by the local openWakeWord model and is not uploaded. The chat WebSocket opens after the wake word is detected. Once awake, speak naturally across turns without repeating the wake word.

对话使用 WebSocket 的 `source=reachyrobot`、`chat_type=activity` 和 automatic response mode：麦克风音频以 16 kHz、单声道、16-bit PCM 的 `audio_data` 持续发送；后端返回的 `audio_chunk` 在同一连接上接收并由 Reachy 扬声器播放。用户转写和助手回复文字也会显示在终端，不需要按回车请求回复。

Conversation uses the WebSocket with `source=reachyrobot`, `chat_type=activity`, and automatic response mode. Microphone audio is continuously sent as 16 kHz mono 16-bit PCM `audio_data`; returned `audio_chunk` messages arrive on the same connection and play through Reachy's speaker. User transcripts and assistant text are also shown in the terminal, with no Enter needed to request a reply.

检测到 Reachy 麦克风阵列的语音活动或收到后端 `user_utt` 转写时，5 分钟静默计时会重置。5 分钟没有语音后，客户端发送 `end_chat` 并回到本地唤醒待机。Reachy SDK 的 `get_DoA()` 提供语音活动状态；不可用时客户端回退到可配置的音量阈值。

The five-minute silence timer resets when the Reachy microphone array detects speech or the backend sends a `user_utt` transcript. After five minutes without speech, the client sends `end_chat` and returns to local wake-word standby. The Reachy SDK's `get_DoA()` supplies speech activity; if unavailable, the client falls back to a configurable audio-level threshold.

## 配置与启动 / Configure and run

将目录放在 Reachy 的 `~/apps/chat/` 后，在该目录从 `.env.example` 创建 `.env` 并填写后端账号。测试后端地址应为 `https://sandbox2.cognibot.org`；如果现有 `.env` 仍填写 `https://cognibot.org`，需将 `BASE_HTTP_URL` 改为 sandbox2。不要关闭 TLS 证书校验。

Place this directory at `~/apps/chat/`, create `.env` from `.env.example`, and enter the backend credentials. The test backend URL is `https://sandbox2.cognibot.org`; change `BASE_HTTP_URL` to sandbox2 if an existing `.env` still says `https://cognibot.org`. Keep TLS certificate verification enabled.

```sh
cd ~/apps/chat
cp .env.example .env
nano .env
/venvs/apps_venv/bin/pip install -r requirements.txt
/venvs/apps_venv/bin/python main.py
```

默认模型会在首次启动时从其公开仓库下载到 `models/`，下载后会校验 SHA-256。若机器人无法访问 GitHub，可先在 `models/` 放入 `reechy-spk150-steps100k-acc98.15-rec97.50.onnx`，或通过 `WAKEWORD_MODEL_PATH` 指定已有模型。可用 `WAKEWORD_THRESHOLD` 调整唤醒阈值；提高阈值会更严格。输入 `/quit` 或按 Ctrl+C 退出。对话模式中仍可键入文字作为调试备用输入。

The default model downloads from its public repository into `models/` on first launch and is checked against a SHA-256 checksum. If the robot cannot reach GitHub, place `reechy-spk150-steps100k-acc98.15-rec97.50.onnx` in `models/` or set `WAKEWORD_MODEL_PATH`. Adjust `WAKEWORD_THRESHOLD` to tune wake sensitivity; higher values are stricter. Enter `/quit` or press Ctrl+C to exit. Typed text remains available as a fallback while a conversation is active.

默认唤醒模型由社区维护，模型标签拼作 `reechy`，读音对应 Reachy。该模型采用 CC BY-NC-SA 4.0 许可，仅供非商业用途；如分发模型或其衍生版本，须保留署名并遵守相同方式共享条款。模型来源：[reachy-wake-word](https://github.com/andyjmorgan/reachy-wake-word)。Reachy 的媒体 API 参考[官方 Python SDK 文档](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md)。

The default community model is labeled `reechy` and is intended to recognize the spoken name Reachy. It is licensed under CC BY-NC-SA 4.0 for non-commercial use; redistribution or derivatives must retain attribution and comply with ShareAlike terms. Model source: [reachy-wake-word](https://github.com/andyjmorgan/reachy-wake-word). Reachy's media APIs follow the [official Python SDK guide](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md).

客户端不使用 QT 的 ROS 服务。QT 原有的自定义桌面界面、语音预览、录音偏好设置及 QT 专用表情和手势服务尚未移植。

The client does not use QT ROS services. The QT desktop UI, voice preview, recording preferences, and QT-specific emotion and gesture services have not been ported.
