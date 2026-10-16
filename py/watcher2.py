import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class OnMyWatch:
    watchDirectory = "/give / the / address / of / directory"

    def __init__(self) -> None:
        self.observer = Observer()

    def run(self) -> None:
        event_handler = Handler()
        self.observer.schedule(
            event_handler,
            self.watchDirectory,
            recursive=True,
        )
        self.observer.start()
        try:
            while True:
                time.sleep(5)
        except:
            self.observer.stop()
            print("Observer Stopped")
        self.observer.join()


class Handler(FileSystemEventHandler):
    @staticmethod
    def on_any_event(event) -> None:
        if event.is_directory:
            return
        elif event.event_type == "created":
            print(f"Watchdog received created event - {event.src_path: }.")
        elif event.event_type == "modified":
            print(f"Watchdog received modified event - {event.src_path: }.")


if __name__ == "__main__":
    watch = OnMyWatch()
    watch.run()
