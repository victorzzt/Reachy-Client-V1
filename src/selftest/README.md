# Reachy Mini Self-Test

This self-test checks the Reachy daemon's live OpenAPI inventory, core robot status endpoints, and one camera frame, then runs a short hardware demonstration. It wakes the robot, enables the motors, gently moves head yaw, pitch, and roll, body yaw, and both antennas, and plays the `cheerful1`, `loving1`, and `laughing1` recorded expressions with their bundled sound effects. It then returns Reachy to its sleep pose and verifies that motor mode is disabled.

The current robot at `192.168.111.101` runs daemon `1.15.0`. Its OpenAPI document lists endpoints for apps, daemon status and control, camera and media, motors, movement, robot state and IMU, kinematics, audio and volume, Wi-Fi, NFC, Hugging Face authentication, and telemetry. The self-test reports the current GET route inventory from `/openapi.json` so it follows the daemon version installed on the robot.

Before moving, the self-test loads all three emotion clips and verifies their bundled sound files are present. The motion angles are intentionally small. Progress is printed as each movement and expression plays. These actions run on every boot because the systemd unit is enabled, so make sure the robot has clear space around its head and antennas.

The API checks use `GET /api/daemon/status`, `GET /api/motors/status`, `GET /api/camera/specs`, `GET /api/media/status`, `GET /api/state/full`, `GET /api/state/imu`, `GET /api/state/present_head_pose`, `GET /api/state/present_body_yaw`, `GET /api/state/present_antenna_joint_positions`, and `GET /api/kinematics/info`. App, app-lock, direction-of-arrival, volume, Wi-Fi, and NFC status routes are optional checks. The camera is checked with `ReachyMini(media_backend="default").media.get_frame()` in the robot's `/venvs/apps_venv` environment.

本自检会查询 Reachy daemon 的 OpenAPI、核心状态接口和一帧相机画面，随后执行一段简短的硬件演示：唤醒机器人并启用电机，小幅转动头部偏航、俯仰和滚转轴、身体偏航及两根天线，再播放 `cheerful1`、`loving1`、`laughing1` 三个预录表情及其配套音效。结束时机器人回到休眠姿态，并确认电机模式已禁用。

动作开始前会先加载这三个表情，并确认对应音效文件已缓存；动作角度较小，执行过程中会逐步输出进度。systemd 单元已设为开机运行，因此每次重启都会执行这些动作，请确保机器人头部和天线周围有活动空间。

The systemd unit `reachy-mini-selftest.service` starts after `reachy-mini-daemon.service` and retries while the daemon API is starting. It is enabled at boot on the robot. Each run writes the latest JSON report to `~/apps/logs/selftest-last.json`; progress and full console output are available with `journalctl -u reachy-mini-selftest.service`.

systemd 单元 `reachy-mini-selftest.service` 会在 `reachy-mini-daemon.service` 启动后运行，并在等待 daemon API 就绪时重试。该单元已设为开机自启。每次运行都会把最新 JSON 报告写入 `~/apps/logs/selftest-last.json`；动作进度和完整输出可通过 `journalctl -u reachy-mini-selftest.service` 查看。

Install or update the unit after copying this directory to `~/apps/selftest/`:

```sh
sudo install -m 644 ~/apps/selftest/reachy-mini-selftest.service /etc/systemd/system/reachy-mini-selftest.service
sudo systemctl daemon-reload
sudo systemctl enable --now reachy-mini-selftest.service
```

The Reachy Mini daemon documents its REST/OpenAPI routes at `http://<robot-ip>:8000/docs` and camera-frame access in the Python SDK guide.

- [Reachy Mini REST API](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/API/rest-api.mdx)
- [Reachy Mini Python SDK](https://github.com/pollen-robotics/reachy_mini/blob/main/docs/source/SDK/python-sdk.md)
