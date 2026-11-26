# Reachy Mini Simulator on Linux / Reachy Mini Linux 模拟器

This guide covers setup and startup on an Ubuntu/Debian desktop with a graphical session. A physical robot is not required. The commands follow the official documentation and have not been run on this machine.

本指南介绍如何在带图形桌面的 Ubuntu/Debian 系统中配置并启动模拟器，无需实体机器人。命令依据官方文档整理，尚未在本机实测。

## Dependencies / 系统依赖

The Linux package build may need `pkg-config`, Cairo headers, and GObject Introspection headers. If these packages are already installed, skip this step; otherwise install them before the Conda and pip steps.

Linux 下编译程序包时可能需要 `pkg-config`、Cairo 头文件和 GObject Introspection 头文件。如果这些依赖已经安装，可跳过此步骤；缺少时请先安装，再创建 Conda 环境并运行 pip。

```bash
sudo apt update
sudo apt install pkg-config libcairo2-dev libgirepository1.0-dev
```

## Create the Conda environment / 创建 Conda 环境

This assumes Conda is already installed. Reachy Mini supports Python 3.10–3.12; the official guide recommends Python 3.12.

以下命令假设本机已安装 Conda。Reachy Mini 支持 Python 3.10–3.12；官方指南推荐 Python 3.12。

```bash
conda create -n reachy_mini_env python=3.12 pip -y
conda activate reachy_mini_env
```

Whenever you open a new terminal, activate the environment again before running Reachy Mini.

每次新开终端运行 Reachy Mini 前，都需要重新启用该环境。

## Install and start / 安装并启动

Install the simulator extra, then start the daemon in simulation mode from the same activated terminal.

安装模拟器扩展，然后在同一个已启用环境的终端中启动模拟模式。

```bash
python -m pip install "reachy-mini[mujoco]"
reachy-mini-daemon --sim
```

A MuJoCo window should open with the simulated robot. Keep the terminal open while using it; press `Ctrl+C` there to stop the daemon.

正常情况下会打开 MuJoCo 窗口并显示模拟机器人。使用期间请保持终端运行；要停止 daemon，请在该终端按 `Ctrl+C`。

The default scene is `empty`. To use the scene with a table and sample objects, run `reachy-mini-daemon --sim --scene minimal` instead.

默认场景为 `empty`。如需加载带桌子和示例物品的场景，请改用 `reachy-mini-daemon --sim --scene minimal`。

## SSH access / SSH 远程访问

The simulator is a process on the Linux host, not a separate computer with its own SSH login. On the host, install and start the SSH server once, then note its IP address.

模拟器是 Linux 主机上的一个进程，并不是一台可单独 SSH 登录的计算机。在主机上安装并启动 SSH 服务后，记下主机 IP 地址。

```bash
sudo apt install openssh-server
sudo systemctl enable --now ssh
hostname -I
```

From another computer on the network, open a shell on the host with `ssh <linux_user>@<simulator_ip>`. Start the MuJoCo viewer from the host's logged-in graphical desktop; a regular SSH shell does not provide that desktop window.

在同一网络的另一台电脑上，运行 `ssh <linux_user>@<simulator_ip>` 登录主机终端。MuJoCo 图形窗口请从主机已登录的桌面会话启动；普通 SSH 终端不会显示该桌面窗口。

To connect a remote client to the simulator API, keep the simulator running on the host, then open an SSH tunnel from the client computer and leave it open:

如需从远程电脑连接模拟器 API，请先让主机上的模拟器保持运行，再从客户端电脑建立 SSH 隧道，并保持隧道终端打开：

```bash
ssh -N -L 8000:127.0.0.1:8000 <linux_user>@<simulator_ip>
```

The API docs are then available on the client at `http://127.0.0.1:8000/docs`. A Python client with the Reachy Mini SDK installed can connect through the tunnel like this:

随后可在客户端浏览器打开 `http://127.0.0.1:8000/docs` 查看 API。客户端安装 Reachy Mini SDK 后，可用以下代码通过隧道连接：

```python
from reachy_mini import ReachyMini

with ReachyMini(host="127.0.0.1", port=8000, connection_mode="network") as mini:
    print("Connected to simulator over SSH tunnel")
```

## Troubleshooting / 排查

For `Dependency "cairo" not found (tried pkg-config)`, install the missing system dependencies from the first section, then retry `python -m pip install "reachy-mini[mujoco]"` with the Conda environment active.

如果出现 `Dependency "cairo" not found (tried pkg-config)`，请安装开头列出的缺失系统依赖，再在已启用 Conda 环境中重试 `python -m pip install "reachy-mini[mujoco]"`。

If `reachy-mini-daemon` is not found, activate `reachy_mini_env` in the current terminal and rerun the pip install command. If the 3D window does not appear, use a terminal opened from a logged-in graphical desktop session.

如果系统找不到 `reachy-mini-daemon`，请在当前终端启用 `reachy_mini_env` 并重新运行 pip 安装命令。如果没有出现 3D 窗口，请在已登录图形桌面中打开终端运行。

Linux audio/video streaming may require the additional packages and WebRTC setup in the [GStreamer installation guide](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation). USB permission rules are only for a physical robot.

Linux 音视频流可能还需要按照 [GStreamer 安装指南](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation)安装额外依赖并配置 WebRTC。USB 权限规则仅适用于实体机器人。

## Official references / 官方参考

- [Reachy Mini Simulation — Setup Guide](https://huggingface.co/docs/reachy_mini/platforms/simulation/get_started)
- [Reachy Mini Installation Guide](https://huggingface.co/docs/reachy_mini/SDK/installation)
- [Reachy Mini REST API](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/API/rest-api.mdx)
- [GStreamer Installation Guide](https://huggingface.co/docs/reachy_mini/SDK/gstreamer-installation)

---

Guide updated: 2026-11-26 / 更新日期：2026-11-26
