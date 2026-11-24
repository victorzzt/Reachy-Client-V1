# Reachy Mini 对话客户端 / Reachy Mini Conversation Client

客户端启动后只在 Reachy 本机监听唤醒词 “Reachy”。待机音频只送入本地 openWakeWord 模型，不上传到后端；检测到唤醒词后会启用电机、展开头部，再建立聊天 WebSocket。唤醒后无需每轮重复唤醒，直接连续说话即可。

At startup, the client listens for “Reachy” locally on the robot. Standby audio is processed only by the local openWakeWord model and is not uploaded. After detecting the wake word, it enables the motors and extends the head before opening the chat WebSocket. Once awake, speak naturally across turns without repeating the wake word.

对话使用 WebSocket 的 `source=reachyrobot`、`chat_type=activity` 和 automatic response mode：麦克风音频以 16 kHz、单声道、16-bit PCM 的 `audio_data` 持续发送；后端返回的 `audio_chunk` 在同一连接上接收并由 Reachy 扬声器播放。用户转写和助手回复文字也会显示在终端，不需要按回车请求回复。

Conversation uses the WebSocket with `source=reachyrobot`, `chat_type=activity`, and automatic response mode. Microphone audio is continuously sent as 16 kHz mono 16-bit PCM `audio_data`; returned `audio_chunk` messages arrive on the same connection and play through Reachy's speaker. User transcripts and assistant text are also shown in the terminal, with no Enter needed to request a reply.

检测到 Reachy 麦克风阵列的语音活动或收到后端 `user_utt` 转写时，5 分钟静默计时会重置。5 分钟没有语音后，客户端发送 `end_chat` 并回到本地唤醒待机。Reachy SDK 的 `get_DoA()` 提供语音活动状态；不可用时客户端回退到可配置的音量阈值。

The five-minute silence timer resets when the Reachy microphone array detects speech or the backend sends a `user_utt` transcript. After five minutes without speech, the client sends `end_chat` and returns to local wake-word standby. The Reachy SDK's `get_DoA()` supplies speech activity; if unavailable, the client falls back to a configurable audio-level threshold.

对话期间也可以说“Reachy，休息一下”“Reachy，暂停一会儿”或 “Reachy, take a break / go to sleep”。同一条指令需要包含 “Reachy” 称呼；语音转写偶尔会把它写成同音的 “Richie” 或 “Ritchie”，客户端也会识别。单独提到休息不会触发。客户端在本地对收到的用户转写运行轻量的同义词与近似拼写匹配；识别到休息意图后立即停止处理后端回复、结束会话、收起 Reachy 并回到本地唤醒待机。该判断不依赖后端语义分析，也不需要额外安装模型。

During a conversation, say “Reachy, take a break / go to sleep” or “Reachy，休息一下 / 暂停一会儿”. Include “Reachy” in the same command; speech recognition may transcribe it as the homophone “Richie” or “Ritchie”, which the client also accepts. Rest-related words alone do not trigger it. The client locally checks the received user transcript using lightweight synonym and fuzzy-spelling rules; when it detects a rest intent, it stops handling backend replies, ends the session, tucks Reachy, and returns to local wake-word standby. This decision does not rely on backend semantic analysis or require an additional model.

每次收到助手回复，客户端都会随机播放 `cheerful1`、`loving1` 或 `laughing1` 中的一个动作，并在动作后恢复到展开的头部姿势。静默超时退出时会播放收起流程、调用 Reachy 的睡眠姿态，并禁用电机，之后继续本地监听唤醒词。

For each assistant reply, the client randomly plays one of `cheerful1`, `loving1`, or `laughing1`, then restores the extended head pose. On inactivity timeout, it returns Reachy to the SDK sleep pose, disables the motors, and resumes local wake-word listening.

## 配置与启动 / Configure and run

聊天客户端按职责拆分为多个模块：`main.py` 负责初始化和启动，`config.py` 读取设置，`audio.py` 转换输入和输出音频，`wakeword.py` 在本机检测唤醒词，`intent.py` 在本机识别休息指令，`backend.py` 处理 JWT、WebSocket 协议和语音播放队列，`interaction.py` 管理待机与对话状态，`motion.py` 管理唤醒、回复动作和休眠姿态。

The chat client is split by responsibility: `main.py` initializes and starts the app; `config.py` loads settings; `audio.py` converts input and output audio; `wakeword.py` detects the wake word locally; `intent.py` detects rest commands locally; `backend.py` handles JWT, the WebSocket protocol, and speech playback queue; `interaction.py` manages standby and conversation state; and `motion.py` controls wake, reply actions, and the sleep pose.

将目录放在 Reachy 的 `~/apps/chat/` 后，在该目录从 `.env.example` 创建 `.env` 并填写后端账号。测试后端地址应为 `https://sandbox2.cognibot.org`；如果现有 `.env` 仍填写 `https://cognibot.org`，需将 `BASE_HTTP_URL` 改为 sandbox2。不要关闭 TLS 证书校验。

Place this directory at `~/apps/chat/`, create `.env` from `.env.example`, and enter the backend credentials. The test backend URL is `https://sandbox2.cognibot.org`; change `BASE_HTTP_URL` to sandbox2 if an existing `.env` still says `https://cognibot.org`. Keep TLS certificate verification enabled.

```sh
cd ~/apps/chat
cp .env.example .env
nano .env
/venvs/apps_venv/bin/pip install -r requirements.txt
/venvs/apps_venv/bin/pip install --no-deps openwakeword==0.6.0
/venvs/apps_venv/bin/python main.py
```

openWakeWord 0.6.0 的 PyPI 安装元数据会在 Linux 上要求 `tflite-runtime`，但 Reachy 当前使用的 Python 3.12 ARM64 没有对应 wheel。客户端选用 ONNX 推理，因此 `requirements.txt` 已列出 ONNX 和其余运行依赖；第二条命令用 `--no-deps` 安装 openWakeWord，跳过不需要的 TFLite 依赖。

The PyPI metadata for openWakeWord 0.6.0 requests `tflite-runtime` on Linux, but no matching wheel is available for Reachy's Python 3.12 ARM64 environment. This client uses ONNX inference, so `requirements.txt` lists ONNX and the other runtime dependencies; the second command installs openWakeWord with `--no-deps` to skip the unused TFLite dependency.

唤醒词模型会下载到 `models/`，openWakeWord 的 ONNX 前处理模型会下载到 `models/openwakeword/`；每个文件下载后都会校验 SHA-256。若机器人无法访问 GitHub，请将这些模型文件放入对应目录。也可通过 `WAKEWORD_MODEL_PATH` 指定已有唤醒词模型。可用 `WAKEWORD_THRESHOLD` 调整唤醒阈值；提高阈值会更严格。输入 `/quit` 或按 Ctrl+C 退出。对话模式中仍可键入文字作为调试备用输入。

The wake-word model downloads into `models/`, and openWakeWord's ONNX feature models download into `models/openwakeword/`; each file is checked against its SHA-256 checksum. If the robot cannot reach GitHub, place the model files in those directories. Set `WAKEWORD_MODEL_PATH` to use another wake-word model. Adjust `WAKEWORD_THRESHOLD` to tune wake sensitivity; higher values are stricter. Enter `/quit` or press Ctrl+C to exit. Typed text remains available as a fallback while a conversation is active.

默认唤醒模型由社区维护，模型标签拼作 `reechy`，读音对应 Reachy。该模型采用 CC BY-NC-SA 4.0 许可，仅供非商业用途；如分发模型或其衍生版本，须保留署名并遵守相同方式共享条款。模型来源：[reachy-wake-word](https://github.com/andyjmorgan/reachy-wake-word)。Reachy 的媒体 API 参考[官方 Python SDK 文档](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md)。

The default community model is labeled `reechy` and is intended to recognize the spoken name Reachy. It is licensed under CC BY-NC-SA 4.0 for non-commercial use; redistribution or derivatives must retain attribution and comply with ShareAlike terms. Model source: [reachy-wake-word](https://github.com/andyjmorgan/reachy-wake-word). Reachy's media APIs follow the [official Python SDK guide](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md).

客户端不使用 QT 的 ROS 服务。QT 原有的自定义桌面界面、语音预览、录音偏好设置及 QT 专用表情和手势服务尚未移植。

The client does not use QT ROS services. The QT desktop UI, voice preview, recording preferences, and QT-specific emotion and gesture services have not been ported.
