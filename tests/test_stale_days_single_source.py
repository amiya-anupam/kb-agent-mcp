"""status, doctor and the watcher must share one stale-days default (90)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PROBE = (
    "import sys; sys.path[:0] = [r'%s', r'%s']\n"
    "import kb_agent_mcp.cli.status as s, kb_agent_mcp.cli.doctor as d, watch_kb as w\n"
    "print(s.STALE_DAYS, d.STALE_DAYS, w.STALE_DAYS)\n"
) % (ROOT / "scripts", ROOT / "agents")


def _run(stale=None):
    env = {k: v for k, v in os.environ.items() if k != "KB_STALE_DAYS"}
    env["KB_ROOT"] = str(ROOT)
    if stale is not None:
        env["KB_STALE_DAYS"] = stale
    out = subprocess.run([sys.executable, "-c", _PROBE], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    return out.split()[-3:]


def test_default_is_90_everywhere():
    assert _run() == ["90", "90", "90"]


def test_env_override_reaches_all_three():
    assert _run("30") == ["30", "30", "30"]
