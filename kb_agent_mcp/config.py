"""
kb_agent_mcp/config.py
─────────────────────
Single source of truth for all configuration.

Usage:
    from kb_agent_mcp.config import cfg

    print(cfg.KB_ROOT)
    print(cfg.KB_MODEL)

All values are read from environment variables (and a .env file if present).
Search order for .env:  CWD → $HOME → package directory.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# ── .env loader ────────────────────────────────────────────────────────────────

def _load_dotenv() -> None:
    """Parse a .env file and inject vars into os.environ (does NOT overwrite)."""
    search_dirs = [
        Path.cwd(),
        Path.home(),
        Path(__file__).parent.parent,  # repo root
    ]
    for directory in search_dirs:
        env_file = directory / ".env"
        if env_file.is_file():
            try:
                with env_file.open() as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "=" not in line:
                            continue
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and key not in os.environ:
                            os.environ[key] = value
            except OSError:
                pass
            break  # stop at first .env found


_load_dotenv()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _str(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _int(key: str, default: int) -> int:
    raw = os.environ.get(key, "").strip()
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def _bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key, "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _list(key: str, default: list[str] | None = None) -> list[str]:
    raw = os.environ.get(key, "").strip()
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


# ── Config dataclass ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Config:
    # ── Knowledge root ────────────────────────────────────────────────────────
    KB_ROOT: str = field(default_factory=lambda: _str(
        "KB_ROOT",
        str(Path.cwd())
    ))
    KB_IGNORE_FOLDERS: list[str] = field(default_factory=lambda: _list(
        "KB_IGNORE_FOLDERS"
    ))

    # ── LLM provider ─────────────────────────────────────────────────────────
    KB_LLM_PROVIDER: str = field(default_factory=lambda: _str(
        "KB_LLM_PROVIDER", "ollama"
    ))
    KB_LLM_BASE_URL: str = field(default_factory=lambda: _str(
        "KB_LLM_BASE_URL", "http://localhost:11434"
    ))
    KB_MODEL: str = field(default_factory=lambda: _str(
        "KB_MODEL", "qwen3:14b"
    ))
    KB_API_KEY: str = field(default_factory=lambda: _str(
        "KB_API_KEY", ""
    ))
    KB_PASSTHROUGH_FALLBACK: bool = field(default_factory=lambda: _bool(
        "KB_PASSTHROUGH_FALLBACK", True
    ))

    # ── Embeddings ────────────────────────────────────────────────────────────
    KB_EMBED_MODEL: str = field(default_factory=lambda: _str(
        "KB_EMBED_MODEL", ""
    ))

    # ── Token / context budgets (all in characters; ~4 chars = 1 token) ──────
    KB_BUDGET_TOTAL: int = field(default_factory=lambda: _int(
        "KB_BUDGET_TOTAL", 24000
    ))
    KB_BUDGET_INDEX: int = field(default_factory=lambda: _int(
        "KB_BUDGET_INDEX", 8000
    ))
    KB_BUDGET_FULL_README: int = field(default_factory=lambda: _int(
        "KB_BUDGET_FULL_README", 24000
    ))
    KB_BUDGET_PRE_INDEX: int = field(default_factory=lambda: _int(
        "KB_BUDGET_PRE_INDEX", 2000
    ))
    KB_BUDGET_RAG_FILE: int = field(default_factory=lambda: _int(
        "KB_BUDGET_RAG_FILE", 4000
    ))
    KB_BUDGET_SUMMARY: int = field(default_factory=lambda: _int(
        "KB_BUDGET_SUMMARY", 500
    ))
    KB_BUDGET_EMBED_CHARS: int = field(default_factory=lambda: _int(
        "KB_BUDGET_EMBED_CHARS", 3500
    ))
    KB_MIN_README_CHARS: int = field(default_factory=lambda: _int(
        "KB_MIN_README_CHARS", 200
    ))
    KB_NUM_CTX: int = field(default_factory=lambda: _int(
        "KB_NUM_CTX", 32768
    ))

    # ── Session memory ────────────────────────────────────────────────────────
    KB_SESSION_TIMEOUT_HOURS: float = field(default_factory=lambda: float(
        _str("KB_SESSION_TIMEOUT_HOURS", "2") or "2"
    ))
    KB_SESSION_MAX_TURNS: int = field(default_factory=lambda: _int(
        "KB_SESSION_MAX_TURNS", 20
    ))
    KB_SESSION_MAX_ANSWER_CHARS: int = field(default_factory=lambda: _int(
        "KB_SESSION_MAX_ANSWER_CHARS", 400
    ))

    # ── File discovery ────────────────────────────────────────────────────────
    KB_STALE_DAYS: int = field(default_factory=lambda: _int(
        "KB_STALE_DAYS", 90
    ))

    # ── Output format ─────────────────────────────────────────────────────────
    KB_FORMAT_DEFAULT: str = field(default_factory=lambda: _str(
        "KB_FORMAT_DEFAULT", ""
    ))

    # ── Derived paths (computed from KB_ROOT) ─────────────────────────────────
    @property
    def kb_root_path(self) -> Path:
        return Path(self.KB_ROOT).expanduser().resolve()

    @property
    def kb_index_path(self) -> Path:
        """ChromaDB + session memory live here — co-located with knowledge docs."""
        return self.kb_root_path / ".kb_index"

    @property
    def session_memory_path(self) -> Path:
        return self.kb_index_path / "session_memory.json"

    # ── Built-in folder blocklist ─────────────────────────────────────────────
    BUILTIN_IGNORE: frozenset[str] = field(default_factory=lambda: frozenset({
        ".kb_index", ".git", ".github", "__pycache__", "node_modules",
        "agents", "scripts", "tests", "dist", "build", ".venv", "venv",
        "kb_agent_mcp",
    }))

    def is_ignored(self, folder_name: str) -> bool:
        """Return True if this folder should be skipped during discovery."""
        lower = folder_name.lower()
        if folder_name in self.BUILTIN_IGNORE:
            return True
        if folder_name.startswith("."):
            return True
        if lower in {f.lower() for f in self.KB_IGNORE_FOLDERS}:
            return True
        return False

    def validate(self) -> list[str]:
        """Return a list of validation error messages (empty = OK)."""
        errors: list[str] = []

        root = self.kb_root_path
        if not root.exists():
            errors.append(f"KB_ROOT does not exist: {root}")
        elif not root.is_dir():
            errors.append(f"KB_ROOT is not a directory: {root}")

        valid_providers = {"ollama", "openai", "anthropic", "custom", "passthrough"}
        if self.KB_LLM_PROVIDER not in valid_providers:
            errors.append(
                f"KB_LLM_PROVIDER '{self.KB_LLM_PROVIDER}' is not valid. "
                f"Choose one of: {', '.join(sorted(valid_providers))}"
            )

        if self.KB_LLM_PROVIDER in {"openai", "anthropic", "custom"} and not self.KB_API_KEY:
            errors.append(
                f"KB_API_KEY is required when KB_LLM_PROVIDER='{self.KB_LLM_PROVIDER}'"
            )

        return errors


# ── Module-level singleton ─────────────────────────────────────────────────────
cfg = Config()
