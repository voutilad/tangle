#!/usr/bin/env python3
"""
Unit tests for the Watcher portion of Tangle
"""
import unittest
from tangle import watcher


class WatcherTests(unittest.TestCase):

    def setUp(self):
        self.watcher = watcher.Watcher('/tmp/')

    def test_nothing(self):
        pass


if __name__ == '__main__':
    unittest.main()
