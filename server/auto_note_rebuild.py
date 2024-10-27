import subprocess
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from threading import Thread, Event
import os
import logging
import shutil
import pathlib
from typing import cast, Any

class Handler(FileSystemEventHandler):
    def __init__(self, changed_files: Queue[str], *args: Any, **kwds: Any):
        super().__init__(*args, **kwds)
        self.changed_files = changed_files

    def on_any_event(self, event : FileSystemEvent):
        if event.is_directory or event.src_path.endswith("workspace.json"): #type:ignore
            return
        path = cast(str, event.src_path)
        self.changed_files.put(path, )

class UpdateThread(Thread):
    def __init__(self, logger: logging.Logger, project_dir: str, dir_to_watch: str, dst_dir: str, interval: float):
        super().__init__()
        self.daemon = True
        self.logger = logger
        self.interval = interval
        self.project_dir = project_dir
        self.dst_dir = dst_dir
        self.dir_to_watch = dir_to_watch
        self.wait_event = Event()
        self.shutdown_event = Event()
        self.changed_files: Queue[str] = Queue()
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
    
    def _copy_content(self, files: list[pathlib.Path]):
        if len(files) == 0:
            shutil.rmtree(self.dst_dir)

            def copy_f(src: str, dst: str, *args: Any, **kwds: Any):
                if ".obsidian" in pathlib.Path(src).parts:
                    return
                self.logger.debug(f"Copying {src} to {dst}")
                shutil.copy2(src, dst, *args, **kwds)
            shutil.copytree(self.dir_to_watch, self.dst_dir, copy_function=copy_f)
        else:
            for file in files:
                relative_path = file.relative_to(self.dir_to_watch_path)
                target_path = self.dst_dir_path / relative_path
                target_path.parent.mkdir(parents=True, exist_ok=True)
                self.logger.debug(f"Copying {str(file)} to {str(target_path)}")
                shutil.copy2(file, target_path)

    def run(self) -> None:
        if not self.valid:
            logger.error("Initialization Failed, will not run")
            return
        
        # do a clean build
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
            files: list[pathlib.Path] = []
            while not self.changed_files.empty():
                file = self.changed_files.get()
                files.append(pathlib.Path(file))

            if len(files) == 0:
                continue
            self.logger.info(f"received {len(files)} changed files")

            rc = 1
            while rc != 0:
                self._copy_content(files)
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
    from unittest.mock import patch, Mock
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

            update_thread = UpdateThread(logger, 'mock_directory', 'mock_directory', 'mock_directory', 1.0)

            update_thread.start()
            update_thread.changed_files.put("mock_file.txt")

            time.sleep(1)
            update_thread.shut_down()
            update_thread.join()

            mock_rebuild.assert_any_call()

    class TestUpdateThreadAdvanced(unittest.TestCase):
        def setUp(self):
            self.temp_dir = tempfile.TemporaryDirectory()
            self.temp_file_name = "mock_file.txt"
            self.temp_file_path = os.path.join(self.temp_dir.name, self.temp_file_name)
            self.temp_file_content = "Initial content"
            with open(self.temp_file_path, 'w') as f:
                f.write(self.temp_file_content)
            self.logger = logging.getLogger(__name__)

        def tearDown(self):
            self.temp_dir.cleanup()

        @patch.object(UpdateThread, '_rebuild', return_value=(0, ""))
        def test_real_file_changes_with_watchdog(self, mock_rebuild: Mock):
            with tempfile.TemporaryDirectory() as tmp_dst:
                update_thread = UpdateThread(self.logger, self.temp_dir.name, self.temp_dir.name, tmp_dst, 1.0)
                update_thread.start()
                target_file = Path(tmp_dst) / self.temp_file_name
                assert target_file.read_text() == self.temp_file_content

                with open(self.temp_file_path, 'a') as f:
                    f.write("\nMore content")

                time.sleep(1)
                update_thread.shut_down()
                update_thread.join()

                mock_rebuild.assert_called_once()
                
                assert target_file.read_text() == self.temp_file_content + "\nMore content"

    # Test runner
    suite = unittest.TestSuite()
    suite.addTest(unittest.FunctionTestCase(test_update_thread_basic))
    suite.addTest(TestUpdateThreadAdvanced('test_real_file_changes_with_watchdog'))

    runner = unittest.TextTestRunner()
    runner.run(suite)
