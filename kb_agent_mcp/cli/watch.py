"""
kb_agent_mcp/cli/watch.py — Filesystem watcher
------------------------------------------------
Watches KB_ROOT for changes and keeps ChromaDB indexes in sync.

Events handled:
  FILE ADDED/MODIFIED → re-embed into ChromaDB
  FILE DELETED        → remove from ChromaDB
  FILE RENAMED        → remove old path + embed new path
  FOLDER CREATED      → run kb-agent-generate (prompt Accept/Skip for new domain)
  FOLDER DELETED      → delete ChromaDB collection for that domain

New-folder workflow:
  When a new top-level folder appears, the watcher auto-generates a
  domain_config.yaml (with Accept/Skip prompt) and begins watching it.
  The prompt is printed to the terminal — the user types A or S.

Usage:
  kb-agent-watch
  kb-agent-watch --no-prompt   # auto-accept new folders (CI/headless)
"""

from __future__ import annotations

import asyncio
import sys
import time
import logging
import argparse
from pathlib import Path

logger = logging.getLogger("kb-agent-watch")


INCLUDE_EXTS  = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".md", ".txt",
    ".csv", ".boxnote", ".ppt", ".doc",
}
SKIP_PATTERNS = {"readme", ".ds_store", ".kb_index", "__pycache__"}
DEBOUNCE_SECS = 5.0


def _should_skip(path: Path) -> bool:
    return any(p in path.name.lower() for p in SKIP_PATTERNS)


def _top_folder(path: Path, kb_root: Path) -> str | None:
    try:
        rel = path.relative_to(kb_root)
        return rel.parts[0] if rel.parts else None
    except ValueError:
        return None


# ── Async watcher ──────────────────────────────────────────────────────────────

class _KBWatcher:
    """
    Async event processor backed by watchdog for filesystem events.

    Files are debounced: we accumulate events for DEBOUNCE_SECS then flush.
    Folder create/delete are handled immediately (no debounce needed).
    """

    def __init__(self, kb_root: Path, no_prompt: bool = False):
        self.kb_root   = kb_root
        self.no_prompt = no_prompt
        self._pending_index:   dict[str, set[Path]] = {}  # folder_name → files
        self._pending_deindex: dict[str, set[Path]] = {}
        self._pending_readme:  dict[str, float]     = {}  # folder_name → deadline
        self._known_folders:   set[str]             = set()

    async def start(self) -> None:
        from kb_agent_mcp.config import cfg

        # Discover existing folders
        for entry in sorted(self.kb_root.iterdir()):
            if entry.is_dir() and not cfg.is_ignored(entry.name):
                self._known_folders.add(entry.name)

        logger.info("Watching %s  (%d domains)", self.kb_root, len(self._known_folders))
        for name in sorted(self._known_folders):
            logger.info("  → %s/", name)

        # Start watchdog in a background thread
        loop = asyncio.get_event_loop()
        observer = await asyncio.to_thread(self._make_observer, loop)
        observer.start()

        try:
            while True:
                await asyncio.sleep(1.0)
                await self._dispatch_pending()
                await self._poll_folder_changes()
        finally:
            observer.stop()
            observer.join()

    def _make_observer(self, loop: asyncio.AbstractEventLoop):
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler

        watcher = self

        class _Handler(FileSystemEventHandler):
            def _schedule(self, coro):
                asyncio.run_coroutine_threadsafe(coro, loop)

            def on_created(self, event):
                self._schedule(watcher._on_created(event.src_path, event.is_directory))

            def on_deleted(self, event):
                self._schedule(watcher._on_deleted(event.src_path, event.is_directory))

            def on_modified(self, event):
                if not event.is_directory:
                    self._schedule(watcher._on_modified(event.src_path))

            def on_moved(self, event):
                self._schedule(watcher._on_moved(event.src_path, event.dest_path,
                                                  event.is_directory))

        observer = Observer()
        observer.schedule(_Handler(), str(self.kb_root), recursive=True)
        return observer

    # ── Event handlers (called from watchdog thread via run_coroutine_threadsafe) ─

    async def _on_created(self, src: str, is_dir: bool) -> None:
        path = Path(src)
        if is_dir:
            if path.parent == self.kb_root:
                from kb_agent_mcp.config import cfg
                if not cfg.is_ignored(path.name) and path.name not in self._known_folders:
                    logger.info("📁 New folder: %s → scheduling generate", path.name)
                    self._known_folders.add(path.name)
                    asyncio.create_task(self._generate_new_domain(path.name))
            return
        folder_name = _top_folder(path, self.kb_root)
        if not folder_name or _should_skip(path) or path.suffix.lower() not in INCLUDE_EXTS:
            return
        logger.info("＋ %s in %s", path.name, folder_name)
        self._pending_index.setdefault(folder_name, set()).add(path)
        self._pending_readme[folder_name] = time.time() + DEBOUNCE_SECS

    async def _on_deleted(self, src: str, is_dir: bool) -> None:
        path = Path(src)
        if is_dir and path.parent == self.kb_root:
            if path.name in self._known_folders:
                logger.info("🗑 Folder deleted: %s → purging collection", path.name)
                self._known_folders.discard(path.name)
                await self._purge_domain(path.name)
            return
        folder_name = _top_folder(path, self.kb_root)
        if not folder_name or path.suffix.lower() not in INCLUDE_EXTS:
            return
        logger.info("✕ %s deleted from %s", path.name, folder_name)
        self._pending_deindex.setdefault(folder_name, set()).add(path)
        self._pending_readme[folder_name] = time.time() + DEBOUNCE_SECS

    async def _on_modified(self, src: str) -> None:
        path = Path(src)
        folder_name = _top_folder(path, self.kb_root)
        if not folder_name or _should_skip(path) or path.suffix.lower() not in INCLUDE_EXTS:
            return
        logger.info("✎ %s modified in %s", path.name, folder_name)
        self._pending_index.setdefault(folder_name, set()).add(path)
        self._pending_readme[folder_name] = time.time() + DEBOUNCE_SECS

    async def _on_moved(self, src: str, dest: str, is_dir: bool) -> None:
        src_path  = Path(src)
        dest_path = Path(dest)
        src_folder  = _top_folder(src_path,  self.kb_root)
        dest_folder = _top_folder(dest_path, self.kb_root)

        if src_folder and src_path.suffix.lower() in INCLUDE_EXTS and not _should_skip(src_path):
            self._pending_deindex.setdefault(src_folder, set()).add(src_path)
            self._pending_readme[src_folder] = time.time() + DEBOUNCE_SECS

        if dest_folder and dest_path.suffix.lower() in INCLUDE_EXTS and not _should_skip(dest_path):
            self._pending_index.setdefault(dest_folder, set()).add(dest_path)
            self._pending_readme[dest_folder] = time.time() + DEBOUNCE_SECS

    # ── Debounce dispatcher ─────────────────────────────────────────────────────

    async def _dispatch_pending(self) -> None:
        from kb_agent_mcp.vector_store import upsert_file, delete_file

        now = time.time()

        for folder_name, deadline in list(self._pending_readme.items()):
            if now < deadline:
                continue

            # Deindex first
            if folder_name in self._pending_deindex:
                for fp in self._pending_deindex.pop(folder_name):
                    try:
                        await delete_file(folder_name, fp)
                        logger.info("  ✓ Removed from index: %s", fp.name)
                    except Exception as e:
                        logger.warning("  ✗ Deindex failed for %s: %s", fp.name, e)

            # Then index new/modified files
            if folder_name in self._pending_index:
                for fp in self._pending_index.pop(folder_name):
                    if not fp.exists():
                        continue
                    try:
                        await upsert_file(folder_name, fp)
                        logger.info("  ✓ Indexed: %s", fp.name)
                    except Exception as e:
                        logger.warning("  ✗ Index failed for %s: %s", fp.name, e)

            del self._pending_readme[folder_name]

    # ── Poll for new/deleted folders (macOS coalesces some dir events) ──────────

    async def _poll_folder_changes(self) -> None:
        from kb_agent_mcp.config import cfg
        try:
            entries = {
                e.name for e in self.kb_root.iterdir()
                if e.is_dir() and not cfg.is_ignored(e.name)
            }
        except Exception:
            return

        new_folders     = entries - self._known_folders
        deleted_folders = self._known_folders - entries

        for name in new_folders:
            logger.info("📁 New folder (poll): %s → scheduling generate", name)
            self._known_folders.add(name)
            asyncio.create_task(self._generate_new_domain(name))

        for name in deleted_folders:
            logger.info("🗑 Folder gone (poll): %s → purging", name)
            self._known_folders.discard(name)
            await self._purge_domain(name)

    # ── Domain create/delete ────────────────────────────────────────────────────

    async def _generate_new_domain(self, folder_name: str) -> None:
        """Run the generate flow for a newly discovered folder."""
        from kb_agent_mcp.vector_store import build_collection
        from kb_agent_mcp.orchestrator import refresh_agents
        from kb_agent_mcp.config import cfg

        folder    = self.kb_root / folder_name
        yaml_path = folder / "domain_config.yaml"

        # Build ChromaDB index
        try:
            count = await build_collection(folder_name)
            logger.info("  ✓ %s: %d files indexed", folder_name, count)
        except Exception as e:
            logger.error("  ✗ Index failed for %s: %s", folder_name, e)
            return

        if yaml_path.exists():
            logger.info("  domain_config.yaml already exists — skipping YAML generation")
            await refresh_agents()
            return

        # Generate minimal YAML (or prompt)
        if self.no_prompt:
            from kb_agent_mcp.cli.generate import _minimal_yaml
            yaml_path.write_text(_minimal_yaml(folder_name), encoding="utf-8")
            logger.info("  ✓ Wrote minimal domain_config.yaml for %s", folder_name)
        else:
            import subprocess
            logger.info("  Running kb-agent-generate --domain %s …", folder_name)
            subprocess.run(
                [sys.executable, "-m", "kb_agent_mcp.cli.generate",
                 "--domain", folder_name],
            )

        await refresh_agents()

    async def _purge_domain(self, folder_name: str) -> None:
        """Delete the ChromaDB collection for a removed domain."""
        try:
            import chromadb
            from kb_agent_mcp.config import cfg
            client = chromadb.PersistentClient(
                path=str(cfg.kb_index_path / "chroma")
            )
            safe = re.sub(r"[^a-z0-9_]", "_", folder_name.lower())
            try:
                client.delete_collection(safe)
                logger.info("  ✓ ChromaDB collection deleted: %s", safe)
            except Exception:
                pass
        except Exception as e:
            logger.warning("  ✗ Could not purge collection for %s: %s", folder_name, e)

        from kb_agent_mcp.orchestrator import refresh_agents
        await refresh_agents()


# ── Entry point ────────────────────────────────────────────────────────────────

import re  # imported here so _purge_domain can use it without a top-level import conflict


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kb-agent-watch",
        description="Watch KB_ROOT for file changes and keep ChromaDB indexes in sync.",
    )
    parser.add_argument("--no-prompt", action="store_true",
                        help="Auto-accept new folders without prompting (headless/CI mode)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="[KB Watch] %(message)s",
        stream=sys.stdout,
    )

    from kb_agent_mcp.config import cfg
    kb_root = cfg.kb_root_path

    if not kb_root.exists():
        logger.error("KB_ROOT does not exist: %s", kb_root)
        logger.error("Check KB_ROOT in your .env or run kb-agent-setup")
        sys.exit(1)

    errors = cfg.validate()
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Starting — watching %s", kb_root)

    watcher = _KBWatcher(kb_root, no_prompt=args.no_prompt)
    try:
        asyncio.run(watcher.start())
    except KeyboardInterrupt:
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
