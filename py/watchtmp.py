import shutil
import time

import watchdog.events
import watchdog.observers

TARGET = "/sdcard/whl"


class Handler(watchdog.events.PatternMatchingEventHandler):
    def __init__(self) -> None:
        watchdog.events.PatternMatchingEventHandler.__init__(
            self,
            patterns=["*.whl", "*.tar.gz"],
            ignore_directories=True,
            case_sensitive=False,
        )

    def on_created(self, event) -> None:
        shutil.copy2(event.srcpath, TARGET)
        print(f"Watchdog received created event - {event.src_path: }.")

    def on_modified(self, event) -> None:
        print(f"Watchdog received modified event - {event.src_path: }.")


if __name__ == "__main__":
    src_path = r"/data/data/com.termux/files/usr/tmp"
    event_handler = Handler()
    observer = watchdog.observers.Observer()
    observer.schedule(
        event_handler,
        path=src_path,
        recursive=True,
    )
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
