#!/usr/bin/env python3
import os
import sys
import logging
from multiprocessing import Queue

from tangle.watcher import Watcher
from tangle.processor import Processor
from tangle.events import SHUTDOWN

SOCKNAME = '.sock'

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
    log = logging.getLogger("tangle-client")

    wq = Queue()
    pq = Queue()

    watcher = Watcher(path, wq, sockname=SOCKNAME)
    processor = Processor(pq, sockname=SOCKNAME, daemon=False)

    processor.start()
    log.info(">>> processor started with pid %s" % processor.pid)

    watcher.start()
    log.info(">>> watcher started with pid %s" % watcher.pid)

    try:
        input()
    except KeyboardInterrupt:
        pass
    log.info(">>> Stopping child processes")

    wq.put(SHUTDOWN)
    pq.put(SHUTDOWN)
    watcher.join()
    processor.join()

    try:
        os.remove(SOCKNAME)
    except:
        log.info('>>> Failed to remove socket %s!' % SOCKNAME)
