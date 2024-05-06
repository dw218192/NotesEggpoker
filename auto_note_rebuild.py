import time
import argparse
import subprocess
import sys
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
from threading import Lock, Thread, Event
import os

if __name__ == '__main__':
    g_shutdown = Event() 
    g_changed_files = set()

    SYM_LINK = ".\\content"
    if not os.path.exists(SYM_LINK):
        print(f"Error: symlink {SYM_LINK} does not exist.")
        sys.exit(1)

    if os.path.islink(SYM_LINK):
        DIRECTORY_TO_WATCH = os.path.realpath(SYM_LINK)
    else:
        DIRECTORY_TO_WATCH = SYM_LINK

    print(f"Watching {DIRECTORY_TO_WATCH} for changes.")

class Watcher:
    def __init__(self):
        self.observer = Observer()

    def run(self):
        event_handler = Handler()
        self.observer.schedule(event_handler, DIRECTORY_TO_WATCH, recursive=True)
        self.observer.start()

        try:
            while True:
                pass
        except:
            g_shutdown.set()
            self.observer.stop()
        self.observer.join()

class Handler(FileSystemEventHandler):
    @staticmethod
    def on_any_event(event : FileSystemEvent):
        if event.is_directory or event.src_path.endswith("workspace.json"):
            return
        g_changed_files.add(event.src_path)

class UpdateThread(Thread):
    def __init__(self, interval):
        super().__init__()
        self.interval = interval
        self.wait_event = Event()

    def wait_for_files(self):
        to_del = []
        for file_path in g_changed_files:
            while os.path.isfile(file_path):
                try:
                    with open(file_path, 'r'):
                        break # file is readable, continue
                except:
                    self.wait_event.wait(2)
            if not os.path.isfile(file_path):
                to_del.append(file_path)

        for file_path in to_del:
            try:
                g_changed_files.remove(file_path)
            except:
                pass
    
    def run(self) -> None:
        while not g_shutdown.is_set():
            if len(g_changed_files) > 0:
                print("changes detected, rebuilding website...")

                self.wait_for_files()
                print(f"the following files have been changed:\n{g_changed_files}")

                p = subprocess.Popen(["npx", "quartz", "build"], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, shell=True)
                p.communicate()
                rc = p.returncode
                if rc == 0:
                    print("rebuild successful")
                    g_changed_files.clear()
                else:
                    print("failed to rebuild, will try again later...")
            g_shutdown.wait(self.interval)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-t', '--interval', type=float, required=True)
    args = parser.parse_args()
    t = UpdateThread(args.interval)
    t.start()
    w = Watcher()
    w.run()
    t.join()