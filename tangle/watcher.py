"""
File watcher for BSD-style systems using kqueue(2)
"""
import os
from threading import Thread
from select import (
    kqueue, kevent, KQ_FILTER_VNODE, KQ_EV_ADD, KQ_EV_ENABLE, KQ_EV_CLEAR,
    KQ_NOTE_RENAME, KQ_NOTE_WRITE, KQ_NOTE_DELETE, KQ_NOTE_ATTRIB
)

# TODO: move into Watcher class and make configurable
IGNORE_DIRS = {".git", "CVS", ".svn", ".hg"}
IGNORE_PATTERNS = {".#"}


class Watcher(Thread):
    """
    A kqueue specific directory and file watcher, built for BSD-like systems.

    Assumptions:
      - We'll use inodes to track files/dirs through modifications
      - Inode generations aren't a thing on our file system for now
      - Hard and Symbolic links won't be handled for now. Undefined behavior
        will result if trying to use them.
      - Closing a file descriptor will delete corresponding kevents

    Known issues:
      - broken symlinks might break initialization or updates
    """

    def __init__(self, path, daemon=True):
        super().__init__(daemon=daemon)
        self.path = path
        self.root_fd = None
        self.file_map = {}     # file inode -> (fd, name)
        self.dir_map = {}       # inode -> (fd, name, {files}, {dirs})
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
        :param files: list of file inodes known in the directory, default: None
        :param dirs: list of directory inodes known in the given directory,
                     default: None
        :returns: None
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
    def fstat_by_name(path, is_dir=False, dir_fd=None):
        """
        Get stats (via `fstat(2)`), specifically an inode number, for a given
        path to a file or directory.

        :param path: string path to file or directory
        :param is_dir: is the path a directory? (default: False)
        :param dir_fd: file descriptor to use as the basis for resolving path
                       (default: None)
        :returns: tuple of (path, fd, inode)

        TODO: refactor into just getting inode, autoclose fd immediately
              as this is leaking fd's most likely
        """
        opts = os.O_RDONLY
        if is_dir:
            opts = os.O_RDONLY | os.O_DIRECTORY
        fd = os.open(path, opts, dir_fd=dir_fd)
        inode = os.fstat(fd).st_ino
        return (path, fd, inode)

    def ignore_file(self, filename):
        """
        Check if a given filename should be ignored due to `IGNORE_PATTERNS`

        :param filename: name of file to test
        :returns: True if file should be ignored, otherwise False
        """
        for pattern in IGNORE_PATTERNS:
            if filename.startswith(pattern):
                return True
        return False

    def update_file(self, fd, name, inode):
        """
        Update our stateful view of a file, given an open file descriptor,
        its current name, and its inode number.

        :param fd: open file descriptor for file
        :param name: name of file in file system
        :param inode: inode number for the file
        :returns: None
        """
        if inode in self.file_map:
            old_fd, old_name = self.file_map[inode]
            if fd != old_fd:
                os.close(old_fd)
                self.changelist.append(self.new_event(fd, inode))
            if old_name != name:
                print("[debug] file rename detected %s -> %s"
                      % (old_name, name))
            self.file_map[inode] = (fd, name)

    def update_dir(self, fd, name, inode):
        """
        Update our statefule view of a directory given an open file descriptor,
        its current name, and its inode number.

        :param fd: open file descriptor to directory
        :param name: current name of directory in file system
        :param inode: inode number for directory
        :returns: None
        """
        if inode in self.dir_map:
            old_fd, old_name, files, dirs = self.dir_map[inode]
            if fd != old_fd:
                os.close(old_fd)
                self.changelist.append(self.new_event(fd, inode))
            if old_name != name:
                print("[debug] dir rename detected %s -> %s"
                      % (old_name, name))
            self.dir_map[inode] = (fd, name, files, dirs)

    def inode_for(self, path, is_dir=False, dir_fd=None):
        """
        Get an inode for a given file by its path on the file system, using its
        containing file directory (`dir_fd`) if known.

        :param path: path to the file of interest
        :param is_idr: boolean flag, True if the file in question is a
                       directory, default is False if it's a regular file.
        :param dir_fd: open file descriptor to a parent directory to use when
                       opening the file path
        :returns: inode number
        """
        opts = os.O_RDONLY
        if is_dir:
            opts = os.O_RDONLY | os.O_DIRECTORY
        fd = os.open(path, opts, dir_fd=dir_fd)
        inode = os.fstat(fd).st_ino
        os.close(fd)
        return inode

    def rename_dir(self, dir_inode):
        """
        Rename a given directory and its children.

        :param dir_inode: inode of directory to rename
        :returns: new name of directory
        """
        fd, name = self.dir_map[dir_inode][:2]
        parent = os.path.dirname(name)
        new_name = ''
        root, dirs, _, _ = next(os.fwalk(parent, dir_fd=self.root_fd))

        # find the new directory name
        for d in dirs:
            path = os.path.join(root, d)
            inode = self.inode_for(path, is_dir=True, dir_fd=self.root_fd)
            if dir_inode == inode:
                new_name = os.path.join(parent, d)

        # inline function for recursively renaming children
        def rename_children(parent_path, child_inode):
            fd, name, files, dirs = self.dir_map[child_inode]
            old_parent, dir_name = os.path.split(name)
            new_name = os.path.join(parent_path, dir_name)
            self.dir_map[child_inode] = (fd, new_name, files, dirs)
            for child in dirs:
                rename_children(new_name, child)

        # walk the children, renaming them as we go
        if new_name:
            for child in self.dir_map[dir_inode][3]:
                rename_children(new_name, child)

        return new_name

    def process_dir(self, dir_inode):
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
        dir_name = self.dir_map[dir_inode][1]

        (root, dirs, files, rootfd) = next(os.fwalk(dir_fd=dir_fd))
        for i in IGNORE_DIRS:
            if i in dirs:
                dirs.remove(i)

        file_stats = {}
        f_inodes = set()
        for f in files:
            if not self.ignore_file(f):
                name, fd, f_inode = self.fstat_by_name(f, dir_fd=dir_fd)
                if f_inode in self.file_map:
                    os.close(fd)
                    fd = self.file_map[f_inode][0]
                file_stats[f_inode] = (name, fd)
                f_inodes.add(f_inode)
                self.update_file(fd, name, f_inode)

        dir_stats = {}
        d_inodes = set()
        for d in dirs:
            name, fd, d_inode = self.fstat_by_name(d, is_dir=True, dir_fd=dir_fd)
            if d_inode in self.dir_map:
                os.close(fd)
                fd = self.dir_map[d_inode][0]
            dir_stats[d_inode] = (os.path.join(dir_name, name), fd)
            d_inodes.add(d_inode)
            self.update_dir(fd, os.path.join(dir_name, name), d_inode)

        removed_files = self.dir_map[dir_inode][2].difference(f_inodes)
        removed_dirs = self.dir_map[dir_inode][3].difference(d_inodes)
        # print("[debug] %s has removed files: %s, dirs: %s"
        # % (dir_name, removed_files, removed_dirs))

        # remove any moved files, de-reg is handled w/ KQ_NOTE_DELETE's
        for f_inode in removed_files:
            self.dir_map[dir_inode][2].remove(f_inode)
        for d_inode in removed_dirs:
            self.dir_map[dir_inode][3].remove(d_inode)

        new_files = f_inodes.difference(self.dir_map[dir_inode][2])
        new_dirs = d_inodes.difference(self.dir_map[dir_inode][3])

        # print("[debug] %s has added files: %s, dirs: %s"
        # % (dir_name, new_files, new_dirs))

        for d_inode in new_dirs:
            self.register_dir(dir_stats[d_inode][1],
                              dir_stats[d_inode][0], d_inode)
            self.dir_map[dir_inode][3].add(d_inode)
            self.process_dir(d_inode)

        for f_inode in new_files:
            self.register_file(file_stats[f_inode][1],
                               file_stats[f_inode][0], f_inode)
            self.dir_map[dir_inode][2].add(f_inode)

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
            if self.root_fd is None:
                self.root_fd = dir_fd

            file_inodes = set()
            for f in files:
                if not self.ignore_file(f):
                    _, fd, f_inode = self.fstat_by_name(f, dir_fd=dir_fd)
                    self.register_file(fd, f, f_inode)
                    file_inodes.add(f_inode)

            # TODO: this is messy, fix when refactoring self.fstat_by_name()
            dir_inodes = [self.fstat_by_name(d, is_dir=True, dir_fd=dir_fd)[2]
                          for d in dirs]
            self.register_dir(dir_fd, root, inode,
                              set(file_inodes), set(dir_inodes))

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
            if event.ident != self.root_fd:
                new_name = self.rename_dir(inode)
                actions.append("rename (%s -> %s)" % (dir_name, new_name))

        if flags & KQ_NOTE_DELETE:
            self.unregister_dir(inode)
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            if inode in self.dir_map:  # this happens if a delete occurs
                file_changes, dir_changes = self.process_dir(inode)
                actions.append("writes (files %d, dirs %d)"
                               % (len(file_changes), len(dir_changes)))
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
        #      and we open a new one in the process_dir() routine calling
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
        Gracefully stop the ``Watcher`` instance, trying to close any open
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
