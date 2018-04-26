#!/usr/bin/env python3
"""
Unit tests for the Watcher portion of Tangle
"""
import os
import unittest
from unittest.mock import MagicMock, patch
from selectors import DefaultSelector, EVENT_READ
import shutil
import socket
import tempfile
from multiprocessing import Queue
from queue import Empty

from tangle.comm import recv_event
from tangle.watcher import Watcher
from tangle.events import (
    SHUTDOWN, STARTED, STOPPED,
    WRITE, DELETE, RENAME_FILE, RENAME_DIR, CREATE_FILE, CREATE_DIR
)


class WatcherUnitTests(unittest.TestCase):
    """
    These tests isolate specific functionality of the Watcher class and should
    not require creation and execution of Watcher threads. Lastly, they can be
    safely run without race conditions.
    """
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.queue = Queue()
        self.watcher = Watcher(self.tempdir.name, self.queue)

    def test_ignoring_files_and_directories(self):
        """
        Files should be ignored based on a starting pattern.
        Directories should be ignored if a complete match.
        """
        self.assertTrue(self.watcher.ignore_file(".#emacsfile"))
        self.assertFalse(self.watcher.ignore_file("passwords.txt"))

    def test_fstat_by_name(self):
        """
        Make sure we can look up an inode by just a file path.

        TODO: This test makes me want to refactor the method.
        """
        dir_inode = os.stat(self.tempdir.name).st_ino
        file_path = os.path.join(self.tempdir.name, "junk")
        f = open(file_path, "a")
        f_inode = os.fstat(f.fileno()).st_ino

        path, fd, inode = self.watcher.fstat_by_name(file_path)
        self.assertEqual(inode, f_inode)
        self.assertEqual(path, file_path)
        self.assertTrue(fd > 0)

        dir_fd = os.open(self.tempdir.name, os.O_RDONLY | os.O_DIRECTORY)
        path, fd, inode = self.watcher.fstat_by_name("junk", dir_fd=dir_fd)
        self.assertEqual(inode, f_inode)
        self.assertEqual(path, "junk")
        self.assertTrue(fd > 0)

        path, fd, inode = self.watcher.fstat_by_name(self.tempdir.name,
                                                     is_dir=True)
        self.assertEqual(path, self.tempdir.name)
        self.assertEqual(dir_inode, inode)

    def test_registering_directory(self):
        """
        Test the logic for "registering" a new directory in our state. This
        includes tracking it in the map and staging a new kqueue event for
        registration.

        TODO: Should we test ensuring sets are created for file/dir lists?
        """
        self.watcher.register_dir(1, "mydir", 123)

        entry = self.watcher.inode_map.get(123, None)
        self.assertIsNotNone(entry)

        self.assertEqual(1, entry.fd)
        self.assertEqual("mydir", entry.name)
        self.assertEqual(0, len(entry.files))
        self.assertEqual(0, len(entry.dirs))

        ev = self.watcher.changelist.pop()
        self.assertEqual(1, ev.ident)
        self.assertEqual(123, ev.udata)

        self.watcher.register_dir(2, "another", 222, {1, 2}, {5, 6, 7})
        entry = self.watcher.inode_map[222]
        self.assertEqual({1, 2}, entry.files)
        self.assertEqual({5, 6, 7}, entry.dirs)

    def test_nothing(self):
        self.tempdir.cleanup()


class WatcherIntegrationTests(unittest.TestCase):
    """
    These tests utilize a supported file system and automate creation and
    modification of test files to evaluate if the Watcher behaves properly and
    as designed. If these fail, it should be indicative of something worth
    investigating.
    """
    QUEUE_WAIT = float(os.environ.get("PYTHON_TEST_QUEUE_WAIT", "5"))

    def setUp(self):
        self.sockfile = tempfile.NamedTemporaryFile()
        self.sockfile.close()

        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmpsubdir = tempfile.TemporaryDirectory(dir=self.tmpdir.name)
        self.tmpdir_inode = os.stat(self.tmpdir.name).st_ino
        self.tmpsubdir_inode = os.stat(self.tmpsubdir.name).st_ino

        # patch.object(Watcher, 'notify', mock_send_event).start()
        # patch.object(Watcher, 'connect').start()

        self.socket = socket.socket(family=socket.AF_UNIX)
        self.socket.bind(self.sockfile.name)
        self.socket.listen()

        self.msg_queue = Queue()
        self.parent_queue = Queue()
        print('Creating Watcher with socket file: %s' % self.sockfile.name)
        self.watcher = Watcher(self.tmpdir.name,
                               sockname=self.sockfile.name,
                               parent_queue=self.parent_queue)
       # self.addCleanup(patch.stopall())

    def tearDown(self):
        self.tmpsubdir.cleanup()
        self.tmpdir.cleanup()
        self.socket.close()
        # self.sockfile.close()

    def abs_tmppath(self, relpath):
        path = os.path.join(self.tmpdir.name, relpath)
        path = os.path.abspath(os.path.realpath(os.path.join(path)))

        if os.uname()[0] == 'Darwin' and path.startswith('/private'):
            # this is a hack around how macOS handles temp dirs
            return path[len('/private'):]
        else:
            return path

    def poll(self, sock, timeout=None):
        if timeout is None:
            timeout = self.QUEUE_WAIT
        try:
            (event, _) = recv_event(sock, timeout=timeout)
            return event
        except Empty:
            self.fail("Timeout polling Watcher event queue (timeout: %d)"
                      % timeout)

    def stop_watcher(self):
        self.parent_queue.put(SHUTDOWN)

    def assertEvent(self, event, exp_type, exp_inode=None, exp_name=None):
        self.assertEqual(exp_type, event.type)
        if exp_inode:
            self.assertEqual(exp_inode, event.inode)
        if exp_name:
            self.assertEqual(exp_name, event.name)

    def start_watcher(self):
        self.watcher.start()
        sel = DefaultSelector()

        sel.register(self.socket, EVENT_READ)
        events = sel.select(timeout=self.QUEUE_WAIT)
        sel.unregister(self.socket)

        if len(events) > 0:
            conn, _ = self.socket.accept()
            return conn
        self.fail('Could not start watcher. Timeout waiting for socket connection.')

    def test_can_detect_adding_files(self):
        """
        Adding files should result in adding them to the file and directory
        states.
        """
        conn = self.start_watcher()

        self.assertEqual(STARTED, self.poll(conn).type)

        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f1_inode = os.stat(f1.name).st_ino
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)
        f2_inode = os.stat(f2.name).st_ino

        self.assertEvent(self.poll(conn),
                         CREATE_FILE, f1_inode, os.path.basename(f1.name))
        self.assertEvent(self.poll(conn),
                         CREATE_FILE, f2_inode, os.path.basename(f2.name))

        self.stop_watcher()
        self.assertEqual(STOPPED, self.poll(conn).type)

        conn.close()
        f1.close()
        f2.close()

    def test_can_detect_deleting_files(self):
        """
        Deleting files should remove them from the file and directory states.
        """
        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)

        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        f2.close()
        event = self.poll(conn)
        self.assertEqual(DELETE, event.type)
        self.assertEqual(os.path.basename(f2.name), event.name)

        f1.close()
        event = self.poll(conn)
        self.assertEqual(DELETE, event.type)
        self.assertEqual(os.path.basename(f1.name), event.name)

        self.stop_watcher()
        self.assertEqual(STOPPED, self.poll(conn).type)
        conn.close()

    def test_can_detect_renaming_files(self):
        """
        Can we rename a file and appropriately update the state maps?
        """
        f = open(os.path.join(self.tmpdir.name, 'before'), 'a')

        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        os.rename(os.path.join(self.tmpdir.name, 'before'),
                  os.path.join(self.tmpdir.name, 'after'))
        ev = self.poll(conn)

        self.assertEqual(RENAME_FILE, ev.type)
        self.assertEqual(os.path.join(self.tmpdir.name, 'after'),
                         self.abs_tmppath(ev.name))

        self.stop_watcher()
        self.assertEqual(STOPPED, self.poll(conn).type)
        f.close()
        conn.close()

    def test_can_detect_copying_files(self):
        """
        Can we detect the copying of a file?

        Turns out this really results in a CREATE event where we get
        a new inode and everything.
        """
        f = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)

        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        shutil.copy(f.name, os.path.join(self.tmpdir.name, "a_copy"))

        ev = self.poll(conn)
        self.assertEqual(CREATE_FILE, ev.type)
        conn.close()

    def test_can_detect_moving_files(self):
        """
        Can we detect moving files between directories and keeping state?
        """
        f = open(os.path.join(self.tmpdir.name, 'tango'), 'a')

        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        os.rename(os.path.join(self.tmpdir.name, 'tango'),
                  os.path.join(self.tmpsubdir.name, 'tango'))
        ev = self.poll(conn)

        self.assertEqual(RENAME_FILE, ev.type)
        self.assertEqual(os.path.join(self.tmpsubdir.name, 'tango'),
                         self.abs_tmppath(ev.name))

        # now move it back! turns out depending on "direction" the underlying
        # kernel events might happen differently
        os.rename(os.path.join(self.tmpsubdir.name, 'tango'),
                  os.path.join(self.tmpdir.name, 'tango'))
        ev = self.poll(conn)

        self.assertEqual(RENAME_FILE, ev.type)
        self.assertEqual(os.path.join(self.tmpdir.name, 'tango'),
                         self.abs_tmppath(ev.name))

        self.stop_watcher()
        self.assertEqual(STOPPED, self.poll(conn).type)
        f.close()
        conn.close()

    def test_can_detect_deleting_directories(self):
        """
        Can we detect a directory delete and handle deleting subdir content?
        """
        f = open(os.path.join(self.tmpsubdir.name, 'junk'), 'a')
        f.close()

        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        self.tmpsubdir.cleanup()

        ev = self.poll(conn)
        self.assertEqual(DELETE, ev.type)

        ev = self.poll(conn)
        self.assertEqual(DELETE, ev.type)

        self.stop_watcher()
        conn.close()

    def test_can_detect_renaming_directories(self):
        """
        Can we properly handle updating state during a directory rename?

        This one is a bit complex as we store some relative path details.
        """
        with tempfile.TemporaryDirectory(dir=self.tmpsubdir.name) as subsubdir:
            new_name = 'junkdir'

            f = open(os.path.join(subsubdir, 'junkfile'), 'a')
            conn = self.start_watcher()
            self.assertEqual(STARTED, self.poll(conn).type)

            # note: this doesn't update the TemporaryDirectory instance
            os.rename(self.tmpsubdir.name,
                      os.path.join(self.tmpdir.name, new_name))
            ev = self.poll(conn)
            self.assertEqual(RENAME_DIR, ev.type)
            self.assertEqual(os.path.join(self.tmpdir.name, new_name),
                             self.abs_tmppath(ev.name))

            self.stop_watcher()
            self.assertEqual(STOPPED, self.poll(conn).type)

            f.close()
            conn.close()
            # reset so the cleanup routine succeeds.
            os.rename(os.path.join(self.tmpdir.name, new_name),
                      self.tmpsubdir.name)

    def test_can_detect_file_writes(self):
        with open(os.path.join(self.tmpdir.name, "junk"), "a") as f:
            inode = os.stat(f.fileno()).st_ino

            conn = self.start_watcher()
            self.assertEqual(STARTED, self.poll(conn).type)

            f.write("don't stop believing")
            f.flush()
            ev = self.poll(conn)

            self.assertEqual(WRITE, ev.type)
            self.assertEqual(inode, ev.inode)

            self.stop_watcher()
            self.assertEqual(STOPPED, self.poll(conn).type)
            conn.close()

    def test_can_detect_directory_creation(self):
        conn = self.start_watcher()
        self.assertEqual(STARTED, self.poll(conn).type)

        path = os.path.join(self.tmpdir.name, 'junkdir')
        os.mkdir(path)

        ev = self.poll(conn)
        self.assertEqual(CREATE_DIR, ev.type)

        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        self.assertEqual(os.stat(fd).st_ino, ev.inode)

        os.close(fd)

        self.stop_watcher()
        self.assertEqual(STOPPED, self.poll(conn).type)
        conn.close()


if __name__ == '__main__':
    unittest.main()
