# Reachy Mini 对话客户端 / Reachy Mini Conversation Client

这个初版把 QT Robot V3 客户端的手动轮次对话流程接到 Reachy Mini：机器人持续把麦克风 PCM 音频流式发送到后端，用户说完后按回车，后端完成转写和回复，再由 Reachy Mini 播放返回的语音。终端会显示用户转写和助手文字。也可以输入文字后按回车，用于安静环境或快速验证对话链路。

This first port brings the QT Robot V3 client's manual turn-taking flow to Reachy Mini. The robot streams microphone PCM to the backend; press Enter when the user finishes, and Reachy Mini plays the backend's spoken reply. The terminal shows the user transcript and assistant text. You can also type a message and press Enter for quiet environments or a quick conversation-path check.

它使用 `reachyrobot` 作为 WebSocket source，将初始的 automatic response mode 切换到 manual，保留“用户决定何时发送”的方式。机器人播放回复期间会暂停后端听写，播放完成后恢复。客户端使用 Reachy SDK 的 `get_audio_sample()` 和 `push_audio_sample()`，不依赖 QT 的 ROS 服务。

The client connects with WebSocket source `reachyrobot` and switches the initial automatic response mode to manual, so the user controls when a turn is sent. Backend listening pauses while Reachy speaks and resumes when playback finishes. Audio uses the Reachy SDK's `get_audio_sample()` and `push_audio_sample()` APIs; no QT ROS services are required.

## 配置与启动 / Configure and run

在项目根目录创建 `.env`，从本目录的 `.env.example` 复制模板，然后填写后端账号。依赖安装到 Reachy 的官方应用虚拟环境 `/venvs/apps_venv` 中。

Create `.env` in the project root by copying this directory's `.env.example`, then enter the backend credentials. Install the dependencies into Reachy's official apps virtual environment at `/venvs/apps_venv`.

```sh
cp src/chat/.env.example .env
/venvs/apps_venv/bin/pip install -r src/chat/requirements.txt
/venvs/apps_venv/bin/python src/chat/main.py
```

按回车发送当前麦克风轮次；输入文字后按回车会发送文本轮次；输入 `/q` 结束对话。不要把含真实账号密码的 `.env` 提交到 Git。

Press Enter to send the current microphone turn; type text and press Enter to send a text turn; enter `/q` to end the chat. Do not commit `.env` if it contains real credentials.

这一版聚焦对话、麦克风采集、后端语音播放和终端转写。QT 原有的自定义桌面界面、语音预览、录音偏好设置，以及 QT 专用表情和手势服务尚未移植。

This version focuses on conversation, microphone capture, backend speech playback, and a terminal transcript. The QT desktop UI, voice preview, recording preferences, and QT-specific emotion and gesture services have not been ported yet.
