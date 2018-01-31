#!/usr/bin/env python3
"""
Unit tests for the Watcher portion of Tangle
"""
import os
import unittest
import tempfile
from tangle.watcher import Watcher


THREAD_WAIT = 0.25


class WatcherUnitTests(unittest.TestCase):

    def setUp(self):
        pass

    def test_nothing(self):
        pass


class WatcherIntegrationTests(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmpsubdir = tempfile.TemporaryDirectory(dir=self.tmpdir.name)
        self.tmpdir_inode = os.stat(self.tmpdir.name).st_ino
        self.tmpsubdir_inode = os.stat(self.tmpsubdir.name).st_ino

        self.watcher = Watcher(self.tmpdir.name)

    def test_can_detect_adding_files(self):
        """
        Adding files should result in adding them to the file and directory
        states.
        """
        watcher = self.watcher
        watcher.start()
        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)
        watcher.stop()
        watcher.join(THREAD_WAIT)

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
        watcher.join(THREAD_WAIT)
        self.assertEqual(2, len(watcher.file_map))
        self.assertEqual(2, len(watcher.dir_map))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpsubdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][3]))

        f1.close()
        f2.close()

        watcher.join(THREAD_WAIT)
        watcher.stop()
        watcher.join(THREAD_WAIT)

        self.assertEqual(0, len(watcher.file_map))
        self.assertEqual(2, len(watcher.dir_map))
        self.assertEqual(0, len(watcher.dir_map[self.tmpdir_inode][2]))
        self.assertEqual(0, len(watcher.dir_map[self.tmpsubdir_inode][2]))
        self.assertEqual(1, len(watcher.dir_map[self.tmpdir_inode][3]))

    def test_can_rename_files(self):
        """
        Can we rename a file and appropriately update the state maps?
        """
        pass

    def tearDown(self):
        self.tmpsubdir.cleanup()
        self.tmpdir.cleanup()


if __name__ == '__main__':
    unittest.main()
