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
    # KB_ROOT may already be in the environment before .env is loaded —
    # include it as a search dir so a .env co-located with the knowledge
    # base is found even when the server is launched from a different CWD.
    kb_root_env = os.environ.get("KB_ROOT", "").strip()
    search_dirs = [
        Path.cwd(),
        Path.home(),
        Path(kb_root_env) if kb_root_env else None,  # KB_ROOT/.env (Risk 8)
        Path(__file__).parent.parent,  # repo root
    ]
    search_dirs = [d for d in search_dirs if d is not None]
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

    @property
    def kb_root_is_explicit(self) -> bool:
        """True only when KB_ROOT was set explicitly in the environment or .env file.

        When False the value is the CWD fallback, which is almost never the
        knowledge base on a typical MCP host (Claude Desktop, Bob, Cursor).
        Use this to emit a clear warning at startup rather than silently
        returning empty results.
        """
        return "KB_ROOT" in os.environ

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
    # Optional override: provider to use for kb-agent-generate (Risk 4).
    # Written by setup wizard when user is passthrough + has an API key.
    # Empty string means "use KB_LLM_PROVIDER".
    KB_LLM_PROVIDER_GENERATE: str = field(default_factory=lambda: _str(
        "KB_LLM_PROVIDER_GENERATE", ""
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

    # ── Stale-index TTL cache (Risk 11) ───────────────────────────────────────
    # Seconds between filesystem mtime scans in ask(). 0 = disabled.
    KB_STALE_CHECK_TTL_SECONDS: int = field(default_factory=lambda: _int(
        "KB_STALE_CHECK_TTL_SECONDS", 60
    ))

    # ── Passthrough budget threshold (Risk 14) ────────────────────────────────
    # Fraction of KB_BUDGET_TOTAL at which top_n is auto-reduced (0.0–1.0).
    KB_BUDGET_PASSTHROUGH_THRESHOLD: float = field(default_factory=lambda: float(
        _str("KB_BUDGET_PASSTHROUGH_THRESHOLD", "0.8") or "0.8"
    ))

    # ── Security gate ─────────────────────────────────────────────────────────
    # Set KB_SECURITY_GATE_ENABLED=false to disable the confidentiality gate
    # entirely (e.g. fully air-gapped, private Ollama-only installs where all
    # documents are already trusted).  Enabled by default.
    KB_SECURITY_GATE_ENABLED: bool = field(default_factory=lambda: _bool(
        "KB_SECURITY_GATE_ENABLED", True
    ))

    # ── Default session identity ──────────────────────────────────────────────
    # When set, this name is used as the default session_id instead of
    # "default".  Set KB_DEFAULT_SESSION_ID to a stable value so conversation
    # history accumulates under a persistent session that survives server
    # restarts and reconnects.  Leave blank to keep the original behaviour.
    KB_DEFAULT_SESSION_ID: str = field(default_factory=lambda: _str(
        "KB_DEFAULT_SESSION_ID", ""
    ))

    # ── Audit log ─────────────────────────────────────────────────────────────
    # Set KB_AUDIT_ENABLED=false to disable audit logging entirely.
    KB_AUDIT_ENABLED: bool = field(default_factory=lambda: _bool(
        "KB_AUDIT_ENABLED", True
    ))
    # Rotate audit log when it exceeds this size in MB.
    KB_AUDIT_MAX_MB: int = field(default_factory=lambda: _int(
        "KB_AUDIT_MAX_MB", 50
    ))

    # ── Image OCR ─────────────────────────────────────────────────────────────
    # Set KB_OCR_ENABLED=false to disable image text extraction entirely.
    # When enabled, the system tries pytesseract first (if installed), then
    # falls back to PIL metadata (dimensions, mode).
    KB_OCR_ENABLED: bool = field(default_factory=lambda: _bool(
        "KB_OCR_ENABLED", True
    ))
    # OCR engine to use: "tesseract" (pytesseract only), "auto" (tesseract
    # then PIL fallback).  "auto" is the default and recommended setting.
    KB_OCR_ENGINE: str = field(default_factory=lambda: _str(
        "KB_OCR_ENGINE", "auto"
    ))

    # ── Re-ranker ─────────────────────────────────────────────────────────────
    # Set KB_RERANKER_ENABLED=false to skip the cross-encoder re-ranking pass.
    # Useful when sentence-transformers is absent or for latency-critical use.
    KB_RERANKER_ENABLED: bool = field(default_factory=lambda: _bool(
        "KB_RERANKER_ENABLED", True
    ))
    # Cross-encoder model name (must be loadable by sentence-transformers).
    # Defaults to the compact MiniLM model (~80 MB, CPU-friendly).
    KB_RERANKER_MODEL: str = field(default_factory=lambda: _str(
        "KB_RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
    ))
    # Candidate pool size fed to the re-ranker.  Defaults to 20; actual fetch is
    # max(top_n * 4, KB_RERANKER_CANDIDATES) so small top_n always get enough candidates.
    KB_RERANKER_CANDIDATES: int = field(default_factory=lambda: _int(
        "KB_RERANKER_CANDIDATES", 20
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
        # Exclude Python packaging artifacts — .egg-info and .dist-info directories
        # are generated by pip/setuptools and must never become knowledge domains.
        if lower.endswith(".egg-info") or lower.endswith(".dist-info"):
            return True
        if lower in {f.lower() for f in self.KB_IGNORE_FOLDERS}:
            return True
        return False

    def validate(self) -> list[str]:
        """Return a list of validation error messages (empty = OK)."""
        errors: list[str] = []

        raw_root = self.KB_ROOT.strip()
        if not raw_root:
            errors.append(
                "KB_ROOT is not set or is empty. "
                "Set KB_ROOT to the absolute path of your knowledge base folder."
            )
            return errors

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

# ── Shared API constants ───────────────────────────────────────────────────────
ANTHROPIC_API_VERSION = "2023-06-01"
