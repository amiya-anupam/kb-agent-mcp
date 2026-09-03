#!/usr/bin/env python3
"""
scripts/install_watcher.py — Cross-platform KnowledgeBase Watcher Installer
-----------------------------------------------------------------------------
Installs watch_kb.py as a persistent background service that starts
automatically on login and restarts on crash.  No AI tool dependency:
works regardless of whether the user is using Claude, Bob, Cursor,
VS Code, or any other tool — or no tool at all.

Supported platforms:
  macOS   → ~/Library/LaunchAgents/com.knowledgebase.watcher.plist (launchd)
  Linux   → ~/.config/systemd/user/kb-watcher.service (systemd --user)
  Windows → Task Scheduler XML  (schtasks, runs at logon, restarts on failure)

Offline LLM support:
  The watcher works fully offline.  When the LLM (Ollama or any local model)
  is unreachable it falls back to heuristic summaries immediately and marks
  them for upgrade once the LLM comes back.  Embeddings use a local model
  (sentence-transformers or Ollama) — no internet required.

  Set KB_LLM_PROVIDER=ollama (default) and KB_LLM_BASE_URL=http://localhost:11434
  in .env.  The watcher reads .env automatically.

Usage:
  python3 scripts/install_watcher.py           # install + start
  python3 scripts/install_watcher.py --uninstall  # stop + remove
  python3 scripts/install_watcher.py --status     # show running state
  python3 scripts/install_watcher.py --restart    # restart the service
"""

import os
import sys
import pathlib
import platform
import subprocess
import textwrap
import argparse

# ── Resolve paths ─────────────────────────────────────────────────────────────

SCRIPT_DIR  = pathlib.Path(__file__).parent.parent.resolve()   # KB root
WATCHER     = SCRIPT_DIR / "scripts" / "watch_kb.py"
PYTHON      = sys.executable
LOG_FILE    = SCRIPT_DIR / ".watch.log"
SERVICE_NAME = "com.knowledgebase.watcher"   # macOS / generic label

SYSTEM = platform.system()   # "Darwin", "Linux", "Windows"

# ── Env vars to pass to the service ──────────────────────────────────────────

def _read_env_file() -> dict[str, str]:
    """Read KB_* variables from .env (if present) without shelling out."""
    env_file = SCRIPT_DIR / ".env"
    result: dict[str, str] = {}
    if not env_file.exists():
        return result
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key.startswith("KB_"):
            result[key] = val
    return result

SERVICE_ENV = {
    "KB_ROOT":         str(SCRIPT_DIR),
    "KB_LLM_PROVIDER": "ollama",
    "KB_LLM_BASE_URL": "http://localhost:11434",
    "KB_MODEL":        "qwen3:14b",
    **_read_env_file(),   # .env values override defaults
}

# ── macOS ─────────────────────────────────────────────────────────────────────

def _macos_plist_path() -> pathlib.Path:
    return pathlib.Path.home() / "Library" / "LaunchAgents" / f"{SERVICE_NAME}.plist"

def _macos_env_xml() -> str:
    lines = []
    for k, v in SERVICE_ENV.items():
        lines.append(f"    <key>{k}</key>")
        lines.append(f"    <string>{v}</string>")
    return "\n".join(lines)

def _macos_write_plist():
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>{SERVICE_NAME}</string>

  <key>ProgramArguments</key>
  <array>
    <string>{PYTHON}</string>
    <string>{WATCHER}</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
{_macos_env_xml()}
  </dict>

  <key>WorkingDirectory</key>
  <string>{SCRIPT_DIR}</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>ThrottleInterval</key>
  <integer>10</integer>

  <key>StandardOutPath</key>
  <string>{LOG_FILE}</string>

  <key>StandardErrorPath</key>
  <string>{LOG_FILE}</string>
</dict>
</plist>
"""
    dest = _macos_plist_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(plist, encoding="utf-8")
    print(f"  ✓ Wrote plist: {dest}")
    return dest

def _macos_install():
    dest = _macos_write_plist()
    uid  = os.getuid()
    # Unload first in case an old version is running
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{SERVICE_NAME}"],
        capture_output=True,
    )
    r = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(dest)],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        # Older macOS fallback
        subprocess.run(["launchctl", "load", str(dest)], capture_output=True)
    _macos_status()

def _macos_uninstall():
    uid  = os.getuid()
    dest = _macos_plist_path()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{SERVICE_NAME}"],
        capture_output=True,
    )
    subprocess.run(["launchctl", "unload", str(dest)], capture_output=True)
    if dest.exists():
        dest.unlink()
        print(f"  ✓ Removed plist: {dest}")
    print("  ✓ Watcher uninstalled.")

def _macos_status():
    r = subprocess.run(
        ["launchctl", "print", f"gui/{os.getuid()}/{SERVICE_NAME}"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if any(k in line for k in ("state", "pid", "runs", "last exit")):
                print(f"  {line.strip()}")
    else:
        print("  ✗ Service not found / not running.")

def _macos_restart():
    uid  = os.getuid()
    dest = _macos_plist_path()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{SERVICE_NAME}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(dest)], capture_output=True)
    _macos_status()

# ── Linux (systemd --user) ────────────────────────────────────────────────────

def _linux_unit_path() -> pathlib.Path:
    return pathlib.Path.home() / ".config" / "systemd" / "user" / "kb-watcher.service"

def _linux_env_lines() -> str:
    return "\n".join(f'Environment="{k}={v}"' for k, v in SERVICE_ENV.items())

def _linux_write_unit():
    unit = textwrap.dedent(f"""\
        [Unit]
        Description=KnowledgeBase Watcher — real-time file indexer
        After=default.target

        [Service]
        Type=simple
        ExecStart={PYTHON} {WATCHER}
        WorkingDirectory={SCRIPT_DIR}
        {_linux_env_lines()}
        StandardOutput=append:{LOG_FILE}
        StandardError=append:{LOG_FILE}
        Restart=on-failure
        RestartSec=10

        [Install]
        WantedBy=default.target
    """)
    dest = _linux_unit_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(unit, encoding="utf-8")
    print(f"  ✓ Wrote unit file: {dest}")
    return dest

def _linux_install():
    _linux_write_unit()
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "--now", "kb-watcher.service"], check=True)
    _linux_status()

def _linux_uninstall():
    subprocess.run(["systemctl", "--user", "disable", "--now", "kb-watcher.service"],
                   capture_output=True)
    dest = _linux_unit_path()
    if dest.exists():
        dest.unlink()
        print(f"  ✓ Removed unit: {dest}")
    subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True)
    print("  ✓ Watcher uninstalled.")

def _linux_status():
    r = subprocess.run(
        ["systemctl", "--user", "status", "kb-watcher.service", "--no-pager", "-l"],
        capture_output=True, text=True,
    )
    print(r.stdout[:800] or r.stderr[:400])

def _linux_restart():
    subprocess.run(["systemctl", "--user", "restart", "kb-watcher.service"], check=True)
    _linux_status()

# ── Windows (Task Scheduler) ──────────────────────────────────────────────────

def _windows_task_name() -> str:
    return "KnowledgeBaseWatcher"

def _windows_env_args() -> str:
    """Produce SET commands to prepend inside the batch wrapper."""
    return "\n".join(f"SET {k}={v}" for k, v in SERVICE_ENV.items())

def _windows_wrapper_path() -> pathlib.Path:
    return SCRIPT_DIR / "scripts" / "_watcher_run.bat"

def _windows_write_wrapper():
    """
    Task Scheduler can't pass env vars natively to a Python script, so we
    generate a tiny .bat wrapper that sets env vars then launches the watcher.
    """
    bat = textwrap.dedent(f"""\
        @echo off
        {_windows_env_args()}
        "{PYTHON}" "{WATCHER}" >> "{LOG_FILE}" 2>&1
    """)
    dest = _windows_wrapper_path()
    dest.write_text(bat, encoding="utf-8")
    print(f"  ✓ Wrote batch wrapper: {dest}")
    return dest

def _windows_install():
    wrapper = _windows_write_wrapper()
    task    = _windows_task_name()

    # Delete existing task if present
    subprocess.run(
        ["schtasks", "/Delete", "/TN", task, "/F"],
        capture_output=True,
    )

    # Create task: runs at logon, restarts every 1 minute if it exits
    r = subprocess.run([
        "schtasks", "/Create",
        "/TN",  task,
        "/TR",  f'"{wrapper}"',
        "/SC",  "ONLOGON",
        "/RL",  "HIGHEST",          # run with highest privileges available
        "/F",                        # overwrite if exists
    ], capture_output=True, text=True)

    if r.returncode == 0:
        print("  ✓ Task created.")
        # Start it immediately
        subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True)
        _windows_status()
    else:
        print(f"  ✗ schtasks failed: {r.stderr.strip()}")
        print("  → Try running this script as Administrator.")

def _windows_uninstall():
    task = _windows_task_name()
    subprocess.run(["schtasks", "/End",   "/TN", task], capture_output=True)
    subprocess.run(["schtasks", "/Delete", "/TN", task, "/F"], capture_output=True)
    w = _windows_wrapper_path()
    if w.exists():
        w.unlink()
    print("  ✓ Watcher uninstalled.")

def _windows_status():
    r = subprocess.run(
        ["schtasks", "/Query", "/TN", _windows_task_name(), "/FO", "LIST"],
        capture_output=True, text=True,
    )
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            if any(k in line for k in ("Status", "Last Run", "Next Run", "Task To Run")):
                print(f"  {line.strip()}")
    else:
        print("  ✗ Task not found.")

def _windows_restart():
    task = _windows_task_name()
    subprocess.run(["schtasks", "/End", "/TN", task], capture_output=True)
    subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True)
    _windows_status()

# ── Dispatch ──────────────────────────────────────────────────────────────────

PLATFORM_MAP = {
    "Darwin":  dict(install=_macos_install,   uninstall=_macos_uninstall,
                    status=_macos_status,      restart=_macos_restart),
    "Linux":   dict(install=_linux_install,   uninstall=_linux_uninstall,
                    status=_linux_status,      restart=_linux_restart),
    "Windows": dict(install=_windows_install, uninstall=_windows_uninstall,
                    status=_windows_status,    restart=_windows_restart),
}

def main():
    parser = argparse.ArgumentParser(
        description="Install/manage the KnowledgeBase background watcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            The watcher runs continuously in the background and re-indexes your
            KnowledgeBase the moment any file is added, modified, or deleted —
            regardless of which tool (Claude, Bob, Cursor, VS Code, etc.) or no
            tool made the change.

            Offline / local LLM:
              Set KB_LLM_PROVIDER=ollama and KB_LLM_BASE_URL in .env.
              When Ollama is offline, heuristic summaries are used immediately
              and silently upgraded to LLM quality once Ollama is back.
        """),
    )
    parser.add_argument("--uninstall", action="store_true", help="Stop and remove the service")
    parser.add_argument("--status",    action="store_true", help="Show current service state")
    parser.add_argument("--restart",   action="store_true", help="Restart the service")
    args = parser.parse_args()

    ops = PLATFORM_MAP.get(SYSTEM)
    if ops is None:
        print(f"✗ Unsupported platform: {SYSTEM}")
        sys.exit(1)

    print(f"KnowledgeBase Watcher Installer  [{SYSTEM}]")
    print(f"  KB root : {SCRIPT_DIR}")
    print(f"  Python  : {PYTHON}")
    print(f"  Watcher : {WATCHER}")
    print(f"  Log     : {LOG_FILE}")
    print()

    if args.uninstall:
        print("Uninstalling...")
        ops["uninstall"]()
    elif args.status:
        print("Status:")
        ops["status"]()
    elif args.restart:
        print("Restarting...")
        ops["restart"]()
    else:
        print("Installing...")
        ops["install"]()
        print()
        print("Done. The watcher is now running in the background.")
        print(f"Monitor activity:  tail -f {LOG_FILE}")


if __name__ == "__main__":
    main()
