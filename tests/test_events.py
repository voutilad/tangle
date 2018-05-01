#!/usr/bin/env python3
"""
Unit tests for the Event functions
"""
# import os
import unittest
from tangle.events import StartEv, StopEv, CreateFileEv, WriteEv, dump_event, load_event

class EventUnitTests(unittest.TestCase):

    def test_dumping_events(self):
        ev = StartEv()
        raw = dump_event(ev)
        self.assertIsNotNone(raw)
