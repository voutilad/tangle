#!/usr/bin/env python3
import os
import sys

from signal import SIGINT, SIGINFO, signal
from select import *
from time import sleep
from threading import Thread

IGNORE_DIRS = [".git", "CVS", ".svn", ".hg"]
IGNORE_PATTERNS = [".#"]

watcher = None

class Watcher(Thread):
    """ kqueue specific directory and file watcher"""
    #XXX: currently doesn't UNregister events! Plus it
    #     might be constantly REregistering events

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.fd_map = {}
        self.dir_fd_map = {}
        self.changelist = []
        self.die = False
        self.kq = kqueue()

    @staticmethod
    def new_event(fd):
        return kevent(fd, filter=KQ_FILTER_VNODE,
                      flags=KQ_EV_ADD | KQ_EV_ENABLE | KQ_EV_CLEAR,
                      fflags=KQ_NOTE_RENAME | KQ_NOTE_WRITE |
                             KQ_NOTE_DELETE | KQ_NOTE_ATTRIB)

    def register_dir(self, dir_fd, dir_name, files):
        self.dir_fd_map[dir_fd] = (dir_name, files)
        event = self.new_event(dir_fd) 
        self.changelist.append(event)
        print("[registered dir %s -> %s]" % (dir_name, dir_fd))

    def register_file(self, dir_fd, filename):
        fd = os.open(filename, os.O_RDONLY, dir_fd=dir_fd)
        self.fd_map[fd] = filename
        event = self.new_event(fd)
        self.changelist.append(event)
        print("[registered %s -> %s]" % (dir_fd, filename))

    def unregister_file(self, fd):
        if fd in self.fd_map:
            self.changelist.append(kevent(fd, filter=KQ_FILTER_VNODE,
                                          flags=KQ_EV_DELETE))
            os.close(fd)
            name = self.fd_map.pop(fd)
            print("[unregistered %s -> %s]" % (fd, name))

    def update_dir(self, dir_fd):
        """Handle state changes to directories"""
        (dirpath, dirnames, filenames, dirfd) = next(os.fwalk(dir_fd=dir_fd))
        for seen in self.dir_fd_map[dir_fd][1]:
            if seen in filenames:
                filenames.remove(seen)

        for newfile in filenames:
            ignore = False
            for i in IGNORE_PATTERNS:
                if newfile.startswith(i):
                    filenames.remove(newfile)
                    ignore = True
                    break
            if not ignore:
                self.register_file(dir_fd, newfile)
                self.dir_fd_map[dir_fd][1].append(newfile)
        return filenames

    def run(self):
        """Main event loop for Watcher"""
        for root, dirs, files, rootfd in os.fwalk(self.path):
            for i in IGNORE_DIRS:
                if i in dirs:
                    dirs.remove(i)
                    print("[ignoring %s/%s/]" % (root, i))

            dir_fd = os.dup(rootfd)
            self.register_dir(dir_fd, root, files)

            for f in files:
                ignore = False
                for i in IGNORE_PATTERNS:
                    if f.startswith(i):
                        ignore = True
                        break
                if not ignore: self.register_file(dir_fd, f)
                else: print("[ignoring %s/%s]" % (root, f))
                
        while not self.die:
            #XXX: without a timeout, no clean way to break out!
            events = self.kq.control(self.changelist, 1, 1)
            self.changelist.clear()
            for event in events:
                fd = event.ident
                if fd in self.dir_fd_map:
                    self.handle_dir_event(fd, event)
                elif fd in self.fd_map:
                    self.handle_file_event(fd, event)

    def handle_dir_event(self, dir_fd, event):
        """Process directory-specific kevents"""
        flags = event.fflags
        actions = []
        if flags & KQ_NOTE_RENAME:
            
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            filenames = self.update_dir(dir_fd)
            if len(filenames) > 0:
                actions.append("write (%s)" % str(filenames))
            else:
                actions.append("writes ignored")

        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        print("[d!] %s - %s" % (self.dir_fd_map[dir_fd][0], actions))

    def handle_file_event(self, fd, event):
        """Process file kevents"""
        flags = event.fflags
        actions = []
        name = self.fd_map[fd]

        if flags & KQ_NOTE_RENAME:
            self.unregister_file(fd)
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            self.unregister_file(fd)
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            actions.append("write")

        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        print("[f!] %s - %s" % (name, actions))

    def stop(self):
        print("Stopping watcher...")
        for fd in self.fd_map:
            try:
                os.close(fd)
            except OSError:
                print("[e] couldn't close fd" % fd)

        self.die = True

# WTF this doesn't work reliable cross platform!!!
# def handle_signals(signal_num, stack_frame):
#     print("[debug] signal_num: %s, stack_frame: %s" % (signal_num, str(stack_frame)))
#     if signal_num == SIGINT:
#         sys.stdout.write("\010\010\010")
#         print("CTRL-C detected.")
#         watcher.stop()
#     elif signal_num == SIGINFO:
#         sys.stdout.write("\010\010\010")
#         print("Watcher is watching %s files." % len(watcher.events))


if __name__ == "__main__":
    path = "."
    if len(sys.argv) > 1:
        path = sys.argv[1]

    print("Starting watcher on %s\nHit ENTER to stop." % path)
    watcher = Watcher(path)
    watcher.start()

    #signal(SIGINT, handle_signals)
    #signal(SIGINFO, handle_signals)
    try:
        input()
    except KeyboardInterrupt:
        pass
    watcher.stop()
    watcher.join()
    print("bye!")
