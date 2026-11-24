# Reachy Client V1

本项目旨在为 Reachy 机器人构建客户端。计划对接 `v2_benchmarking` 的 `adnan_activity_refactor` 分支，并移植 QT Robot 客户端 `new_ws_connection` 分支中的交互流程。

This project aims to build a client for the Reachy robot. The client will connect to the `adnan_activity_refactor` branch of `v2_benchmarking` and port the interaction flow from the QT Robot client's `new_ws_connection` branch.

参考仓库链接见 [Reference.md](Reference.md)。本地参考副本放在 `Reference/` 下。

See [Reference.md](Reference.md) for repository links. Local reference copies are kept in `Reference/`.

WebSocket 协议有变更时，需从 `v2_benchmarking` 的 `adnan_activity_refactor` 分支同步更新本仓库的 `docs/CLIENT_PROTOCOL.md`。 [上游协议文档](https://github.com/amurphy99/v2_benchmarking/blob/adnan_activity_refactor/backend/chat_app/websocket/consumers/CLIENT_PROTOCOL.md)

When the WebSocket protocol changes upstream, sync this repository's `docs/CLIENT_PROTOCOL.md` from the `adnan_activity_refactor` branch of `v2_benchmarking`. [Upstream protocol document](https://github.com/amurphy99/v2_benchmarking/blob/adnan_activity_refactor/backend/chat_app/websocket/consumers/CLIENT_PROTOCOL.md)

## Reachy Mini 目录安排 / Reachy Mini Directory Layout

Reachy Mini 上的代码、演示程序和测试统一放在 `~/apps/`。本项目副本位于 `~/apps/Reachy-Client-V1/`，上游 `reachy-mini-demo` 工作副本位于 `~/apps/reachy-mini-demo/`，测试脚本位于 `~/apps/Reachy-Client-V1/tests/`，运行日志和测试结果位于 `~/apps/logs/`。机器人 SDK 脚本须通过 `/venvs/apps_venv/bin/python` 运行。

Keep the code, demo and tests on Reachy Mini under `~/apps/`. The project copy lives in `~/apps/Reachy-Client-V1/`, the working copy of the upstream `reachy-mini-demo` lives in `~/apps/reachy-mini-demo/`, test scripts live in `~/apps/Reachy-Client-V1/tests/`, and runtime logs and test results live in `~/apps/logs/`. Run robot SDK scripts with `/venvs/apps_venv/bin/python`.

```text
~/apps/
├── Reachy-Client-V1/
│   ├── docs/
│   ├── src/
│   └── tests/
├── reachy-mini-demo/
├── selftest/
└── logs/
```

每次更新代码、文档或测试后，都将更新的文件复制到机器人上 `~/apps/` 中对应的位置，再使用 Reachy SDK 虚拟环境运行或测试。使用 `~/apps/Reachy-Client-V1/tests/robot_smoke_test.sh` 运行硬件冒烟测试。

After each code, documentation or test update, copy the updated files to their matching locations under `~/apps/` on the robot, then run or test them in the Reachy SDK virtual environment. Run the hardware smoke test with `~/apps/Reachy-Client-V1/tests/robot_smoke_test.sh`.

## Reachy Mini 自检 / Reachy Mini Self-Test

本仓库的自检代码和 systemd 单元位于 `src/selftest/`，设备副本位于 `~/apps/selftest/`。自检会查询当前 daemon 的 OpenAPI 和机器人状态、读取一帧相机画面，然后启用电机并小幅活动头部偏航/俯仰/滚转、身体偏航和两根天线，依次显示 `cheerful1`、`loving1`、`laughing1` 三个表情并播放各自配套的音效。结束时机器人回到休眠姿态，并确认电机已禁用。systemd 单元每次开机后都会在 daemon API 就绪时运行，报告写入 `~/apps/logs/selftest-last.json`。

The self-test code and systemd unit live in `src/selftest/`, with the device copy under `~/apps/selftest/`. It inventories the current daemon OpenAPI, checks robot status, and reads one camera frame, then enables the motors and gently moves head yaw, pitch, and roll, body yaw, and both antennas. It plays the `cheerful1`, `loving1`, and `laughing1` expressions with their bundled sounds, returns the robot to its sleep pose, and verifies that the motors are disabled. The systemd unit runs at each boot after the daemon API is ready. The report is written to `~/apps/logs/selftest-last.json`.

## 记录 / Records

20261117 - 仓库提交测试

20261117 - repository commit test
