import logging
import os
import pathlib
import shutil
import subprocess
from threading import Event, Lock, Thread
from typing import Any, Callable

from watchdog.events import (
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

MEANINGFUL_EVENTS = {
    EVENT_TYPE_CREATED,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
}

IGNORED_DIR_NAMES = {".obsidian"}
IGNORED_FILE_NAMES = {"workspace.json"}


class Handler(FileSystemEventHandler):
    """Watchdog handler that raises a flag when meaningful changes occur."""

    def __init__(
        self,
        on_change: Callable[[], None],
        ignore_predicate: Callable[[pathlib.Path], bool],
        *args: Any,
        **kwds: Any,
    ):
        super().__init__(*args, **kwds)
        self.on_change = on_change
        self.ignore_predicate = ignore_predicate

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory or event.event_type not in MEANINGFUL_EVENTS:
            return

        paths = [
            getattr(event, "src_path", None),
            getattr(event, "dest_path", None),
        ]

        for path_str in paths:
            if not path_str:
                continue
            candidate_path = pathlib.Path(path_str)
            if not self.ignore_predicate(candidate_path):
                self.on_change()
                break


class UpdateThread(Thread):
    def __init__(
        self,
        logger: logging.Logger,
        project_dir: str,
        dir_to_watch: str,
        dst_dir: str,
        interval: float,
        rebuild_on_start: bool = True,
    ):
        super().__init__()
        self.daemon = True
        self.logger = logger
        self.interval = interval
        self.project_dir = project_dir
        self.dst_dir = dst_dir
        self.dir_to_watch = dir_to_watch
        self.rebuild_on_start = rebuild_on_start
        self.shutdown_event = Event()
        self.is_rebuilding = False
        self.valid = False
        self._pending_changes = False
        self._pending_lock = Lock()

        if not os.path.exists(dir_to_watch):
            logger.error(f"{dir_to_watch} does not exist.")
            return

        if not os.path.exists(project_dir):
            logger.error(f"{project_dir} does not exist")
            return

        if not os.path.exists(dst_dir):
            logger.error(f"{dst_dir} does not exist")
            return

        self.logger.info(f"Watching {dir_to_watch} for changes.")
        self.dir_to_watch_path = pathlib.Path(dir_to_watch)
        self.dst_dir_path = pathlib.Path(dst_dir)

        event_handler = Handler(self._handle_meaningful_change, self._should_ignore)
        self.observer = Observer()
        self.observer.schedule(event_handler, dir_to_watch, recursive=True)
        self.observer.start()
        self.valid = True

    def shut_down(self) -> None:
        self.shutdown_event.set()
        if hasattr(self, "observer"):
            self.observer.stop()

    def _handle_meaningful_change(self) -> None:
        with self._pending_lock:
            self._pending_changes = True

    def _consume_pending_changes(self) -> bool:
        with self._pending_lock:
            if not self._pending_changes:
                return False
            self._pending_changes = False
            return True

    def _should_ignore(self, path: pathlib.Path) -> bool:
        if any(part in IGNORED_DIR_NAMES for part in path.parts):
            return True
        return path.name in IGNORED_FILE_NAMES

    def _copytree_ignore(self, current_dir: str, names: list[str]) -> list[str]:
        ignored: list[str] = []
        base_path = pathlib.Path(current_dir)
        for name in names:
            candidate = base_path / name
            if self._should_ignore(candidate):
                ignored.append(name)
        return ignored

    def _sync_directories(self) -> None:
        self.logger.info(
            f"Synchronizing directories by replacing {self.dst_dir} "
            f"with {self.dir_to_watch}"
        )

        if self.dst_dir_path.exists():
            shutil.rmtree(self.dst_dir_path)

        self.dst_dir_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            self.dir_to_watch_path,
            self.dst_dir_path,
            copy_function=shutil.copy2,
            ignore=self._copytree_ignore,
        )

    def _rebuild(self) -> tuple[int, str]:
        self.is_rebuilding = True
        try:
            process = subprocess.run(
                ["npx", "quartz", "build"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                shell=True,
                cwd=self.project_dir,
            )
            return process.returncode, process.stderr
        finally:
            self.is_rebuilding = False

    def _perform_sync_cycle(self) -> None:
        while not self.shutdown_event.is_set():
            try:
                self._sync_directories()
                break
            except Exception as exc:  # pragma: no cover - log and retry
                self.logger.warning("%s", exc)
                self.logger.warning(
                    "Failed to synchronize directories, will retry shortly..."
                )
                if self.shutdown_event.wait(5):
                    return

        if self.shutdown_event.is_set():
            return

        while not self.shutdown_event.is_set():
            rc, err = self._rebuild()
            if rc == 0:
                self.logger.info("Rebuild successful")
                return
            self.logger.warning("%s", err)
            self.logger.warning("Failed to rebuild, will retry shortly...")
            if self.shutdown_event.wait(5):
                return

    def run(self) -> None:
        if not self.valid:
            self.logger.error("Initialization failed, will not run")
            return

        try:
            if self.rebuild_on_start:
                self.logger.info("Running initial synchronization and rebuild")
                self._perform_sync_cycle()

            while not self.shutdown_event.is_set():
                if self.shutdown_event.wait(self.interval):
                    break
                if not self._consume_pending_changes():
                    continue
                self.logger.info("Detected changes, performing full sync")
                self._perform_sync_cycle()
        finally:
            if hasattr(self, "observer"):
                self.observer.stop()
                self.observer.join()


if __name__ == "__main__":
    import logging
    import os
    import tempfile
    import time
    import unittest
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    logging.basicConfig(level=logging.DEBUG)
    test_logger = logging.getLogger(__name__)

    def test_update_thread_basic():
        with patch("os.path.exists", return_value=True), patch(
            "watchdog.observers.Observer.schedule"
        ), patch("watchdog.observers.Observer.start"), patch(
            "watchdog.observers.Observer.stop"
        ), patch(
            "watchdog.observers.Observer.join"
        ), patch.object(
            UpdateThread, "_sync_directories"
        ) as mock_sync, patch.object(
            UpdateThread, "_rebuild", return_value=(0, "")
        ) as mock_rebuild:
            update_thread = UpdateThread(
                test_logger,
                "mock_project",
                "mock_src",
                "mock_dst",
                interval=0.1,
                rebuild_on_start=False,
            )

            update_thread.start()
            update_thread._handle_meaningful_change()
            time.sleep(0.3)
            update_thread.shut_down()
            update_thread.join()

            assert mock_sync.called
            assert mock_rebuild.called

    def test_sync_directories():
        with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst, patch(
            "watchdog.observers.Observer.schedule"
        ), patch(
            "watchdog.observers.Observer.start"
        ), patch(
            "watchdog.observers.Observer.stop"
        ), patch(
            "watchdog.observers.Observer.join"
        ):
            src_path = Path(tmp_src)
            dst_path = Path(tmp_dst)

            (src_path / "note.md").write_text("hello world")
            obsidian_dir = src_path / ".obsidian"
            obsidian_dir.mkdir()
            (obsidian_dir / "workspace.json").write_text("{}")

            update_thread = UpdateThread(
                test_logger,
                tmp_src,
                tmp_src,
                tmp_dst,
                interval=1.0,
                rebuild_on_start=False,
            )

            update_thread._sync_directories()

            assert (dst_path / "note.md").read_text() == "hello world"
            assert not (dst_path / ".obsidian").exists()

    def test_handler_ignores_paths():
        triggered: list[bool] = []
        handler = Handler(
            lambda: triggered.append(True),
            lambda path: ".obsidian" in path.parts,
        )

        ignored_event = MagicMock()
        ignored_event.is_directory = False
        ignored_event.event_type = EVENT_TYPE_MODIFIED
        ignored_event.src_path = os.path.join("notes", ".obsidian", "workspace.json")
        ignored_event.dest_path = None
        handler.on_any_event(ignored_event)
        assert not triggered

        valid_event = MagicMock()
        valid_event.is_directory = False
        valid_event.event_type = EVENT_TYPE_CREATED
        valid_event.src_path = os.path.join("notes", "note.md")
        valid_event.dest_path = None
        handler.on_any_event(valid_event)
        assert triggered

    suite = unittest.TestSuite()
    suite.addTest(unittest.FunctionTestCase(test_update_thread_basic))
    suite.addTest(unittest.FunctionTestCase(test_sync_directories))
    suite.addTest(unittest.FunctionTestCase(test_handler_ignores_paths))

    runner = unittest.TextTestRunner()
    runner.run(suite)
