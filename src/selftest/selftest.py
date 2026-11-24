#!/usr/bin/env python3
"""API, camera, gentle motion, and emotion/audio checks for Reachy Mini."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DAEMON_URL = os.environ.get("REACHY_DAEMON_URL", "http://127.0.0.1:8000").rstrip("/")
REPORT_PATH = Path(
    os.environ.get(
        "REACHY_SELFTEST_REPORT",
        "/home/pollen/apps/logs/selftest-last.json",
    )
).expanduser()
REQUEST_TIMEOUT_SECONDS = 5
CAMERA_TIMEOUT_SECONDS = 10
EMOTIONS_DATASET = "pollen-robotics/reachy-mini-emotions-library"
EMOTION_NAMES = ("cheerful1", "loving1", "laughing1")

READ_ONLY_ENDPOINTS = (
    ("daemon_status", "/api/daemon/status", True),
    ("motor_status", "/api/motors/status", True),
    ("camera_specs", "/api/camera/specs", True),
    ("media_status", "/api/media/status", True),
    ("full_state", "/api/state/full", True),
    ("imu", "/api/state/imu", True),
    ("head_pose", "/api/state/present_head_pose", True),
    ("body_yaw", "/api/state/present_body_yaw", True),
    ("antenna_positions", "/api/state/present_antenna_joint_positions", True),
    ("kinematics_info", "/api/kinematics/info", True),
    ("app_status", "/api/apps/current-app-status", False),
    ("app_lock_status", "/api/daemon/robot-app-lock-status", False),
    ("doa", "/api/state/doa", False),
    ("speaker_volume", "/api/volume/current", False),
    ("microphone_volume", "/api/volume/microphone/current", False),
    ("wifi_status", "/wifi/status", False),
    ("nfc_status", "/api/nfc/status", False),
)


def get_json(path: str) -> tuple[int, object]:
    request = Request(
        f"{DAEMON_URL}{path}",
        headers={"Accept": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        body = response.read()
        if not body:
            return response.status, None
        return response.status, json.loads(body)


def announce(message: str) -> None:
    print(f"[selftest] {message}", flush=True)


def check_endpoint(name: str, path: str, required: bool) -> tuple[dict, object | None]:
    result = {
        "name": name,
        "path": path,
        "required": required,
        "status": "passed",
    }
    try:
        http_status, body = get_json(path)
        result["http_status"] = http_status
        if not 200 <= http_status < 300:
            result["status"] = "failed" if required else "warning"
            result["detail"] = f"Unexpected HTTP status {http_status}"
            return result, body
        return result, body
    except HTTPError as exc:
        result["http_status"] = exc.code
        result["status"] = "failed" if required else "warning"
        result["detail"] = f"HTTP error {exc.code}"
    except (URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        result["status"] = "failed" if required else "warning"
        result["detail"] = f"{type(exc).__name__}: {exc}"
    return result, None


def inventory_api(specification: object) -> dict:
    if not isinstance(specification, dict):
        raise ValueError("OpenAPI document is not a JSON object")

    paths = specification.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI document has no paths object")

    get_endpoints = []
    for path, operations in paths.items():
        if not isinstance(operations, dict) or "get" not in operations:
            continue
        operation = operations["get"]
        if not isinstance(operation, dict):
            continue
        get_endpoints.append(
            {
                "path": path,
                "summary": operation.get("summary", ""),
                "tags": operation.get("tags", []),
            }
        )

    if not get_endpoints:
        raise ValueError("OpenAPI document has no GET endpoints")

    tag_counts: dict[str, int] = {}
    for endpoint in get_endpoints:
        tags = endpoint["tags"] or ["Untagged"]
        for tag in tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return {
        "version": specification.get("info", {}).get("version"),
        "get_endpoint_count": len(get_endpoints),
        "get_endpoints": get_endpoints,
        "get_endpoints_by_tag": dict(sorted(tag_counts.items())),
    }


def check_camera_frame() -> dict:
    from reachy_mini import ReachyMini

    deadline = time.monotonic() + CAMERA_TIMEOUT_SECONDS
    with ReachyMini(media_backend="default") as mini:
        frame = mini.media.get_frame()
        while frame is None and time.monotonic() < deadline:
            time.sleep(0.25)
            frame = mini.media.get_frame()

    if frame is None:
        raise RuntimeError("Camera did not return a frame within the timeout")
    if not hasattr(frame, "shape") or len(frame.shape) < 2:
        raise RuntimeError("Camera returned a frame with an unexpected format")

    return {
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "shape": [int(dimension) for dimension in frame.shape],
    }


def set_global_motor_mode_disabled() -> str:
    request = Request(
        f"{DAEMON_URL}/api/motors/set_mode/disabled",
        data=b"",
        method="POST",
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"Could not disable motors, HTTP {response.status}")

    _, motor_status = get_json("/api/motors/status")
    if not isinstance(motor_status, dict) or motor_status.get("mode") != "disabled":
        raise RuntimeError("Reachy did not report motor mode disabled after cleanup")
    return "disabled"


def run_motion_and_emotion_demo() -> dict:
    from reachy_mini import ReachyMini
    from reachy_mini.motion.recorded_move import RecordedMoves
    from reachy_mini.utils import create_head_pose

    result = {
        "status": "failed",
        "warmup_moves": [],
        "expressions": [],
        "sound_effects": [],
        "parked_in_sleep_pose": False,
        "motor_mode_after": None,
        "errors": [],
    }

    try:
        emotion_library = RecordedMoves(EMOTIONS_DATASET)
        emotion_moves = []
        for emotion_name in EMOTION_NAMES:
            emotion = emotion_library.get(emotion_name)
            if emotion.sound_path is None or not emotion.sound_path.is_file():
                raise RuntimeError(f"Emotion {emotion_name} has no cached sound effect")
            emotion_moves.append(emotion)
    except Exception as exc:
        result["errors"].append(f"Could not load emotion clips: {type(exc).__name__}: {exc}")
        return result

    motors_may_have_changed = False
    try:
        with ReachyMini() as mini:
            motors_may_have_changed = True
            motors_enabled = False
            try:
                announce("Starting gentle movement and expression/audio check")
                mini.enable_motors()
                motors_enabled = True
                mini.wake_up()
                result["warmup_moves"].append("wake_up")
                announce("Robot is awake; moving head, body, and antennas")

                poses = (
                    ("look_left", -10.0, -8.0, 3.0, -4.0, 30.0, 18.0),
                    ("look_right", 10.0, 8.0, -3.0, 4.0, 18.0, 30.0),
                    ("center", 0.0, 0.0, 0.0, 0.0, 20.0, 20.0),
                )
                for (
                    name,
                    body_yaw,
                    head_yaw,
                    pitch,
                    roll,
                    left_antenna,
                    right_antenna,
                ) in poses:
                    mini.goto_target(
                        head=create_head_pose(
                            pitch=math.radians(pitch),
                            yaw=math.radians(head_yaw),
                            roll=math.radians(roll),
                            degrees=False,
                            mm=False,
                        ),
                        antennas=[
                            math.radians(left_antenna),
                            math.radians(right_antenna),
                        ],
                        body_yaw=math.radians(body_yaw),
                        duration=0.8,
                    )
                    result["warmup_moves"].append(name)
                    announce(f"Completed movement: {name}")

                for emotion_name, emotion in zip(EMOTION_NAMES, emotion_moves):
                    announce(f"Playing expression and sound: {emotion_name}")
                    mini.play_move(emotion, initial_goto_duration=0.5)
                    result["expressions"].append(
                        {
                            "name": emotion_name,
                            "duration_seconds": round(emotion.duration, 2),
                        }
                    )
                    result["sound_effects"].append(emotion.sound_path.name)
                announce("All expressions and sound effects completed")
            except Exception as exc:
                result["errors"].append(f"Motion or expression failed: {type(exc).__name__}: {exc}")
            finally:
                announce("Returning to the sleep pose and disabling motors")
                if motors_enabled:
                    try:
                        mini.goto_sleep()
                        result["parked_in_sleep_pose"] = True
                    except Exception as exc:
                        result["errors"].append(
                            f"Could not reach the sleep pose: {type(exc).__name__}: {exc}"
                        )
                    try:
                        mini.disable_motors()
                    except Exception as exc:
                        result["errors"].append(
                            f"Could not release motor torque: {type(exc).__name__}: {exc}"
                        )
    except Exception as exc:
        result["errors"].append(f"Reachy SDK connection failed: {type(exc).__name__}: {exc}")
    finally:
        if motors_may_have_changed:
            try:
                result["motor_mode_after"] = set_global_motor_mode_disabled()
            except Exception as exc:
                result["errors"].append(
                    f"Could not verify disabled motor mode: {type(exc).__name__}: {exc}"
                )

    complete_sequence = (
        len(result["warmup_moves"]) == 4
        and len(result["expressions"]) == len(EMOTION_NAMES)
        and result["parked_in_sleep_pose"]
        and result["motor_mode_after"] == "disabled"
    )
    if complete_sequence and not result["errors"]:
        result["status"] = "passed"
        announce("Movement demo finished; motor mode is disabled")
    else:
        announce("Movement demo did not complete cleanly; see the JSON report")
    return result


def write_report(report: dict) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=REPORT_PATH.parent,
            delete=False,
        ) as report_file:
            json.dump(report, report_file, indent=2, ensure_ascii=False)
            report_file.write("\n")
            temporary_path = Path(report_file.name)
        os.replace(temporary_path, REPORT_PATH)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def main() -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    checks = []
    details = {}
    inventory = None

    inventory_result, specification = check_endpoint(
        "openapi_inventory", "/openapi.json", required=True
    )
    checks.append(inventory_result)
    if inventory_result["status"] == "passed":
        try:
            inventory = inventory_api(specification)
        except (AttributeError, ValueError) as exc:
            inventory_result["status"] = "failed"
            inventory_result["detail"] = str(exc)

    for name, path, required in READ_ONLY_ENDPOINTS:
        result, body = check_endpoint(name, path, required)
        checks.append(result)
        if name == "daemon_status" and isinstance(body, dict):
            backend = body.get("backend_status") or {}
            result["daemon_state"] = body.get("state")
            result["daemon_version"] = body.get("version")
            result["backend_ready"] = backend.get("ready")
            result["motor_control_mode"] = backend.get("motor_control_mode")
            if body.get("state") != "running" or backend.get("ready") is not True:
                result["status"] = "failed"
                result["detail"] = "Reachy daemon is not running and ready"
        elif name == "motor_status" and isinstance(body, dict):
            result["motor_mode"] = body.get("mode")

    try:
        details["camera_frame"] = check_camera_frame()
        checks.append(
            {
                "name": "camera_frame",
                "path": "ReachyMini.media.get_frame",
                "required": True,
                "status": "passed",
                **details["camera_frame"],
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": "camera_frame",
                "path": "ReachyMini.media.get_frame",
                "required": True,
                "status": "failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )

    camera_check = next(check for check in checks if check["name"] == "camera_frame")
    failed_before_motion = any(
        check["required"] and check["status"] == "failed" for check in checks
    )
    if not failed_before_motion and camera_check["status"] == "passed":
        motion_demo = run_motion_and_emotion_demo()
        details["motion_demo"] = motion_demo
        checks.append(
            {
                "name": "motion_emotion_and_sound_demo",
                "path": "ReachyMini.goto_target/play_move/goto_sleep",
                "required": True,
                **motion_demo,
            }
        )
    else:
        checks.append(
            {
                "name": "motion_emotion_and_sound_demo",
                "path": "ReachyMini.goto_target/play_move/goto_sleep",
                "required": True,
                "status": "skipped",
                "detail": "A required API or camera check failed",
            }
        )

    failed_required = sum(
        check["required"] and check["status"] == "failed" for check in checks
    )
    daemon_check = next(
        (check for check in checks if check["name"] == "daemon_status"), {}
    )
    report = {
        "started_at": started_at,
        "daemon_url": DAEMON_URL,
        "daemon_version": daemon_check.get("daemon_version"),
        "motor_control_mode": daemon_check.get("motor_control_mode"),
        "motor_control_mode_after": (details.get("motion_demo") or {}).get(
            "motor_mode_after"
        ),
        "status": "passed" if failed_required == 0 else "failed",
        "summary": {
            "checks": len(checks),
            "passed": sum(check["status"] == "passed" for check in checks),
            "warnings": sum(check["status"] == "warning" for check in checks),
            "failed_required": failed_required,
        },
        "api_inventory": inventory,
        "details": details,
        "checks": checks,
    }

    try:
        write_report(report)
    except OSError as exc:
        print(f"Could not write self-test report: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Self-test report: {REPORT_PATH}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
