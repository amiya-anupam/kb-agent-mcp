"""
kb_agent_mcp/security_gate.py
──────────────────────────────
Anti-trick security gate for confidential documents.

Patentable mechanism
────────────────────
When a scan finds confidential-flagged files, a one-time random token is
generated with secrets.token_hex(4) and printed to the MCP response.  The
user must type that token back in a subsequent acknowledge_gate() call.

Because the token is generated fresh on every check_confidential() call, a
malicious document cannot pre-plant the correct value — the token did not
exist when the document was ingested.  Only the live user, reading the
terminal/chat, can supply the right value.

Classification pipeline (checked in priority order, first match wins)
──────────────────────────────────────────────────────────────────────
1. EML Sensitivity header
2. PDF /Keywords + /Subject metadata fields
3. DOCX core_properties.category + .keywords
4. File path / filename (full path string)
5. Extracted text body (first KB_BUDGET_RAG_FILE chars)

.noindex sentinel
─────────────────
Any file whose ancestor folder contains a `.noindex` file is hard-excluded —
it never appears in scan results and its content never enters any context.
This is enforced here (scan time) AND in file_parser.should_skip() (index time).

Public API
──────────
classify_confidential(path)            → (is_confidential: bool, reason: str)
scan_domain(domain_name)               → list[ConfidentialEntry]
scan_all_domains()                     → list[ConfidentialEntry]
generate_ack_token()                   → str   (8 hex chars, uppercase)
validate_ack_token(stored, provided)   → bool  (constant-time compare)
load_gate_session(session_id)          → GateSession
save_gate_session(session)             → None
clear_gate_session(session_id)         → None
is_gate_acknowledged(session_id)       → bool
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import pathlib
import re
import secrets
import time
import zipfile
from dataclasses import dataclass, field, asdict
from typing import Any

from kb_agent_mcp.config import cfg
from kb_agent_mcp.file_parser import _has_noindex_ancestor

logger = logging.getLogger(__name__)

# ── Confidentiality keyword list (matches old architecture §14) ───────────────

_CONFIDENTIAL_RE = re.compile(
    r"\b("
    r"confidential|internal use only|not for distribution|not for sharing|"
    r"do not share|do not distribute|proprietary|restricted|privileged|"
    r"ibm confidential|company confidential|for internal use|classification:|"
    r"sensitive|top secret|private and confidential"
    r")\b",
    re.IGNORECASE,
)

# EML Sensitivity header values that indicate confidentiality
_EML_SENSITIVE_VALUES = frozenset({
    "confidential", "company-confidential", "personal", "private", "restricted",
})

# ── Per-format classifiers ────────────────────────────────────────────────────

def _classify_eml(path: pathlib.Path) -> tuple[bool, str]:
    """Check EML Sensitivity header first — highest priority."""
    try:
        import email
        msg = email.message_from_bytes(path.read_bytes())
        sensitivity = (msg.get("Sensitivity") or "").strip().lower()
        if sensitivity in _EML_SENSITIVE_VALUES:
            return True, f"EML Sensitivity header: {sensitivity!r}"
    except Exception as exc:
        logger.debug("EML classification failed for %s: %s", path.name, exc)
    return False, ""


def _classify_pdf(path: pathlib.Path) -> tuple[bool, str]:
    """Check PDF /Keywords and /Subject metadata."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(path))
        meta = reader.metadata or {}
        for field_name in ("/Keywords", "/Subject"):
            value = str(meta.get(field_name) or "")
            if _CONFIDENTIAL_RE.search(value):
                return True, f"PDF metadata field {field_name!r}"
    except Exception as exc:
        logger.debug("PDF metadata classification failed for %s: %s", path.name, exc)
    return False, ""


def _classify_docx(path: pathlib.Path) -> tuple[bool, str]:
    """Check DOCX core_properties.category and .keywords."""
    try:
        with zipfile.ZipFile(path) as z:
            if "docProps/core.xml" in z.namelist():
                xml = z.read("docProps/core.xml").decode("utf-8", errors="ignore")
                if _CONFIDENTIAL_RE.search(xml):
                    return True, "DOCX core properties (category/keywords)"
    except Exception as exc:
        logger.debug("DOCX classification failed for %s: %s", path.name, exc)
    return False, ""


def _classify_path(path: pathlib.Path) -> tuple[bool, str]:
    """Check the full file path string.

    Underscores and hyphens in filenames act as word separators
    (e.g. 'my_confidential_doc.pdf'), so we normalise them to spaces
    before running the word-boundary regex.
    """
    normalised = str(path).replace("_", " ").replace("-", " ")
    if _CONFIDENTIAL_RE.search(normalised):
        return True, "filename / folder path"
    return False, ""


def _classify_text_body(path: pathlib.Path) -> tuple[bool, str]:
    """Scan the first KB_BUDGET_RAG_FILE chars of the file's text content."""
    try:
        from kb_agent_mcp.file_parser import _extract_sync
        max_chars = cfg.KB_BUDGET_RAG_FILE
        text = _extract_sync(path, max_chars)
        match = _CONFIDENTIAL_RE.search(text)
        if match:
            return True, f"text body keyword: {match.group(0)!r}"
    except Exception as exc:
        logger.debug("Text body classification failed for %s: %s", path.name, exc)
    return False, ""


# ── Main classification entry point ──────────────────────────────────────────

def classify_confidential(path: pathlib.Path) -> tuple[bool, str]:
    """
    Return (is_confidential, reason_string).

    Checks signal sources in priority order; returns on first match.
    Returns (False, "") when no confidential signal is found.

    .noindex files are always treated as not-confidential here because
    they are filtered out before reaching this function (scan_domain skips them).
    """
    ext = path.suffix.lower()

    # Priority 1 — EML Sensitivity header
    if ext == ".eml":
        found, reason = _classify_eml(path)
        if found:
            return True, reason

    # Priority 2 — PDF metadata
    if ext == ".pdf":
        found, reason = _classify_pdf(path)
        if found:
            return True, reason

    # Priority 3 — DOCX core properties
    if ext == ".docx":
        found, reason = _classify_docx(path)
        if found:
            return True, reason

    # Priority 4 — file path / filename
    found, reason = _classify_path(path)
    if found:
        return True, reason

    # Priority 5 — text body
    found, reason = _classify_text_body(path)
    if found:
        return True, reason

    return False, ""


# ── Domain scanner ────────────────────────────────────────────────────────────

@dataclass
class ConfidentialEntry:
    domain: str
    relative_path: str   # relative to KB_ROOT
    filename: str
    reason: str


def scan_domain(domain_name: str) -> list[ConfidentialEntry]:
    """
    Walk every indexed file in *domain_name* and return entries for those
    that are classified as confidential.

    Respects .noindex sentinel — files in .noindex folders are silently skipped.
    """
    from kb_agent_mcp.file_parser import INCLUDE_EXTS, should_skip

    results: list[ConfidentialEntry] = []
    folder = cfg.kb_root_path / domain_name
    if not folder.is_dir():
        return results

    for file_path in sorted(folder.rglob("*")):
        if not file_path.is_file():
            continue
        if file_path.suffix.lower() not in INCLUDE_EXTS:
            continue
        if should_skip(file_path):
            continue
        if _has_noindex_ancestor(file_path):
            continue

        is_conf, reason = classify_confidential(file_path)
        if is_conf:
            try:
                rel = str(file_path.relative_to(cfg.kb_root_path))
            except ValueError:
                rel = str(file_path)
            results.append(ConfidentialEntry(
                domain=domain_name,
                relative_path=rel,
                filename=file_path.name,
                reason=reason,
            ))

    return results


def scan_all_domains() -> list[ConfidentialEntry]:
    """Scan every non-ignored domain under KB_ROOT."""
    results: list[ConfidentialEntry] = []
    try:
        for entry in sorted(cfg.kb_root_path.iterdir()):
            if entry.is_dir() and not cfg.is_ignored(entry.name):
                results.extend(scan_domain(entry.name))
    except Exception as exc:
        logger.warning("scan_all_domains failed: %s", exc)
    return results


# ── Token generation & validation ─────────────────────────────────────────────

def generate_ack_token() -> str:
    """
    Generate a fresh one-time acknowledgement token.

    Uses secrets.token_hex() — cryptographic OS entropy, zero network calls.
    Returns 8 uppercase hex characters (e.g. "B7E2A3F1").

    Because this is called at check_confidential() time, the token cannot
    be pre-planted in any document that was indexed before the call.
    """
    return secrets.token_hex(4).upper()


def validate_ack_token(stored: str, provided: str) -> bool:
    """
    Constant-time comparison of the stored and user-provided tokens.

    Uses hmac.compare_digest to prevent timing oracle attacks.
    Both values are normalised to uppercase before comparison.
    """
    return hmac.compare_digest(stored.upper(), provided.strip().upper())


# ── GateSession persistence ───────────────────────────────────────────────────

_GATE_SESSIONS_FILE = "gate_sessions.json"


@dataclass
class GateSession:
    session_id: str
    status: str                          # "blocked" | "acknowledged" | "clear"
    ack_token: str                       # generated token (never logged to answers)
    confidential_files: list[dict]       # list of ConfidentialEntry dicts
    created_at: float = field(default_factory=time.time)
    acknowledged_at: float = 0.0


def _gate_sessions_path() -> pathlib.Path:
    path = cfg.kb_index_path / _GATE_SESSIONS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_all_sessions() -> dict[str, Any]:
    p = _gate_sessions_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_all_sessions(data: dict[str, Any]) -> None:
    p = _gate_sessions_path()
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_gate_session(session_id: str) -> GateSession | None:
    """Return the GateSession for *session_id*, or None if not found."""
    data = _load_all_sessions()
    raw = data.get(session_id)
    if raw is None:
        return None
    return GateSession(
        session_id=raw["session_id"],
        status=raw["status"],
        ack_token=raw["ack_token"],
        confidential_files=raw.get("confidential_files", []),
        created_at=raw.get("created_at", 0.0),
        acknowledged_at=raw.get("acknowledged_at", 0.0),
    )


def save_gate_session(session: GateSession) -> None:
    """Persist *session* to disk.  The ack_token is stored but never surfaced
    in answers — it is only used for validation inside acknowledge_gate()."""
    data = _load_all_sessions()
    data[session.session_id] = asdict(session)
    _save_all_sessions(data)


def clear_gate_session(session_id: str) -> None:
    """Remove the GateSession for *session_id* (called by reindex)."""
    data = _load_all_sessions()
    data.pop(session_id, None)
    _save_all_sessions(data)


def clear_all_gate_sessions() -> None:
    """Remove all gate sessions — called after a full reindex so every
    session must re-acknowledge against the fresh file inventory."""
    p = _gate_sessions_path()
    if p.exists():
        p.write_text("{}", encoding="utf-8")


def is_gate_acknowledged(session_id: str) -> bool:
    """
    Return True when the session has already passed the gate, or when the
    security gate is globally disabled (KB_SECURITY_GATE_ENABLED=false).
    """
    if not cfg.KB_SECURITY_GATE_ENABLED:
        return True
    sess = load_gate_session(session_id)
    if sess is None:
        return False
    return sess.status in ("acknowledged", "clear")
