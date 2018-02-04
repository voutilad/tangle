#!/usr/bin/env python3
"""
Unit tests for the Watcher portion of Tangle
"""
import os
import unittest
import tempfile
from queue import Queue, Empty
from tangle.watcher import Watcher
from tangle.events import *

THREAD_WAIT = float(os.environ.get("PYTHON_TEST_THREAD_WAIT", "0.5"))
QUEUE_WAIT = float(os.environ.get("PYTHON_TEST_QUEUE_WAIT", "2.0"))


class WatcherUnitTests(unittest.TestCase):
    """
    These tests isolate specific functionality of the Watcher class and should
    not require creation and execution of Watcher threads. Lastly, they can be
    safely run without race conditions.
    """
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.watcher = Watcher(self.tempdir)

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

        dir_fd = os.open(self.tempdir.name, os.O_RDONLY|os.O_DIRECTORY)
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

        entry = self.watcher.dir_map.get(123, None)
        self.assertIsNotNone(entry)

        self.assertEqual(1, entry[0])
        self.assertEqual("mydir", entry[1])
        self.assertEqual(0, len(entry[2]))
        self.assertEqual(0, len(entry[3]))

        ev = self.watcher.changelist.pop()
        self.assertEqual(1, ev.ident)
        self.assertEqual(123, ev.udata)

        self.watcher.register_dir(2, "another", 222, {1, 2}, {5, 6, 7})
        entry = self.watcher.dir_map[222]
        self.assertEqual({1, 2}, entry[2])
        self.assertEqual({5, 6, 7}, entry[3])

    def test_nothing(self):
        self.tempdir.cleanup()


class WatcherIntegrationTests(unittest.TestCase):
    """
    These tests utilize a supported file system and automate creation and
    modification of test files to evaluate if the Watcher behaves properly and
    as designed. If these fail, it should be indicative of something worth
    investigating.

    There may be some race conditions as this does end up spawning Watcher
    threads. Liberal calls of ``watcher.join(THREAD_WAIT)`` are used where
    ``THREAD_WAIT`` lets the test routine safely sleep for a bit while the
    watcher catches up to the state of the file system.

    On my Lenovo x270, a ``THREAD_WAIT`` of 0.5 seconds seems to routinely be
    safe to use.

    ``THREAD_WAIT`` can be set in this module or by setting it via the
    ``PYTHON_TEST_THREAD_WAIT`` environment variable.
    """

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmpsubdir = tempfile.TemporaryDirectory(dir=self.tmpdir.name)
        self.tmpdir_inode = os.stat(self.tmpdir.name).st_ino
        self.tmpsubdir_inode = os.stat(self.tmpsubdir.name).st_ino

        self.watcher = Watcher(self.tmpdir.name, evqueue=Queue())

    def poll(self, timeout=QUEUE_WAIT):
        try:
            return self.watcher.evqueue.get(timeout=timeout)
        except Empty:
            self.fail("Timeout polling Watcher event queue (timeout: %d)"
                      % timeout)

    def test_can_detect_adding_files(self):
        """
        Adding files should result in adding them to the file and directory
        states.
        """
        watcher = self.watcher
        watcher.start()

        self.assertEqual(STARTED, self.poll().type)
        
        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)

        self.assertEqual(CREATE_FILE, self.poll().type)
        self.assertEqual(CREATE_FILE, self.poll().type)

        watcher.stop()
        self.assertEqual(STOPPED, self.poll().type)
 
        f1_inode = os.stat(f1.name).st_ino
        f2_inode = os.stat(f2.name).st_ino
        f1_name = os.path.basename(f1.name)
        f2_name = os.path.basename(f2.name)

        f1.close()
        f2.close()

        self.assertEqual(2, len(watcher.dir_map))
        self.assertIn(f1_inode, watcher.file_map)
        self.assertIn(f2_inode, watcher.file_map)
        self.assertEqual(f1_name, watcher.file_map[f1_inode][1])
        self.assertEqual(f2_name, watcher.file_map[f2_inode][1])
        self.assertIn(f1_inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertIn(f2_inode, watcher.dir_map[self.tmpsubdir_inode][2])

        

    def test_can_detect_deleting_files(self):
        """
        Deleting files should remove them from the file and directory states.
        """
        watcher = self.watcher
        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)

        watcher.start()
        self.assertEqual(STARTED, self.poll().type)
        self.assertEqual(2, len(watcher.file_map))
        self.assertEqual(2, len(watcher.dir_map))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpsubdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][3]))

        f1.close()
        f2.close()

        event = self.poll()
        self.assertEqual(DELETE, event.type)
        self.assertEqual(f1.name, event.name)
        event = self.poll()
        self.assertEqual(DELETE, event.type)
        self.assertEqual(f2.name, event.name)

        watcher.stop()
        self.assertEqual(STOPPED, self.poll().type)

        self.assertEqual(0, len(watcher.file_map))
        self.assertEqual(2, len(watcher.dir_map))
        self.assertEqual(0, len(watcher.dir_map[self.tmpdir_inode][2]))
        self.assertEqual(0, len(watcher.dir_map[self.tmpsubdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][3]))

    def test_can_detect_renaming_files(self):
        """
        Can we rename a file and appropriately update the state maps?
        """
        watcher = self.watcher
        f = open(os.path.join(self.tmpdir.name, 'before'), 'a')
        inode = os.stat(f.fileno()).st_ino

        watcher.start()
        self.assertEqual(STARTED, self.poll().type)

        self.assertIn(inode, watcher.file_map)
        self.assertEqual('before', watcher.file_map[inode][1])

        os.rename(os.path.join(self.tmpdir.name, 'before'),
                  os.path.join(self.tmpdir.name, 'after'))
        ev = self.poll()
        
        self.assertEqual(RENAME, ev.type)
        self.assertEqual(os.path.join(self.tmpdir.name, 'after'), ev.name)
        self.assertEqual('after', watcher.file_map[inode][1])

        watcher.stop()
        self.assertEqual(STOPPED, self.poll().type)
        f.close()

    def test_can_detect_moving_files(self):
        """
        Can we detect moving files between directories and keeping state?
        """
        watcher = self.watcher
        f = open(os.path.join(self.tmpdir.name, 'tango'), 'a')
        inode = os.stat(f.fileno()).st_ino

        watcher.start()
        self.assertEqual(STARTED, self.poll().type)

        self.assertIn(inode, watcher.file_map)
        self.assertIn(inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertNotIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])

        os.rename(os.path.join(self.tmpdir.name, 'tango'),
                  os.path.join(self.tmpsubdir.name, 'tango'))
        ev = self.poll()

        self.assertEqual(RENAME, ev.type)
        self.assertEqual(os.path.join(self.tmpsubdir.name, 'tango'), ev.name)

        self.assertNotIn(inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])

        # now move it back! turns out depending on "direction" the underlying
        # kernel events might happen differently
        os.rename(os.path.join(self.tmpsubdir.name, 'tango'),
                  os.path.join(self.tmpdir.name, 'tango'))
        ev = self.poll()

        self.assertEqual(RENAME, ev.type)
        self.assertEqual(os.path.join(self.tmpdir.name, 'tango'), ev.name)

        self.assertIn(inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertNotIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])
        
        watcher.stop()
        self.assertEqual(STOPPED, self.poll().type)
        f.close()

    def test_can_detect_deleting_directories(self):
        """
        Can we detect a directory delete and handle deleting subdir content?
        """
        watcher = self.watcher
        f = open(os.path.join(self.tmpsubdir.name, 'junk'), 'a')
        inode = os.stat(f.fileno()).st_ino
        f.close()

        watcher.start()
        watcher.join(THREAD_WAIT)

        self.assertIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])
        self.assertIn(inode, watcher.file_map)

        self.tmpsubdir.cleanup()
        watcher.join(THREAD_WAIT)

        self.assertEqual(0, len(watcher.file_map))
        self.assertNotIn(self.tmpsubdir_inode, watcher.dir_map)

    def test_can_detect_renaming_directories(self):
        """
        Can we properly handle updating state during a directory rename?

        This one is a bit complex as we store some relative path details.
        """
        watcher = self.watcher
        with tempfile.TemporaryDirectory(dir=self.tmpsubdir.name) as subsubdir:
            inode = os.stat(subsubdir).st_ino
            new_name = 'junkdir'

            watcher.start()
            watcher.join(THREAD_WAIT)

            self.assertIn(self.tmpsubdir.name, watcher.dir_map[inode][1])

            # note: this doesn't update the TemporaryDirectory instance
            os.rename(self.tmpsubdir.name,
                      os.path.join(self.tmpdir.name, new_name))
            watcher.join(THREAD_WAIT)

            self.assertIn(new_name, watcher.dir_map[inode][1])
            self.assertIn(new_name, watcher.dir_map[self.tmpsubdir_inode][1])
            self.assertNotIn(os.path.basename(self.tmpsubdir.name),
                             watcher.dir_map[inode][1])
            self.assertNotIn(os.path.basename(self.tmpsubdir.name),
                             watcher.dir_map[self.tmpsubdir_inode][1])

            watcher.stop()
            watcher.join(THREAD_WAIT)

            os.rename(os.path.join(self.tmpdir.name, new_name),
                      self.tmpsubdir.name)

    def tearDown(self):
        self.tmpsubdir.cleanup()
        self.tmpdir.cleanup()


if __name__ == '__main__':
    unittest.main()
