"""
File Events
"""
from collections import namedtuple
from enum import Enum
from time import time


class EventType(Enum):
    """
    Definition of supported file system events:

    ``EventType.write``: a write occurred
    ...
    """
    create_file = 0
    create_dir = 1
    write = 2
    delete = 3
    rename = 4
    started = 6
    stopped = 7


CREATE_FILE = EventType.create_file
CREATE_DIR = EventType.create_dir
WRITE = EventType.write
DELETE = EventType.delete
RENAME = EventType.rename
STARTED = EventType.started
STOPPED = EventType.stopped


LocalEvent = namedtuple('LocalEvent', ['type', 'inode', 'time', 'name'])


def StartEv(): return LocalEvent(STARTED, -1, time(), '')


def StopEv(): return LocalEvent(STOPPED, -1, time(), '')


def CreateFileEv(inode, name):
    return LocalEvent(CREATE_FILE, inode, time(), name)


def CreateDirEv(inode, name):
    return LocalEvent(CREATE_DIR, inode, time(), name)


def WriteEv(inode, name): return LocalEvent(WRITE, inode, time(), name)


def DeleteEv(inode, name): return LocalEvent(DELETE, inode, time(), name)


def RenameEv(inode, name): return LocalEvent(RENAME, inode, time(), name)
