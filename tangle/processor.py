#!/usr/bin/env python3
"""
Tangle Event Processor
"""
import logging
from queue import Empty
from multiprocessing import Process, Queue

DEFAULT_TIMEOUT = 5

LOG = logging.getLogger(__name__)


class Processor(Process):
    """
    Listens for events published by a Watcher thread.
    """

    def __init__(self, queue, parent_queue, daemon=True):
        super().__init__(daemon=daemon)
        self.queue = queue
        self.parent_queue = parent_queue
        self.die = False

    def stop(self):
        """
        Gracefully stop the Processer instance.
        """
        LOG.info("Stopping processor...")
        self.die = True

    def should_stop(self):
        try:
            self.parent_queue.get_nowait()
            return True
        except Empty:
            return False

    def run(self):
        """
        Main event loop
        """
        LOG.info("Starting processor...")
        while not self.should_stop():
            try:
                event = self.queue.get(timeout=DEFAULT_TIMEOUT)
                LOG.info("Processing event: %s" % str(event))
            except Empty:
                LOG.info("No events in timeout (%ss)" % DEFAULT_TIMEOUT)
        self.stop()
