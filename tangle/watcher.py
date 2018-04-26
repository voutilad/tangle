"""
File watcher for BSD-style systems using kqueue(2)
"""
import logging
import os
import socket
from collections import namedtuple
from multiprocessing import Process
from queue import Empty
from select import (
    kqueue, kevent, KQ_FILTER_VNODE, KQ_EV_ADD, KQ_EV_ENABLE, KQ_EV_CLEAR,
    KQ_NOTE_RENAME, KQ_NOTE_WRITE, KQ_NOTE_DELETE, KQ_NOTE_ATTRIB
)
from tangle.comm import send_event
from tangle.events import (
    StartEv, StopEv, CreateFileEv, CreateDirEv, WriteEv, DeleteEv,
    RenameFileEv, RenameDirEv
)


LOG = logging.getLogger(__name__)

# TODO: move into Watcher class and make configurable
IGNORE_DIRS = {".git", "CVS", ".svn", ".hg"}
IGNORE_PATTERNS = {".#"}


FileState = namedtuple("FileState", ["fd", "name", "dirs"])
DirState = namedtuple("DirState", ["fd", "name", "files", "dirs"])


class Watcher(Process):
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

    def __init__(self, path, parent_queue=None, sockname=None, daemon=True):
        super().__init__(daemon=daemon)
        self.path = os.path.abspath(path)
        self.parent_queue = parent_queue
        self.root_fd = None
        self.sockname = sockname
        self.inode_map = {}
        self.changelist = []
        self.die = False
        # self.kq = kqueue()

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

        state = DirState(fd, dirname, files, dirs)
        self.inode_map[inode] = state
        event = self.new_event(fd, inode)
        self.changelist.append(event)
        LOG.debug("[registered %d:%s]" % (inode, str(state)))

    def register_file(self, fd, filename, inode, current_dir):
        """
        Open a file descriptor and prepare to construct a new `kevent` to add
        to `self.changelist` so they get registered during the next interaction
        with `kqueue()`. Also add it to the internal `Watcher` state in the
        `self.fd_map` map of files we're watching.

        :param fd: open file descriptor for the file
        :param filename: `str` of the filename
        :param inode: inode number for the file
        :param current_dir: currently known parent directory
        :returns: (inode number, file descriptor)
        """
        state = FileState(fd, filename, current_dir)
        self.inode_map[inode] = state
        event = self.new_event(fd, inode)
        self.changelist.append(event)
        LOG.debug("[registered %d:%s]" % (inode, str(state)))
        return (inode, fd)

    def unregister(self, inode):
        """
        Queues up a de-registration for events on the given file descriptor as
        well as tries to close it and clean up internal state.

        :param inode: inode of the file or dir to unregister
        :returns: name of the file or dir being unregistered
        """
        if inode in self.inode_map:
            state = self.inode_map[inode]
            os.close(state.fd)
            del self.inode_map[inode]
            LOG.debug("[unregistered %d:%s]" % (inode, str(state)))
            return state.name

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

    def update_state(self, fd, name, inode):
        """
        Update our stateful view of a file or dir, given an open file
        descriptor, its current name, and its inode number.

        :param fd: open file descriptor for file
        :param name: name of file in file system
        :param inode: inode number for the file
        :returns: None
        """
        if inode in self.inode_map:
            state = self.inode_map[inode]
            if fd != state.fd:
                os.close(state.fd)
                self.changelist.append(self.new_event(fd, inode))
            if state.name != name:
                LOG.debug("rename detected %s -> %s" % (state.name, name))
            self.inode_map[inode] = state._replace(fd=fd, name=name)

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
        fd, name = self.inode_map[dir_inode][:2]
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
            fd, name, files, dirs = self.inode_map[child_inode]
            old_parent, dir_name = os.path.split(name)
            new_name = os.path.join(parent_path, dir_name)
            self.inode_map[child_inode] = DirState(fd, new_name, files, dirs)
            for f_inode in files:
                state = self.inode_map[f_inode]
                self.inode_map[f_inode] = state._replace(
                    dirs=os.path.join(parent_path, state.name)
                )
            for child in dirs:
                rename_children(new_name, child)

        # walk the children, renaming them as we go
        if new_name:
            for child in self.inode_map[dir_inode].dirs:
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
        dir_fd = self.inode_map[dir_inode].fd
        dir_name = self.inode_map[dir_inode].name

        try:
            (root, dirs, files, rootfd) = next(os.fwalk(dir_fd=dir_fd))
        except FileNotFoundError:
            # race condition? directory may be gone!
            return (set(), set())

        for i in IGNORE_DIRS:
            if i in dirs:
                dirs.remove(i)

        file_stats = {}
        f_inodes = set()
        for f in files:
            if not self.ignore_file(f):
                try:
                    name, fd, f_inode = self.fstat_by_name(f, dir_fd=dir_fd)
                    if f_inode in self.inode_map:
                        os.close(fd)
                        fd = self.inode_map[f_inode][0]
                    file_stats[f_inode] = (name, fd, root)
                    f_inodes.add(f_inode)
                    self.update_state(fd, name, f_inode)
                except FileNotFoundError:
                    # thrown by fstat_by_name()
                    LOG.debug("[possibly moved file: %s]" % f)

        dir_stats = {}
        d_inodes = set()
        for d in dirs:
            name, fd, d_inode = self.fstat_by_name(d, is_dir=True,
                                                   dir_fd=dir_fd)
            if d_inode in self.inode_map:
                os.close(fd)
                fd = self.inode_map[d_inode][0]
            dir_stats[d_inode] = (os.path.join(dir_name, name), fd)
            d_inodes.add(d_inode)
            self.update_state(fd, os.path.join(dir_name, name), d_inode)

        removed_files = self.inode_map[dir_inode].files.difference(f_inodes)
        removed_dirs = self.inode_map[dir_inode].dirs.difference(d_inodes)
        # print("[debug] %s has removed files: %s, dirs: %s"
        # % (dir_name, removed_files, removed_dirs))

        # remove any moved files, de-reg is handled w/ KQ_NOTE_DELETE's
        for f_inode in removed_files:
            self.inode_map[dir_inode].files.remove(f_inode)
        for d_inode in removed_dirs:
            self.inode_map[dir_inode].dirs.remove(d_inode)

        new_files = f_inodes.difference(self.inode_map[dir_inode].files)
        new_dirs = d_inodes.difference(self.inode_map[dir_inode].dirs)

        # Process net-new dirs and files
        for d_inode in new_dirs:
            name, fd = dir_stats[d_inode][:2]
            self.notify(CreateDirEv(d_inode, name, fd))
            self.register_dir(fd, name, d_inode)
            self.inode_map[dir_inode].dirs.add(d_inode)
            self.process_dir(d_inode)

        for f_inode in new_files:
            name, fd = file_stats[f_inode][:2]
            if f_inode not in self.inode_map:
                self.notify(CreateFileEv(f_inode, name, fd))
            self.register_file(fd, name, f_inode, dir_name)
            self.inode_map[dir_inode].files.add(f_inode)

        return (file_stats, dir_stats)

    def notify(self, event):
        """
        Add the given event to the internal queue.
        """
        LOG.info(str(event))
        # LOG.info('XXX sanity check: %s' % str(os.fstat(event.fd)))
        send_event(self.sock, event)

    def connect(self):
        """
        Try to connect to a Processor via a socket
        """
        LOG.info('Opening socket on %s' % self.sockname)
        self.sock = socket.socket(family=socket.AF_UNIX)
        self.sock.connect(self.sockname)
        LOG.info('Connected via %s' % self.sockname)

    def run(self):
        """
        Main event loop for Watcher. Performs initial walk of target
        directory and registers events. Executes an event-loop to hande
        new events as they are returned by the kernel.
        """
        # bootstrap
        self.kq = kqueue()

        self.root_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY)
        for root, dirs, files, rootfd in os.fwalk('.', dir_fd=self.root_fd):
            for i in IGNORE_DIRS:
                if i in dirs:
                    dirs.remove(i)
                    print("[ignoring %s/%s/]" % (root, i))

            dir_fd = os.dup(rootfd)
            inode = os.fstat(dir_fd).st_ino

            file_inodes = set()
            for f in files:
                if not self.ignore_file(f):
                    _, fd, f_inode = self.fstat_by_name(f, dir_fd=dir_fd)
                    self.register_file(fd, f, f_inode, root)
                    file_inodes.add(f_inode)

            # TODO: this is messy, fix when refactoring self.fstat_by_name()
            dir_inodes = [self.fstat_by_name(d, is_dir=True, dir_fd=dir_fd)[2]
                          for d in dirs]
            self.register_dir(dir_fd, root, inode,
                              set(file_inodes), set(dir_inodes))

        self.connect()
        self.notify(StartEv())

        # main event loop
        while not self.die:
            # ???: without a timeout, no clean way to break out!
            events = self.kq.control(self.changelist, 1, 1)
            self.changelist.clear()
            for event in events:
                inode = event.udata
                state = self.inode_map.get(inode, 0)

                if isinstance(state, DirState):
                    self.handle_dir_event(event)
                elif isinstance(state, FileState):
                    self.handle_file_event(event)
                else:
                    LOG.error("Serious state issue! Unknown inode %s" % inode)
            try:
                self.parent_queue.get_nowait()
                self.stop()
            except Empty:
                # TODO: add proper messaging from parent process
                pass

        # notify listeners we're done
        self.notify(StopEv())
        # self.parent_queue.put_nowait(StopEv())
        self.dump()

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
        state = self.inode_map[inode]
        actions = []

        if flags & KQ_NOTE_RENAME:
            if event.ident != self.root_fd:
                new_name = self.rename_dir(inode)
                self.notify(RenameDirEv(inode, new_name, state.fd))
                actions.append("rename (%s -> %s)" % (state.name, new_name))

        if flags & KQ_NOTE_DELETE:
            self.unregister(inode)
            actions.append("delete")
            self.notify(DeleteEv(inode, state.name, state.fd))

        if flags & KQ_NOTE_WRITE:
            if inode in self.inode_map:  # this happens if a delete occurs
                file_changes, dir_changes = self.process_dir(inode)
                actions.append("writes (files %d, dirs %d)"
                               % (len(file_changes), len(dir_changes)))
            else:  # ???: is this conditional still valid?
                actions.append("writes ignored (%s)" % str(state.name))
        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        LOG.debug("[d!%d] (%s) %s@%s - %s" % (inode, hex(flags),
                                              state.name, state.fd, actions))

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
        state = self.inode_map[inode]
        path = os.path.join(state.dirs, state.name)

        if flags & KQ_NOTE_RENAME:
            self.notify(RenameFileEv(inode, path, state.fd))
            actions.append("rename")

        if flags & KQ_NOTE_DELETE:
            self.unregister(inode)
            self.notify(DeleteEv(inode, state.name, state.fd))
            actions.append("delete")

        if flags & KQ_NOTE_WRITE:
            self.notify(WriteEv(inode, state.name, state.fd))
            actions.append("write")

        if flags & KQ_NOTE_ATTRIB:
            actions.append("attrib")
        LOG.debug("[f!%d] (%s) %s@%s - %s" % (inode, hex(flags),
                                              state.name, state.fd, actions))

    def stop(self):
        """
        Gracefully stop the ``Watcher`` instance, trying to close any open
        file descriptors first.

        :returns: None
        """
        LOG.info("Stopping watcher...")
        for inode, state in self.inode_map.items():
            try:
                os.close(state.fd)
            except OSError:
                LOG.warning("[e] couldn't close fd %s" % state.fd)

        self.die = True

    def dump(self):
        from pprint import pprint
        pprint(self.inode_map)
