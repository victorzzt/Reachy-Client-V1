# Agent workspace

Store temporary files the agent creates or downloads under the repository-root `.agent/` directory. Before using it, create the category subdirectories the task is likely to need.

- `.agent/scripts/` for temporary scripts, including downloaded scripts.
- `.agent/data/` for temporary input data and fixtures.
- `.agent/downloads/` for other temporary downloads.
- `.agent/logs/` for temporary logs.
- `.agent/output/` for intermediate results and generated files.

## Reachy Mini

Keep the Reachy Mini project copy, demo, and tests under `/home/pollen/apps` on `192.168.111.101`. After each update, copy the changed files to their matching paths under `/home/pollen/apps` before running them on the robot.

Run robot SDK scripts with `/venvs/apps_venv/bin/python`, the official Reachy Mini apps virtual environment. Do not use the system Python for SDK imports or robot tests.

On the first PSCP or PuTTY connection to the robot, retry a few times when a connection attempt fails.

When updating self-test code or its systemd unit, copy the current src/selftest/ files to /home/pollen/apps/selftest/ before running or installing them. Install the unit under /etc/systemd/system/. The boot self-test intentionally wakes Reachy, performs small head/body/antenna motions, plays the cheerful1, loving1, and laughing1 expressions with their bundled sounds, then returns to sleep and verifies motors are disabled. Preserve this cleanup sequence in all changes.
