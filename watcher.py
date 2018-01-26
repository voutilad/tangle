"""
File watcher for BSD-style systems using kqueue(2)
"""
import os
from threading import Thread
from select import (
    kqueue, kevent, KQ_FILTER_VNODE, KQ_EV_ADD, KQ_EV_ENABLE, KQ_EV_CLEAR,
    KQ_EV_DELETE, KQ_NOTE_RENAME, KQ_NOTE_WRITE, KQ_NOTE_DELETE, KQ_NOTE_ATTRIB
)

IGNORE_DIRS = {".git", "CVS", ".svn", ".hg"}
IGNORE_PATTERNS = {".#"}


class Watcher(Thread):
    """
    A kqueue specific directory and file watcher, built for BSD-like systems
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.root_fd = -1
        self.fd_map = {}        # fd -> name
        self.dir_fd_map = {}    # fd -> (name, [files], [dirs])
        self.changelist = []
        self.die = False
        self.kq = kqueue()

    @staticmethod
    def new_event(fd):
        """
        Build new kevent preconfigured for registering the given file
        descriptor, `fd`, for `select.KQ_FILTER_VNODE` type events.

        :param fd: open file descriptor to watch using the event
        :returns: new `select.kevent` instance"""
        return kevent(fd, filter=KQ_FILTER_VNODE,
                      flags=KQ_EV_ADD | KQ_EV_ENABLE | KQ_EV_CLEAR,
                      fflags=KQ_NOTE_RENAME | KQ_NOTE_WRITE |
                      KQ_NOTE_DELETE | KQ_NOTE_ATTRIB)

    def register_dir(self, dir_fd, dir_name, files=None, dirs=None):
        """
        Configure the given directory for event listening and update its state
        in the `self.dir_fd_map` map of known directories and their contents.

        Assumes the file descriptor for the directory in quesiton is already
        opened (and passed as `dir_fd`).

        :param dir_fd: file descriptor for the directory to register
        :param dir_name: `str` name of the directory
        :param files: list of filenames known in the directory, default: None
        :param dirs: list of directories known in the given directory,
                     default: None
        :returns: None
        """
        if files is None:
            files = set()
        if dirs is None:
            dirs = set()

        self.dir_fd_map[dir_fd] = (dir_name, set(files), set(dirs))
        event = self.new_event(dir_fd)
        self.changelist.append(event)
        print("[registered dir %s -> %s (%d files, %d dirs)]"
              % (dir_name, dir_fd, len(files), len(dirs)))

    def register_file(self, dir_fd, filename):
        """
        Open a file descriptor and prepare to construct a new `kevent` to add
        to `self.changelist` so they get registered during the next interaction
        with `kqueue()`. Also add it to the internal `Watcher` state in the
        `self.fd_map` map of files we're watching.

        :param dir_fd: file descriptor of the directory containing the file
        :param filename: `str` of the filename
        :returns: None
        """
        fd = os.open(filename, os.O_RDONLY, dir_fd=dir_fd)
        self.fd_map[fd] = filename
        event = self.new_event(fd)
        self.changelist.append(event)
        print("[registered %s -> %s]" % (dir_fd, filename))

    def unregister_file(self, fd):
        """
        Queues up a de-registration for events on the given file descriptor as
        well as tries to close it and clean up internal state.

        :param fd: file descriptor to unregister
        :returns: None
        """
        if fd in self.fd_map:
            # self.changelist.append(kevent(fd, filter=KQ_FILTER_VNODE,
            #                              flags=KQ_EV_DELETE))
            os.close(fd)
            name = self.fd_map.pop(fd)
            print("[unregistered %s -> %s]" % (fd, name))

    def unregister_dir(self, dir_fd):
        """
        Queues up a de-registration for events on the given directory file
        descriptor. Also tries to close it and clean up state.

        Assumes other events fire for any dependent children such as contained
        files or subdirectories since chances are this directory described by
        `dir_fd` has been removed from the file system as well as its contents.

        :param dir_fd: file descriptor for the directory to unregister
        :returns: None
        """
        # XXX: possible race condition...should we check if the dir is cleaned
        #      up or assume it is by update_dir()?
        if dir_fd in self.dir_fd_map:
            # self.changelist.append(kevent(dir_fd, filter=KQ_FILTER_VNODE,
            #                              flags=KQ_EV_DELETE))
            os.close(dir_fd)
            (name, files, dirs) = self.dir_fd_map.pop(dir_fd)
            print("[unregistered dir %s -> %s]" % (dir_fd, name))

    def update_dir(self, dir_fd):
        """
        Handle state changes to directories, finding changes to subdirectories
        as well as any files.

        TODO: This is the meat of the event handling and a great candidate for
        a refactor.

        :param dir_fd: file descriptor (`int`) for the target directory
        :returns: dict containing a summary of adds and deletes, of the
        format: `{'add': (set(), set()), 'del': (set(), set())}` where each
        tuple is ordered like: `(<files>, <dirs>)`
        """
        (dirpath, dirnames, filenames, dirfd) = next(os.fwalk(dir_fd=dir_fd))
        filenames = set(filenames)
        dirnames = set(dirnames)

        # handle changes to subdirs
        new_dirs = dirnames.difference(self.dir_fd_map[dir_fd][2])\
                           .difference(IGNORE_DIRS)
        rm_dirs = self.dir_fd_map[dir_fd][2].difference(dirnames)

        for newdir in new_dirs:
            new_dir_fd = os.open(newdir, os.O_RDONLY | os.O_DIRECTORY,
                                 dir_fd=dir_fd)
            self.register_dir(new_dir_fd,
                              "%s/%s" % (self.dir_fd_map[dir_fd][0], newdir))
            self.update_dir(new_dir_fd)

        for rmdir in rm_dirs:
            # self.unregister_dir(rmdir)
            self.dir_fd_map[dir_fd][2].remove(rmdir)

        # handle changes in this dir's files
        new_files = filenames.difference(self.dir_fd_map[dir_fd][1])
        rm_files = self.dir_fd_map[dir_fd][1].difference(filenames)

        # we won't have events on new files yet
        for newfile in new_files:
            ignore = False
            for i in IGNORE_PATTERNS:
                if newfile.startswith(i):
                    new_files.remove(newfile)
                    ignore = True
                    break
            if not ignore:
                self.register_file(dir_fd, newfile)
                self.dir_fd_map[dir_fd][1].update({newfile})

        # file de-registration happens as a result of file events,
        # but we need to clean up our directory map
        for rmfile in rm_files:
            self.dir_fd_map[dir_fd][1].remove(rmfile)

        return {'add': (new_files, new_dirs), 'del': (rm_files, rm_dirs)}

    def run(self):
        """
        Main event loop for Watcher. Performs initial walk of target
        directory and registers events. Executes an event-loop to hande
        new events as they are returned by the kernel.
        """
        # bootstrap
        for root, dirs, files, rootfd in os.fwalk(self.path):
            for i in IGNORE_DIRS:
                if i in dirs:
                    dirs.remove(i)
                    print("[ignoring %s/%s/]" % (root, i))

            dir_fd = os.dup(rootfd)
            if self.root_fd < 0:
                self.root_fd = dir_fd
            self.register_dir(dir_fd, root, files, dirs)

            for f in files:
                ignore = False
                for i in IGNORE_PATTERNS:
                    if f.startswith(i):
                        ignore = True
                        break
                if not ignore:
                    self.register_file(dir_fd, f)
                else:
                    print("[ignoring %s/%s]" % (root, f))

        # main event loop
        while not self.die:
            # XXX: without a timeout, no clean way to break out!
            events = self.kq.control(self.changelist, 1, 1)
            self.changelist.clear()
            for event in events:
                print("[*] %s" % event)
                fd = event.ident
                if fd in self.dir_fd_map:
                    self.handle_dir_event(event)
                elif fd in self.fd_map:
                    self.handle_file_event(event)

    def handle_dir_event(self, event):
        """
        Process directory-specific kevents, specifically those for
        renames, deletes, attribute changes, and any write-inducing
        activities (which is almost everything it seems).

        :param event: `select.kevent` instance from `select.kqueue`
        :returns: None
        """
        dir_fd = event.ident
        flags = event.fflags
        dir_name = self.dir_fd_map[dir_fd]
        actions = []

        if flags & KQ_NOTE_RENAME:
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            self.unregister_dir(dir_fd)
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            if dir_fd in self.dir_fd_map:  # this happens if a delete occurs
                results = self.update_dir(dir_fd)
                actions.append("writes (%s)" % str(results))
            else:
                actions.append("writes ignored (%s)" % str(dir_name))
        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        print("[d!%d] (%s) %s - %s" % (dir_fd, hex(flags), dir_name, actions))

    def handle_file_event(self, event):
        """
        Process file kevents. In this case, we defer most complex operations
        to the directory kevent handler `self.handle_dir_event()`.

        :param event: `select.kevent` instance from `select.kqueue`
        :returns: None
        """
        fd = event.ident
        flags = event.fflags
        actions = []
        name = self.fd_map[fd]

        # XXX: At the moment, we waste the fd even though it's the same
        #      and we open a new one in the update_dir() routine calling
        #      register_file()
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
        print("[f!%d] (%s) %s - %s" % (fd, hex(flags), name, actions))

    def stop(self):
        """
        Gracefully stop the `Watcher` instance, trying to close any open
        file descriptors first.

        :returns: None
        """
        print("Stopping watcher...")
        for fd in self.fd_map:
            try:
                os.close(fd)
            except OSError:
                print("[e] couldn't close fd" % fd)

        self.die = True
