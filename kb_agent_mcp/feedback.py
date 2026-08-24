"""
kb_agent_mcp/feedback.py
────────────────────────
Per-answer feedback / rating store.

Each rating is written as a single JSON object on its own line (JSONL)
to {KB_ROOT}/.kb_index/feedback.jsonl.

Schema per entry:
    {
        "ts":          <unix float>,
        "iso":         "2026-07-31T14:32:01.123Z",
        "session_id":  "user-session-1",
        "question":    "What is the Q3 ACE renewal status?",   (first 500 chars)
        "rating":      4,           # 1–5 (1 = bad, 5 = excellent)
        "comment":     "...",       # optional free-text
        "answer_hash": "a3f2c1"     # sha256[:8] of the answer that was rated
    }

Public API
----------
record(session_id, question, answer, rating, comment) → None
    Append one feedback entry. Silently swallows I/O errors.

read_feedback(limit, session_id, min_rating, max_rating) → list[dict]
    Return the last *limit* entries, optionally filtered.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from kb_agent_mcp.config import cfg

if TYPE_CHECKING:
    from kb_agent_mcp.vector_store import SearchResult

logger = logging.getLogger(__name__)

# Valid rating range
RATING_MIN = 1
RATING_MAX = 5


# ── Helpers ────────────────────────────────────────────────────────────────────

def _feedback_path() -> Path:
    p = cfg.kb_index_path / "feedback.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _answer_hash(answer: str) -> str:
    return hashlib.sha256(answer.encode()).hexdigest()[:8]


# ── Public API ─────────────────────────────────────────────────────────────────

def record(
    session_id: str,
    question: str,
    answer: str,
    rating: int,
    comment: str = "",
) -> None:
    """
    Append one feedback entry.  Never raises — I/O errors are logged and
    swallowed so a feedback failure never impacts query responses.

    Args:
        session_id: The session the answer was delivered in.
        question:   The question that was asked (capped to 500 chars).
        answer:     The answer text (used only to derive a hash for correlation).
        rating:     Integer 1–5.  Values outside this range are clamped.
        comment:    Optional free-text note from the user.
    """
    rating = max(RATING_MIN, min(RATING_MAX, int(rating)))
    now = time.time()
    entry = {
        "ts":          now,
        "iso":         datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
        "session_id":  session_id,
        "question":    question[:500],
        "rating":      rating,
        "comment":     comment[:1000] if comment else "",
        "answer_hash": _answer_hash(answer),
    }
    try:
        path = _feedback_path()
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        # Bust the weight cache so the new rating is visible on the next query
        # without waiting for the full TTL to expire.
        invalidate_weight_cache()
    except OSError as exc:
        logger.warning("Feedback write failed: %s", exc)


def read_feedback(
    limit: int = 50,
    session_id: str | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
) -> list[dict]:
    """
    Return the last *limit* feedback entries from disk (newest-last order).
    Optionally filter by session_id and/or rating range.
    Never raises.
    """
    path = _feedback_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Feedback read failed: %s", exc)
        return []

    entries: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if session_id and entry.get("session_id") != session_id:
            continue
        r = entry.get("rating", 0)
        if min_rating is not None and r < min_rating:
            continue
        if max_rating is not None and r > max_rating:
            continue
        entries.append(entry)
        if len(entries) >= limit:
            break

    return list(reversed(entries))  # chronological order


def summarise_feedback(days: int = 30) -> dict:
    """
    Compute rating statistics from feedback.jsonl over the last *days* days.

    Returns a dict with:
        period_days     - the requested window
        total_ratings   - number of feedback entries in the window
        avg_rating      - mean rating (float, rounded to 2 dp), or None
        rating_dist     - dict mapping "1"–"5" to count
        low_rated       - list of {"question": ..., "rating": ..., "comment": ...}
                          for entries with rating <= 2 (up to 10, newest first)
        no_data         - True when no feedback entries fall within the window
    """
    import time as _time

    cutoff = _time.time() - days * 86400
    path = _feedback_path()
    if not path.exists():
        return {
            "period_days": days,
            "total_ratings": 0,
            "avg_rating": None,
            "rating_dist": {str(i): 0 for i in range(1, 6)},
            "low_rated": [],
            "no_data": True,
        }

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Feedback summarise read failed: %s", exc)
        return {
            "period_days": days,
            "total_ratings": 0,
            "avg_rating": None,
            "rating_dist": {str(i): 0 for i in range(1, 6)},
            "low_rated": [],
            "no_data": True,
        }

    entries: list[dict] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("ts", 0) >= cutoff:
            entries.append(e)

    if not entries:
        return {
            "period_days": days,
            "total_ratings": 0,
            "avg_rating": None,
            "rating_dist": {str(i): 0 for i in range(1, 6)},
            "low_rated": [],
            "no_data": True,
        }

    total = len(entries)
    avg = round(sum(e.get("rating", 0) for e in entries) / total, 2)

    dist: dict[str, int] = {str(i): 0 for i in range(1, 6)}
    low_rated: list[dict] = []
    for e in entries:
        r = e.get("rating", 0)
        key = str(max(1, min(5, r)))
        dist[key] += 1
        if r <= 2:
            low_rated.append({
                "question": e.get("question", ""),
                "rating": r,
                "comment": e.get("comment", ""),
            })

    # newest first, cap at 10
    low_rated = list(reversed(low_rated))[:10]

    return {
        "period_days": days,
        "total_ratings": total,
        "avg_rating": avg,
        "rating_dist": dist,
        "low_rated": low_rated,
        "no_data": False,
    }


# ── Retrieval reweighting ───────────────────────────────────────────────────────
#
# Design notes
# ─────────────
# We need a per-file multiplier in [WEIGHT_MIN, WEIGHT_MAX] that reflects
# accumulated user ratings without ever zeroing a result or locking in early
# noise from a single bad/good rating.
#
# Algorithm:
#   1. Read feedback.jsonl for the last KB_FEEDBACK_DECAY_DAYS days.
#   2. For each feedback entry, look up the corresponding audit entry (same
#      answer_hash) to find which files were cited in that answer.
#   3. Convert the 1–5 rating to a signed sentiment in [-1, +1]:
#        signal = (rating - RATING_MID) / (RATING_MAX - RATING_MID)
#      e.g. rating=5 → +1.0, rating=3 → 0.0, rating=1 → -1.0
#   4. Apply linear time-decay: weight = signal * (age_fraction)
#      where age_fraction = 1.0 for today's entry and 0.0 at the cutoff boundary.
#   5. Accumulate per-file signals, then normalise to [WEIGHT_MIN, WEIGHT_MAX]:
#        raw_weight  = total_signal / max(1, sqrt(n_ratings))   # dampens early noise
#        multiplier  = 1.0 + raw_weight * (WEIGHT_MAX - 1.0)    # positive signal → boost
#                                                               # negative → demote
#        multiplier  = clamp(multiplier, WEIGHT_MIN, WEIGHT_MAX)
#
# The sqrt(n) dampening means a single 5-star rating gives less than a pattern
# of ten 5-star ratings, preventing a noisy first impression from dominating.
#
# Cache: the weight table is rebuilt at most once per KB_WEIGHT_CACHE_TTL_SECONDS
# (default 300 s = 5 min), so new ratings show up quickly without I/O on every query.

_WEIGHT_MIN  = 0.5   # floor multiplier (demoted files keep at least half their score)
_WEIGHT_MAX  = 1.5   # ceiling multiplier (boosted files get at most 1.5× their score)
_RATING_MID  = 3.0   # neutral midpoint of the 1–5 scale
_RATING_SPAN = 2.0   # RATING_MAX - RATING_MID

_KB_WEIGHT_CACHE_TTL = 300.0  # seconds between cache rebuilds

# Module-level cache: (weights_dict, built_at_monotonic)
_weight_cache: tuple[dict[str, float], float] | None = None


def _load_audit_hash_to_files() -> dict[str, list[str]]:
    """
    Build a mapping from answer_hash → list[file_path] by reading audit.jsonl.

    Uses the audit log (not feedback) because that's where files_cited lives.
    Reads both the current log and the rotated archive.
    Never raises — returns {} on any I/O error.
    """
    from kb_agent_mcp.config import cfg as _cfg  # avoid circular at module load
    audit_path = _cfg.kb_index_path / "audit.jsonl"
    hash_to_files: dict[str, list[str]] = {}

    candidates = [audit_path, audit_path.with_suffix(".jsonl.1")]
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                h = e.get("answer_hash", "")
                files = e.get("files_cited") or []
                if h and files:
                    # Later entries (same hash) overwrite earlier ones — latest wins.
                    hash_to_files[h] = list(files)
        except OSError as exc:
            logger.warning("Reweight: audit read failed (%s): %s", path, exc)

    return hash_to_files


def build_file_weights(decay_days: int | None = None) -> dict[str, float]:
    """
    Return a dict mapping relative file path → score multiplier in [0.5, 1.5].

    Paths use the same format as SearchResult.path (relative to KB_ROOT).
    Files with no feedback history map to 1.0 (neutral — no boost/demotion).

    The result is cached for KB_WEIGHT_CACHE_TTL_SECONDS (default 5 min).
    Call invalidate_weight_cache() to force a rebuild (e.g. after rate_answer()).

    Args:
        decay_days: Override KB_FEEDBACK_DECAY_DAYS for the look-back window.
                    Defaults to cfg.KB_FEEDBACK_DECAY_DAYS.

    Never raises.
    """
    import math

    global _weight_cache

    now_mono = time.monotonic()
    if _weight_cache is not None:
        weights, built_at = _weight_cache
        if now_mono - built_at < _KB_WEIGHT_CACHE_TTL:
            return weights

    if decay_days is None:
        decay_days = cfg.KB_FEEDBACK_DECAY_DAYS

    now_ts   = time.time()
    cutoff   = now_ts - decay_days * 86400

    # ── Step 1: load audit hash→files mapping ─────────────────────────────────
    hash_to_files = _load_audit_hash_to_files()

    # ── Step 2: read feedback entries within the window ───────────────────────
    path = _feedback_path()
    if not path.exists():
        _weight_cache = ({}, now_mono)
        return {}

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        logger.warning("Reweight: feedback read failed: %s", exc)
        _weight_cache = ({}, now_mono)
        return {}

    # Accumulate per-file: {file_path: [weighted_signal, ...]}
    file_signals: dict[str, list[float]] = {}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = e.get("ts", 0.0)
        if ts < cutoff:
            continue

        rating = e.get("rating", 0)
        answer_hash = e.get("answer_hash", "")
        files = hash_to_files.get(answer_hash, [])
        if not files:
            continue

        # Signed sentiment: +1.0 for 5★, 0.0 for 3★, -1.0 for 1★
        sentiment = (float(rating) - _RATING_MID) / _RATING_SPAN

        # Linear time-decay: entries at the cutoff boundary count as 0,
        # entries from right now count as 1.
        age_frac = (ts - cutoff) / max(decay_days * 86400, 1.0)
        weighted_signal = sentiment * age_frac

        for file_path in files:
            file_signals.setdefault(file_path, []).append(weighted_signal)

    if not file_signals:
        _weight_cache = ({}, now_mono)
        return {}

    # ── Step 3: normalise to multiplier ───────────────────────────────────────
    weights: dict[str, float] = {}
    for file_path, signals in file_signals.items():
        n = len(signals)
        # sqrt(n) dampening reduces the influence of a single isolated rating
        raw = sum(signals) / math.sqrt(max(n, 1))
        # Map raw ∈ [-1, +1] (approximately) → multiplier ∈ [WEIGHT_MIN, WEIGHT_MAX]
        # raw=+1 → WEIGHT_MAX, raw=0 → 1.0, raw=-1 → WEIGHT_MIN
        multiplier = 1.0 + raw * (_WEIGHT_MAX - 1.0)
        weights[file_path] = max(_WEIGHT_MIN, min(_WEIGHT_MAX, multiplier))

    _weight_cache = (weights, now_mono)
    return weights


def invalidate_weight_cache() -> None:
    """
    Force the next build_file_weights() call to rebuild from disk.

    Called automatically by record() so a new rating is reflected within
    the next search cycle rather than waiting out the full TTL.
    """
    global _weight_cache
    _weight_cache = None


def apply_feedback_weights(
    results: "list[SearchResult]",
    weights: dict[str, float],
) -> "list[SearchResult]":
    """
    Multiply each result's score by the file's feedback weight and re-sort.

    Args:
        results: Ordered list of SearchResult dicts from the retrieval layer.
        weights: Mapping from file path → multiplier (from build_file_weights()).

    Returns:
        A new list of the same dicts (score field mutated in-place on copies),
        sorted descending by the adjusted score.  Scores are clamped to [0.0, 1.0].

    If *weights* is empty the original list is returned unchanged (zero overhead
    on the hot path when no feedback exists yet).
    """
    if not weights:
        return results

    adjusted: list = []
    for r in results:
        w = weights.get(r["path"], 1.0)
        if w == 1.0:
            adjusted.append(r)
        else:
            new_score = max(0.0, min(1.0, r["score"] * w))
            adjusted.append({**r, "score": new_score})

    adjusted.sort(key=lambda r: r["score"], reverse=True)
    return adjusted
