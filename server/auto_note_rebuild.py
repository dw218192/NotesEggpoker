import subprocess
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import (
    FileSystemEventHandler,
    FileSystemEvent,
    EVENT_TYPE_CREATED,
    EVENT_TYPE_MODIFIED,
    EVENT_TYPE_MOVED,
    EVENT_TYPE_CLOSED,
    EVENT_TYPE_CLOSED_NO_WRITE,
    EVENT_TYPE_DELETED,
    EVENT_TYPE_OPENED
)
from threading import Thread, Event
import os
import logging
import shutil
import pathlib
from typing import cast, Any
from dataclasses import dataclass

@dataclass
class FileChange:
    event_type: str
    src_path: pathlib.Path
    dst_path: pathlib.Path

class Handler(FileSystemEventHandler):
    def __init__(self, changed_files: Queue[FileChange], *args: Any, **kwds: Any):
        super().__init__(*args, **kwds)
        self.changed_files = changed_files

    def on_any_event(self, event : FileSystemEvent):
        if event.is_directory or event.src_path.endswith("workspace.json"): #type:ignore
            return
        event_type = event.event_type
        src_path = cast(str, event.src_path)
        dst_path = cast(str, event.dest_path)

        if event_type in (EVENT_TYPE_CREATED, EVENT_TYPE_DELETED, EVENT_TYPE_MODIFIED, EVENT_TYPE_MOVED):
            self.changed_files.put(FileChange(event_type, pathlib.Path(src_path), pathlib.Path(dst_path)))

class UpdateThread(Thread):
    def __init__(self, logger: logging.Logger, project_dir: str, dir_to_watch: str, dst_dir: str, interval: float, rebuild_on_start: bool=True):
        super().__init__()
        self.daemon = True
        self.logger = logger
        self.interval = interval
        self.project_dir = project_dir
        self.dst_dir = dst_dir
        self.dir_to_watch = dir_to_watch
        self.rebuild_on_start = rebuild_on_start
        self.wait_event = Event()
        self.shutdown_event = Event()
        self.changed_files: Queue[FileChange] = Queue()
        self.is_rebuilding = False
        self.valid = False

        if not os.path.exists(dir_to_watch):
            logger.error(f"{dir_to_watch} does not exist.")
            return
        
        if not os.path.exists(project_dir):
            logger.error(f"{project_dir} does not exist")
            return
        
        if not os.path.exists(dst_dir):
            logger.error(f"{dst_dir} does not exist")
            return
        
        self.logger.info(f"Watching {self.dir_to_watch} for changes.")
        
        self.dst_dir_path = pathlib.Path(self.dst_dir)
        self.dir_to_watch_path = pathlib.Path(dir_to_watch)
        event_handler = Handler(self.changed_files)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.dir_to_watch, recursive=True) #type:ignore
        self.observer.start()
        self.valid = True

    def shut_down(self):
        self.shutdown_event.set()

    def _rebuild(self) -> tuple[int, str]:
        self.is_rebuilding = True
        p = subprocess.run(["npx", "quartz", "build"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, shell=True, cwd=self.project_dir)
        self.is_rebuilding = False

        return p.returncode, p.stderr
    
    def _copy_content(self, file_changes: list[FileChange]):
        if len(file_changes) == 0:
            shutil.rmtree(self.dst_dir)

            def copy_f(src: str, dst: str, *args: Any, **kwds: Any):
                if ".obsidian" in pathlib.Path(src).parts:
                    return
                self.logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst, *args, **kwds)
            shutil.copytree(self.dir_to_watch, self.dst_dir, copy_function=copy_f)
        else:
            for file_change in file_changes:
                def copy_file(file: pathlib.Path):
                    if file.exists():
                        relative_path = file.relative_to(self.dir_to_watch_path)
                        target_path = self.dst_dir_path / relative_path
                        target_path.parent.mkdir(parents=True, exist_ok=True)
                        self.logger.debug(f"Copying {str(file)} to {str(target_path)}")
                        shutil.copy2(file, target_path)

                def delete_file(file: pathlib.Path):
                    relative_path = file.relative_to(self.dir_to_watch_path)
                    target_path = self.dst_dir_path / relative_path
                    if target_path.exists():
                        self.logger.debug(f"Deleting {target_path}")
                        os.remove(str(target_path))

                if file_change.event_type in (EVENT_TYPE_CREATED, EVENT_TYPE_MODIFIED):
                    copy_file(file_change.src_path)
                elif file_change.event_type == EVENT_TYPE_DELETED:
                    delete_file(file_change.src_path)
                elif file_change.event_type == EVENT_TYPE_MOVED:
                    delete_file(file_change.src_path)
                    copy_file(file_change.dst_path)
                else:
                    self.logger.error(f"Unhandled file event type: {file_change.event_type}")

    def run(self) -> None:
        if not self.valid:
            logger.error("Initialization Failed, will not run")
            return
        
        # do a clean build
        if self.rebuild_on_start:
            self._copy_content([])
            while True:
                rc, err = self._rebuild()
                if rc != 0:
                    self.logger.warning(f"{err}")
                    self.logger.warning("failed to rebuild, will try again later...")
                    self.shutdown_event.wait(5)
                else:
                    break

        while not self.shutdown_event.is_set():
            file_changes: list[FileChange] = []
            while not self.changed_files.empty():
                file_changes.append(self.changed_files.get())

            if len(file_changes) == 0:
                continue
            self.logger.info(f"received {len(file_changes)} changed files")

            rc = 1
            while rc != 0:
                while True:
                    try:
                        self._copy_content(file_changes)
                        break
                    except Exception as e:
                        self.logger.warning(f"{e}")
                        self.logger.warning("failed to copy content, will try again later...")
                        self.shutdown_event.wait(5)

                rc, err = self._rebuild()
                if rc == 0:
                    self.logger.info("rebuild successful")
                else:
                    self.logger.warning(f"{err}")
                    self.logger.warning("failed to rebuild, will try again later...")

                # wait for 5 secs, exit if shutdown signal is received
                self.shutdown_event.wait(5)

if __name__ == '__main__':
    import unittest
    from unittest.mock import patch, MagicMock
    import time
    import logging
    import os
    import tempfile
    from pathlib import Path

    # Ensure logging is set up
    logging.basicConfig(level=logging.DEBUG)
    logger = logging.getLogger(__name__)

    def test_update_thread_basic():
        with patch('os.path.exists', return_value=True), \
            patch('os.path.realpath', return_value='mock_directory'), \
            patch.object(UpdateThread, '_copy_content', return_value=None), \
            patch.object(UpdateThread, '_rebuild', return_value=(0, "")) as mock_rebuild, \
            patch('watchdog.observers.Observer.schedule'), \
            patch('watchdog.observers.Observer.start'), \
            patch('watchdog.observers.Observer.stop'):

            update_thread = UpdateThread(logger, 'mock_directory', 'mock_directory', 'mock_directory', 1.0, False)

            update_thread.start()
            update_thread.changed_files.put(FileChange(EVENT_TYPE_CREATED, Path("mock_file.txt"), Path("mock_file.txt")))

            time.sleep(1)
            update_thread.shut_down()
            update_thread.join()

            mock_rebuild.assert_any_call()

    def test_copy_content():
        with tempfile.TemporaryDirectory() as tmp_src, \
            tempfile.TemporaryDirectory() as tmp_dst:

            src_path = Path(tmp_src)
            dst_path = Path(tmp_dst)
            update_thread = UpdateThread(logger, tmp_src, tmp_src, tmp_dst, 1.0, False)
            
            # Mock the logger to capture log outputs
            update_thread.logger = MagicMock()
            
            # Create a file in the source directory
            file_path = src_path / "test_file.txt"
            file_path.write_text("test content")

            # Test file creation event
            created_event = FileChange(EVENT_TYPE_CREATED, file_path, file_path)
            update_thread._copy_content([created_event]) #type: ignore
            assert (dst_path / "test_file.txt").exists()
            assert (dst_path / "test_file.txt").read_text() == "test content"

            # Test file modification event
            file_path.write_text("modified content")
            modified_event = FileChange(EVENT_TYPE_MODIFIED, file_path, file_path)
            update_thread._copy_content([modified_event]) #type: ignore
            assert (dst_path / "test_file.txt").read_text() == "modified content"

            # Test file deletion event
            deleted_event = FileChange(EVENT_TYPE_DELETED, file_path, file_path)
            update_thread._copy_content([deleted_event]) #type: ignore
            assert not (dst_path / "test_file.txt").exists()

            # Reset file for move event
            file_path.write_text("test content")

            # Test file move event
            new_file_path = src_path / "new_test_file.txt"
            new_file_path.write_text(file_path.read_text())
            moved_event = FileChange(EVENT_TYPE_MOVED, file_path, new_file_path)
            update_thread._copy_content([moved_event]) #type: ignore
            assert not (dst_path / "test_file.txt").exists()
            assert (dst_path / "new_test_file.txt").exists()
            assert (dst_path / "new_test_file.txt").read_text() == "test content"

            # Verify logger usage for each event
            update_thread.logger.error.assert_not_called()

    def test_real_file_changes_with_watchdog():
        with tempfile.TemporaryDirectory() as tmp_src, \
            tempfile.TemporaryDirectory() as tmp_dst, \
            patch.object(UpdateThread, '_rebuild', return_value=(0, "")) as mock_rebuild:
            
            update_thread = UpdateThread(logger, tmp_src, tmp_src, tmp_dst, 1.0)
            update_thread.logger = MagicMock()
            update_thread.start()

            time.sleep(5)
            mock_rebuild.assert_called_once()
            mock_rebuild.reset_mock()

            # file creation
            src_file = Path(tmp_src) / "test_file.txt"
            src_file.write_text("Initial content")
            time.sleep(5)

            target_file = Path(tmp_dst) / "test_file.txt"
            assert target_file.read_text() == "Initial content"
            mock_rebuild.assert_called_once()
            mock_rebuild.reset_mock()

            # file change
            src_file.write_text("New content")
            time.sleep(5)
            assert target_file.read_text() == "New content"
            mock_rebuild.assert_called_once()
            mock_rebuild.reset_mock()

            # file deletion
            os.remove(str(src_file))
            time.sleep(5)
            assert not target_file.exists()
            mock_rebuild.assert_called_once()
            mock_rebuild.reset_mock()

            update_thread.shut_down()
            update_thread.join()
            update_thread.logger.error.assert_not_called()

    # Test runner
    suite = unittest.TestSuite()
    suite.addTest(unittest.FunctionTestCase(test_update_thread_basic))
    suite.addTest(unittest.FunctionTestCase(test_copy_content))
    suite.addTest(unittest.FunctionTestCase(test_real_file_changes_with_watchdog))

    runner = unittest.TextTestRunner()
    runner.run(suite)
