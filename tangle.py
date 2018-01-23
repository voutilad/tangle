#!/usr/bin/env python3
import os
import sys

from select import (
    kqueue, kevent, KQ_FILTER_VNODE, KQ_EV_ADD, KQ_EV_ENABLE, KQ_EV_CLEAR,
    KQ_EV_DELETE, KQ_NOTE_RENAME, KQ_NOTE_WRITE, KQ_NOTE_DELETE, KQ_NOTE_ATTRIB
)
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
    print("bye!")
