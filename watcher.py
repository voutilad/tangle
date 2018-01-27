"""
File watcher for BSD-style systems using kqueue(2)
"""
import os
from threading import Thread
from select import (
    kqueue, kevent, KQ_FILTER_VNODE, KQ_EV_ADD, KQ_EV_ENABLE, KQ_EV_CLEAR,
    KQ_NOTE_RENAME, KQ_NOTE_WRITE, KQ_NOTE_DELETE, KQ_NOTE_ATTRIB
)

IGNORE_DIRS = {".git", "CVS", ".svn", ".hg"}
IGNORE_PATTERNS = {".#"}


class Watcher(Thread):
    """
    A kqueue specific directory and file watcher, built for BSD-like systems.

    Assumptions:
      - We'll use inodes to track files/dirs through modifications
      - Inode generations aren't a thing on our file system for now
      - Closing a file descriptor will delete corresponding kevents
    """

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.root_fd = -1
        self.file_map = {}     # file inode -> (fd, name)
        # dir inode  -> (dir_fd, name, [file inodes], [dirs])
        self.dir_map = {}
        self.changelist = []
        self.die = False
        self.kq = kqueue()

    @staticmethod
    def new_event(fd, inode):
        """
        Build new kevent preconfigured for registering the given file
        descriptor, `fd`, for `select.KQ_FILTER_VNODE` type events.

        Sets the given inode integer to the `udata` parameter on the kevent.

        :param fd: open file descriptor to watch using the event
        :param inode: inode number of the file pointed to by fd
        :returns: new `select.kevent` instance"""
        return kevent(fd,
                      filter=KQ_FILTER_VNODE,
                      flags=KQ_EV_ADD | KQ_EV_ENABLE | KQ_EV_CLEAR,
                      fflags=KQ_NOTE_RENAME | KQ_NOTE_WRITE | KQ_NOTE_DELETE
                      | KQ_NOTE_ATTRIB,
                      udata=inode)

    def register_dir(self, fd, dirname, inode, files=None, dirs=None):
        """
        Configure the given directory for event listening and update its state
        in the `self.dir_fd_map` map of known directories and their contents.

        Assumes the file descriptor for the directory in question is already
        opened (and passed as `dir_fd`).

        :param fd: file descriptor for the directory to register
        :param dirname: `str` name of the directory
        :param inode: inode number for the directory
        :param files: list of filenames known in the directory, default: None
        :param dirs: list of directories known in the given directory,
                     default: None
        :returns: None
        TOOD: is files/dirs inodes or names???
        """
        if files is None:
            files = set()
        if dirs is None:
            dirs = set()

        self.dir_map[inode] = (fd, dirname, files, dirs)
        event = self.new_event(fd, inode)
        self.changelist.append(event)
        print("[registered dir %s -> %s w/fd %s and (%d files, %d dirs)]"
              % (inode, dirname, fd, len(files), len(dirs)))

    def register_file(self, fd, filename, inode):
        """
        Open a file descriptor and prepare to construct a new `kevent` to add
        to `self.changelist` so they get registered during the next interaction
        with `kqueue()`. Also add it to the internal `Watcher` state in the
        `self.fd_map` map of files we're watching.

        :param fd: open file descriptor for the file
        :param filename: `str` of the filename
        :param inode: inode number for the file
        :returns: (inode number, file descriptor)
        """
        self.file_map[inode] = (fd, filename)
        event = self.new_event(fd, inode)
        self.changelist.append(event)
        print("[registered %s -> %s in w/fd %s]" % (inode, filename, fd))
        return (inode, fd)

    def unregister_file(self, inode):
        """
        Queues up a de-registration for events on the given file descriptor as
        well as tries to close it and clean up internal state.

        :param inode: inode of the file to unregister
        :returns: None
        """
        if inode in self.file_map:
            fd = self.file_map[inode][0]
            os.close(fd)
            name = self.file_map[inode][1]
            del self.file_map[inode]
            print("[unregistered file inode %d: (name: %s, fd: %d)]"
                  % (inode, name, fd))

    def unregister_dir(self, inode):
        """
        Queues up a de-registration for events on the given directory file
        descriptor. Also tries to close it and clean up state.

        Assumes other events fire for any dependent children such as contained
        files or subdirectories since chances are this directory described by
        `dir_fd` has been removed from the file system as well as its contents.

        :param dir_fd: file descriptor for the directory to unregister
        :returns: None
        """
        if inode in self.dir_map:
            dir_fd = self.dir_map[inode][0]
            name = self.dir_map[inode][1]
            os.close(dir_fd)
            del self.dir_map[inode]
            print("[unregistered dir inode %d: (name: %s, fd: %d)]"
                  % (inode, name, dir_fd))

    @staticmethod
    def fstat_by_name(filename, is_dir=False, dir_fd=None):
        opts = os.O_RDONLY
        if is_dir:
            opts = os.O_RDONLY | os.O_DIRECTORY
        fd = os.open(filename, opts, dir_fd=dir_fd)
        inode = os.fstat(fd).st_ino
        return (filename, fd, inode)

    def ignore_file(self, filename):
        for pattern in IGNORE_PATTERNS:
            if filename.startswith(pattern):
                return True
        return False

    def update_dir(self, dir_inode):
        """
        Handle state changes to directories, finding changes to subdirectories
        as well as any files.

        TODO: This is the meat of the event handling and a great candidate for
        a refactor.

        :param inode: inode number for the target directory
        :returns: dict containing a summary of adds and deletes, of the
        format: `{'add': (set(), set()), 'del': (set(), set())}` where each
        tuple is ordered like: `(<files>, <dirs>)`
        """
        dir_fd = self.dir_map[dir_inode][0]
        (dirpath, dirnames, filenames, dirfd) = next(os.fwalk(dir_fd=dir_fd))

        filenames = set(f for f in filenames if not self.ignore_file(f))
        dirnames = set(dirnames).difference(IGNORE_DIRS)

        file_stats = [self.fstat_by_name(f, dir_fd=dir_fd)
                      for f in filenames]
        dir_stats = [self.fstat_by_name(d, is_dir=True, dir_fd=dir_fd)
                     for d in dirnames]

        removed_files = self.dir_map[dir_inode][2].difference(filenames)
        removed_dirs = self.dir_map[dir_inode][3].difference(dirnames)

        for name in removed_files:
            self.dir_map[dir_inode][2].remove(name)
        for name in removed_dirs:
            self.dir_map[dir_inode][3].remove(name)

        for name, fd, inode in dir_stats:
            if inode not in self.dir_map:
                # net new inode for a dir!
                self.dir_map[dir_inode][3].add(name)
                self.register_dir(fd, name, inode)
                # print("[debug] new dir %s w/ inode %d" % (name, inode))

        for name, fd, inode in file_stats:
            if inode not in self.file_map:
                # net new inode for a file!
                # print("[debug] new file %s w/ inode %d" % (name, inode))
                self.register_file(fd, name, inode)
                self.dir_map[dir_inode][2].add(name)
            else:
                # just update if needed
                self.file_map[inode] = (fd, name)

        # we won't have events on new files yet
        # for newfile in new_files:
        #     ignore = False
        #     for i in IGNORE_PATTERNS:
        #         if newfile.startswith(i):
        #             new_files.remove(newfile)
        #             ignore = True
        #             break
        #     if not ignore:
        #         self.register_file(dir_fd, newfile)
        #         self.dir_fd_map[dir_fd][1].update({newfile})

        # file de-registration happens as a result of file events,
        # but we need to clean up our directory map
        #for rmfile in rm_files:
        #    self.dir_fd_map[dir_fd][1].remove(rmfile)

        return (file_stats, dir_stats)

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
            inode = os.fstat(dir_fd).st_ino
            self.register_dir(dir_fd, root, inode, set(files), set(dirs))

            for f in files:
                ignore = False
                for i in IGNORE_PATTERNS:
                    if f.startswith(i):
                        ignore = True
                        break
                if not ignore:
                    name, fd, inode = self.fstat_by_name(f, dir_fd=dir_fd)
                    self.register_file(fd, f, inode)
                else:
                    print("[ignoring %s/%s]" % (root, f))

        # main event loop
        while not self.die:
            # ???: without a timeout, no clean way to break out!
            events = self.kq.control(self.changelist, 1, 1)
            self.changelist.clear()
            for event in events:
                inode = event.udata

                # XXX: future idea is to add a bit to the udata to
                #      store not just inode, but dir/file type
                if inode in self.dir_map:
                    self.handle_dir_event(event)
                elif inode in self.file_map:
                    self.handle_file_event(event)

    def handle_dir_event(self, event):
        """
        Process directory-specific kevents, specifically those for
        renames, deletes, attribute changes, and any write-inducing
        activities (which is almost everything it seems).

        :param event: `select.kevent` instance from `select.kqueue`
        :returns: None
        """
        inode = event.udata
        flags = event.fflags
        dir_name = self.dir_map[inode]
        actions = []

        if flags & KQ_NOTE_RENAME:
            self.update_dir(inode)
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            self.unregister_dir(inode)
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            if inode in self.dir_map:  # this happens if a delete occurs
                results = self.update_dir(inode)
                actions.append("writes (%s)" % str(results))
            else:  # ???: is this conditional still valid?
                actions.append("writes ignored (%s)" % str(dir_name))
        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        print("[d!%d] (%s) %s - %s" % (inode, hex(flags), dir_name, actions))

    def handle_file_event(self, event):
        """
        Process file kevents. In this case, we defer most complex operations
        to the directory kevent handler `self.handle_dir_event()`.

        :param event: `select.kevent` instance from `select.kqueue`
        :returns: None
        """
        inode = event.udata
        flags = event.fflags
        actions = []
        name = self.file_map[inode][1]

        # XXX: At the moment, we waste the fd even though it's the same
        #      and we open a new one in the update_dir() routine calling
        #      register_file()
        if flags & KQ_NOTE_RENAME:
            # self.unregister_file(inode)
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            self.unregister_file(inode)
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            actions.append("write")

        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        print("[f!%d] (%s) %s - %s" % (inode, hex(flags), name, actions))

    def stop(self):
        """
        Gracefully stop the `Watcher` instance, trying to close any open
        file descriptors first.

        :returns: None
        """
        print("Stopping watcher...")
        for inode in self.file_map:
            try:
                fd = self.file_map[inode][0]
                os.close(fd)
            except OSError:
                print("[e] couldn't close file fd %s" % fd)

        for inode in self.dir_map:
            try:
                fd = self.dir_map[inode][0]
                os.close(fd)
            except OSError:
                print("[e] couldn't close dir fd %s" % fd)

        self.die = True
