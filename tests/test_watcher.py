#!/usr/bin/env python3
"""
Unit tests for the Watcher portion of Tangle
"""
import os
import unittest
import tempfile
from tangle.watcher import Watcher


THREAD_WAIT = float(os.environ.get('PYTHON_TEST_THREAD_WAIT', '0.25'))


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
        watcher.join(THREAD_WAIT)

        f1 = tempfile.NamedTemporaryFile(dir=self.tmpdir.name)
        f2 = tempfile.NamedTemporaryFile(dir=self.tmpsubdir.name)
        watcher.join(THREAD_WAIT)
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

    def test_can_detect_renaming_files(self):
        """
        Can we rename a file and appropriately update the state maps?
        """
        watcher = self.watcher
        f = open(os.path.join(self.tmpdir.name, 'before'), 'a')
        inode = os.stat(f.fileno()).st_ino

        watcher.start()
        watcher.join(THREAD_WAIT)

        self.assertIn(inode, watcher.file_map)
        self.assertEqual('before', watcher.file_map[inode][1])

        os.rename(os.path.join(self.tmpdir.name, 'before'),
                  os.path.join(self.tmpdir.name, 'after'))
        watcher.join(THREAD_WAIT)

        self.assertEqual('after', watcher.file_map[inode][1])
        watcher.stop()
        watcher.join(THREAD_WAIT)
        f.close()

    def test_can_detect_moving_files(self):
        """
        Can we detect moving files between directories and keeping state?
        """
        watcher = self.watcher
        f = open(os.path.join(self.tmpdir.name, 'tango'), 'a')
        inode = os.stat(f.fileno()).st_ino

        watcher.start()
        watcher.join(THREAD_WAIT)

        self.assertIn(inode, watcher.file_map)
        self.assertIn(inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertNotIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])

        os.rename(os.path.join(self.tmpdir.name, 'tango'),
                  os.path.join(self.tmpsubdir.name, 'tango'))
        watcher.join(THREAD_WAIT)

        self.assertNotIn(inode, watcher.dir_map[self.tmpdir_inode][2])
        self.assertIn(inode, watcher.dir_map[self.tmpsubdir_inode][2])

        watcher.stop()
        watcher.join(THREAD_WAIT)
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
