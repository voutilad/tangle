#!/usr/bin/env python3
"""
Tangle Event Processor
"""
import array
import logging
import os
import selectors
import socket
from queue import Empty
from threading import Thread
from multiprocessing import Process, Queue
from tangle.comm import recv_event


DEFAULT_TIMEOUT = 5

LOG = logging.getLogger(__name__)


def count(name, f):
    LOG.info('Counter starting (name=%s, f=%s)' % (name, f))
    f.seek(0)
    cnt = len(f.read(4096))
    LOG.info('Counter[%s] reporting %s bytes for %s' % (os.getpid(), cnt, name))


class Counter(Thread):
    """ Counts bytes in file """

    def __init__(self, name, fd, daemon=True):
        super().__init__(daemon=daemon)
        self.name = name
        self.fd = fd

    def run(self):
        LOG.info('Counter starting (name=%s, fd=%s)' % (self.name, self.fd))
        with os.fdopen(self.fd, 'r') as f:
            f.seek(0)
            cnt = len(f.readall())
            LOG.info('Counter[%s] reporting %s bytes for %s' %
                     (os.getpid(), cnt, self.name))


class Processor(Process):
    """
    Listens for events published by a Watcher thread.
    """

    def __init__(self, parent_queue, sockname, daemon=True):
        super().__init__(daemon=daemon)
        self.sockname = sockname
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
        LOG.info('Starting processor...')

        LOG.info('Opening socket on %s...' % self.sockname)
        sock = socket.socket(family=socket.AF_UNIX)
        sock.bind(self.sockname)
        sock.listen(100)

        sel = selectors.DefaultSelector()
        sel.register(sock, selectors.EVENT_READ)

        conn = None
        for i in range(12):
            LOG.info('waiting 5s for watcher to connect....')
            events = sel.select(timeout=5)
            if len(events) > 0:
                # assume connection
                conn, _ = sock.accept()
                LOG.info('connected on socket %s' % self.sockname)
                break

        if not conn:
            LOG.info('no connection within timeout.')
            self.stop()
            return

        sel.unregister(sock)
        sel.register(conn, selectors.EVENT_READ)

        while not self.should_stop():
            try:
                sock_events = sel.select(timeout=DEFAULT_TIMEOUT)
                for sock_event in sock_events:
                    event, f = recv_event(conn)
                    if event is not None:
                        LOG.info("Processing event: %s" % str(event))

                        if f is not None:
                            child = Thread(target=count, args=(event.name, f))
                            child.start()
            except Empty:
                LOG.info("No socket events in timeout (%ss)" % DEFAULT_TIMEOUT)

        conn.close()
        sock.close()
        self.stop()
