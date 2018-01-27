#!/usr/bin/env python3
import sys

from watcher import Watcher


if __name__ == "__main__":
    path = "."
    if len(sys.argv) > 1:
        path = sys.argv[1]

    print("Starting watcher on %s\nHit ENTER to stop." % path)
    watcher = Watcher(path)
    watcher.start()

    try:
        input()
    except KeyboardInterrupt:
        pass
    watcher.stop()
    watcher.join()

    print("Final watcher status:")
    from pprint import pprint
    print("file_map:")
    pprint(watcher.file_map)
    print("dir_map:")
    pprint(watcher.dir_map)
