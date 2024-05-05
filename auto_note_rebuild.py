import time
import argparse
import subprocess
import sys
from queue import Queue
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from threading import Lock, Thread, Event
import os

g_shutdown = Event() 
g_changed_files = set()

class Watcher:
    DIRECTORY_TO_WATCH = "C:\\Users\\Administrator\\Dropbox\\NOTES\\obsidian\\Coding"

    def __init__(self):
        self.observer = Observer()

    def run(self):
        event_handler = Handler()
        self.observer.schedule(event_handler, self.DIRECTORY_TO_WATCH, recursive=True)
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
    def on_any_event(event):
        if event.is_directory:
            return
        # print(f"Received FS event {event.event_type} - {event.src_path}.")
        if event.src_path.endswith("workspace.json"):
            return
        g_changed_files.add(event.src_path)

class UpdateThread(Thread):
    def __init__(self, interval):
        super().__init__()
        self.interval = interval

    def any_file_blocked(self):
        to_del = []
        for file_path in g_changed_files:
            if not os.path.isfile(file_path):
                to_del.append(file_path)
                continue
            try:
                with open(file_path, 'r+'):
                    pass  # Attempt to open the file
            except Exception as e:
                return True
        for file_path in to_del:
            g_changed_files.remove(file_path)
        return False
    
    def run(self) -> None:
        while not g_shutdown.is_set():
            if len(g_changed_files) > 0:
                print("changes detected, rebuilding website...")

                while(self.any_file_blocked()):
                    time.sleep(5)
                print(f"the following files have been changed:\n{g_changed_files}")

                p = subprocess.Popen(["powershell.exe", "C:\\Users\\Administrator\\Desktop\\servers\\deploy_notes.ps1"], 
                                     stdin=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                p.stdin.write('\n')
                p.stdin.flush()
                p.stdin.close()
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