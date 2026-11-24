# Reachy Mini 模拟器 / Reachy Mini Simulator

Reachy Mini 模拟器使用 MuJoCo 显示虚拟机器人，无需连接实体 Reachy Mini。以下步骤适用于 Windows 和 Linux；需要 Python 3.12 和 `uv`。

The Reachy Mini simulator uses MuJoCo to display a virtual robot; no physical Reachy Mini is needed. The steps below cover Windows and Linux and require Python 3.12 and `uv`.

## Windows

在 PowerShell 中进入要存放项目的目录，依次运行以下命令。若已安装 `uv`，可跳过第一行。

Open PowerShell in the directory where you want the environment, then run these commands in order. If `uv` is already installed, skip the first command.

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv python install 3.12
uv venv .venv --python 3.12
.\.venv\Scripts\Activate.ps1
uv pip install "reachy-mini[mujoco]"
reachy-mini-daemon --sim --no-media
```

若 PowerShell 阻止激活虚拟环境，可在当前用户范围设置一次执行策略，然后重新运行激活命令：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

If PowerShell blocks virtual-environment activation, set the execution policy once for the current user, then run the activation command again: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Linux

在终端中进入要存放项目的目录，依次运行以下命令。若已安装 `uv`，可跳过第一行。

Open a terminal in the directory where you want the environment, then run these commands in order. If `uv` is already installed, skip the first command.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.12
uv venv .venv --python 3.12
source .venv/bin/activate
uv pip install "reachy-mini[mujoco]"
reachy-mini-daemon --sim --no-media
```

## 运行与停止 / Run and stop

启动后会打开 MuJoCo 机器人视窗。保持运行 daemon 的终端打开；在终端按 `Ctrl+C` 可停止模拟器。可在浏览器打开 `http://localhost:8000/docs` 检查本机模拟器 API。

The MuJoCo robot viewer opens after startup. Keep the daemon terminal open; press `Ctrl+C` there to stop the simulator. Open `http://localhost:8000/docs` in a browser to check the local simulator API.

命令中的 [`--no-media`](https://github.com/pollen-robotics/reachy_mini/blob/main/src/reachy_mini/daemon/app/main.py#L779-L783) 会关闭相机、音频和 WebRTC，只保留虚拟机器人和控制 API。若需要媒体功能，请移除该参数；Linux 还需按官方 [GStreamer 安装说明](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/gstreamer-installation.md)安装 GStreamer。安装选项和模拟器说明见官方 [SDK 安装指南](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/installation.md)及[模拟器指南](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/platforms/simulation/get_started.md)。

The [`--no-media`](https://github.com/pollen-robotics/reachy_mini/blob/main/src/reachy_mini/daemon/app/main.py#L779-L783) option disables the camera, audio, and WebRTC while keeping the virtual robot and control API. Remove it to enable media; on Linux, install GStreamer using the official [GStreamer instructions](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/gstreamer-installation.md). For installation options and simulator details, see the official [SDK installation guide](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/installation.md) and [simulator guide](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/platforms/simulation/get_started.md).
