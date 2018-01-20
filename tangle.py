#!/usr/bin/env python
import os
import sys

from signal import SIGINT, SIGINFO, signal
from select import *
from time import sleep
from threading import Thread

watcher = None

class Watcher(Thread):
    def __init__(self, path):
        super().__init__()
        self.path = path
        self.file_map = {}
        self.die = False

    def run(self):
        for item in os.listdir(self.path):
            print("Watching item: %s" % item)
        while not self.die:
            sleep(1)


    def stop(self):
        print("Stopping watcher...")
        self.die = True


def handle_signals(signal_num, stack_frame):
    if signal_num == SIGINT:
        sys.stdout.write("\010\010\010")
        print("CTRL-C detected.")
        watcher.stop()
    elif signal_num == SIGINFO:
        sys.stdout.write("\010\010\010")
        print("SIGINFO TBD...")


if __name__ == "__main__":
    signal(SIGINT, handle_signals)
    signal(SIGINFO, handle_signals)

    watcher = Watcher("..")
    watcher.start()
    watcher.join()
