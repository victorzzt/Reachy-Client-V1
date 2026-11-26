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

## Linux: Configure GStreamer and WebRTC / Linux：配置 GStreamer 和 WebRTC

This section is required when you want the Linux simulator to provide camera/audio streaming. Without the WebRTC plugin, the daemon and simulator window can still start, but the media server reports `Failed to create webrtcsink element`. You can skip these steps when running with `--no-media`.

如果希望 Linux 模拟器提供相机和音频流，需要完成本节配置。缺少 WebRTC 插件时，daemon 和模拟器窗口仍可能启动，但媒体服务器会报错 `Failed to create webrtcsink element`。使用 `--no-media` 时可以跳过本节。

### 1. Install system packages / 安装系统依赖

For Ubuntu/Debian, install the GStreamer development libraries and plugins:

Ubuntu/Debian 系统请安装 GStreamer 开发库和插件：

```bash
sudo apt-get update
sudo apt-get install \
    libgstreamer-plugins-bad1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer1.0-dev \
    libglib2.0-dev \
    libssl-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    libportaudio2 \
    libnice10 \
    gstreamer1.0-plugins-good \
    gstreamer1.0-alsa \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-nice \
    python3-gi \
    python3-gi-cairo
```

Ubuntu 22.04's default GStreamer is too old for this setup. The official guide requires GStreamer 1.22 or later and provides this PPA route to install 1.24.x:

Ubuntu 22.04 自带的 GStreamer 版本过旧。官方指南要求 1.22 或更高版本，并提供以下 PPA 方式安装 1.24.x：

```bash
sudo add-apt-repository ppa:savoury1/multimedia
sudo apt update
sudo apt install \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev \
    libgstreamer-plugins-good1.0-dev \
    libgstreamer-plugins-bad1.0-dev
pkg-config --modversion gstreamer-1.0
```

Use the Ubuntu 22.04-specific commands only on Ubuntu 22.04. The version command should report `1.22` or newer.

仅在 Ubuntu 22.04 上使用上面的专用命令。版本检查结果应为 `1.22` 或更高。

### 2. Install Rust / 安装 Rust

The Linux WebRTC plugin is built from Rust sources. Install Rust with `rustup`, then load Cargo into the current shell:

Linux WebRTC 插件需要从 Rust 源码编译。使用 `rustup` 安装 Rust，并将 Cargo 环境载入当前终端：

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"
```

### 3. Build and install the WebRTC plugin / 编译并安装 WebRTC 插件

Build the pinned GStreamer Rust plugin release `0.14.5`, which includes the WebRTC sink fixes required by the Reachy Mini daemon:

编译固定版本的 GStreamer Rust 插件 `0.14.5`；该版本包含 Reachy Mini daemon 所需的 WebRTC sink 修复：

```bash
git clone https://gitlab.freedesktop.org/gstreamer/gst-plugins-rs.git
cd gst-plugins-rs
git checkout 0.14.5
cargo install cargo-c
sudo mkdir -p /opt/gst-plugins-rs
sudo chown "$USER" /opt/gst-plugins-rs
cargo cinstall -p gst-plugin-webrtc --prefix=/opt/gst-plugins-rs --release
```

Check the machine architecture:

查看本机架构：

```bash
uname -m
```

If it reports `x86_64`, add this path:

如果显示 `x86_64`，添加此路径：

```bash
echo 'export GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/x86_64-linux-gnu:$GST_PLUGIN_PATH' >> ~/.bashrc
```

If it reports `aarch64`, use this command instead:

如果显示 `aarch64`，则改用此命令：

```bash
echo 'export GST_PLUGIN_PATH=/opt/gst-plugins-rs/lib/aarch64-linux-gnu:$GST_PLUGIN_PATH' >> ~/.bashrc
```

Then load the environment and start the simulator from this shell:

然后载入环境变量，并在此终端启动模拟器：

```bash
source ~/.bashrc
```

### 4. Verify and start / 验证并启动

Install the optional command-line tools, confirm that GStreamer can find `webrtcsink`, then start the simulator without `--no-media`:

安装可选命令行工具，确认 GStreamer 能找到 `webrtcsink`，然后不带 `--no-media` 启动模拟器：

```bash
sudo apt install gstreamer1.0-tools
gst-inspect-1.0 webrtcsink
gst-inspect-1.0 webrtcsrc
reachy-mini-daemon --sim
```

If either `gst-inspect-1.0` command reports that the element is unavailable, check the GStreamer version and `GST_PLUGIN_PATH`. With the plugin loaded, the daemon should initialize its media server instead of logging `Failed to create webrtcsink element`.

如果任一 `gst-inspect-1.0` 命令提示找不到插件，请检查 GStreamer 版本和 `GST_PLUGIN_PATH`。插件载入后，daemon 应能初始化媒体服务器，不再报告 `Failed to create webrtcsink element`。

The official [GStreamer installation guide](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation) covers the complete Linux media setup and troubleshooting.

完整 Linux 媒体配置和故障排查请参阅官方 [GStreamer 安装指南](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation)。
