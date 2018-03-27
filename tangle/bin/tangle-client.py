#!/usr/bin/env python3
import sys
import logging
import queue
from tangle.watcher import Watcher


if __name__ == "__main__":
    path = "."
    if len(sys.argv) > 1:
        path = sys.argv[1]

    print("Starting watcher on %s\nHit ENTER to stop." % path)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    ch.setFormatter(formatter)
    root.addHandler(ch)

    watcher = Watcher(path, queue.Queue())
    watcher.start()

    try:
        input()
    except KeyboardInterrupt:
        pass
    watcher.stop()
    watcher.join()

    print("Final watcher status:")
    from pprint import pprint
    print("inode_map:")
    pprint(watcher.inode_map)
