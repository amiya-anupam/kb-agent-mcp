"""
tests/test_step1_setup_shim.py
──────────────────────────────
Verifies that scripts/setup.py is a thin shim delegating to kb_agent_mcp.cli.setup.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SHIM = Path(__file__).parent.parent / "scripts" / "setup.py"


class TestSetupShim:

    def test_shim_file_exists(self):
        assert SHIM.exists(), "scripts/setup.py must exist"

    def test_shim_is_small(self):
        """The shim should be ≤ 25 lines — it must not contain the old wizard logic."""
        lines = SHIM.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= 25, (
            f"scripts/setup.py has {len(lines)} lines — expected a small shim. "
            "Did the old wizard code creep back in?"
        )

    def test_shim_references_cli_module(self):
        """The shim must delegate to kb_agent_mcp.cli.setup."""
        content = SHIM.read_text(encoding="utf-8")
        assert "kb_agent_mcp.cli.setup" in content

    def test_shim_help_exits_cleanly(self):
        """Running scripts/setup.py --help must exit 0."""
        result = subprocess.run(
            [sys.executable, str(SHIM), "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"--help exited {result.returncode}: {result.stderr}"
        # Should forward kb-agent-setup's help text
        assert "kb-agent" in result.stdout.lower() or "knowledgebase" in result.stdout.lower()

    def test_shim_does_not_define_functions(self):
        """The shim must not define any Python functions (no old wizard logic)."""
        content = SHIM.read_text(encoding="utf-8")
        assert "def " not in content, "scripts/setup.py must not define functions"
