#!/usr/bin/env python3
"""
scripts/setup.py — compatibility shim
--------------------------------------
Delegates to kb-agent-setup (kb_agent_mcp.cli.setup).

This file exists so that cloned-repo users and the knowledgebase-install
skill can continue to run:
    python3 scripts/setup.py [--yes] [--kb-root /path]

All logic now lives in kb_agent_mcp/cli/setup.py which is also installed
as the `kb-agent-setup` console-script entry point.
"""

import subprocess
import sys

sys.exit(
    subprocess.run(
        [sys.executable, "-m", "kb_agent_mcp.cli.setup"] + sys.argv[1:]
    ).returncode
)
