#!/usr/bin/env python
import os
import sys

from signal import SIGINT, SIGINFO, signal
from select import *
from time import sleep
from threading import Thread

IGNORES = [".git", "CVS", ".svn", ".hg"]

watcher = None

class Watcher(Thread):

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.fd_map = {}
        self.events = []
        self.die = False
        self.kq = kqueue()

    def register_file(self, dir_fd, filename):
        fd = os.open(filename, os.O_RDONLY, dir_fd=dir_fd)
        self.fd_map[fd] = filename
        event = kevent(fd, filter=KQ_FILTER_VNODE,
                       flags=KQ_EV_ADD | KQ_EV_ENABLE | KQ_EV_CLEAR,
                       fflags=KQ_NOTE_RENAME | KQ_NOTE_WRITE | KQ_NOTE_DELETE | KQ_NOTE_ATTRIB)
        self.events.append(event)

        print("[registered %s -> %s]" % (dir_fd, filename))

    def run(self):
        for root, dirs, files, rootfd in os.fwalk(self.path):
            for i in IGNORES:
                if i in dirs: dirs.remove(i)
            for f in files:
                self.register_file(os.dup(rootfd), f)
                

        while not self.die:
            events = self.kq.control(self.events, len(self.events), 5)
            if len(events) == 0:
                print("...nothing yet...")
            else:
                for event in events:
                    print("[!] %s" % self.fd_map.get(event.ident, "???"))


    def stop(self):
        print("Stopping watcher...")
        for fd in self.fd_map:
            try:
                os.close(fd)
            except OSError:
                print("[e] couldn't close fd" % fd)

        self.die = True


def handle_signals(signal_num, stack_frame):
    if signal_num == SIGINT:
        sys.stdout.write("\010\010\010")
        print("CTRL-C detected.")
        watcher.stop()
    elif signal_num == SIGINFO:
        sys.stdout.write("\010\010\010")
        print("Watcher is watching %s files." % len(watcher.events))


if __name__ == "__main__":
    signal(SIGINT, handle_signals)
    signal(SIGINFO, handle_signals)

    path = "."
    if len(sys.argv) > 1:
        path = sys.argv[1]

    watcher = Watcher(path)
    watcher.start()
    watcher.join()
    print("bye!")
