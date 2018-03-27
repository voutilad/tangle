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
    copy = 5
    started = 9
    stopped = 10
    shutdown = 69


CREATE_FILE = EventType.create_file
CREATE_DIR = EventType.create_dir
WRITE = EventType.write
DELETE = EventType.delete
RENAME = EventType.rename
COPY = EventType.copy
STARTED = EventType.started
STOPPED = EventType.stopped
SHUTDOWN = EventType.shutdown

LocalEvent = namedtuple('LocalEvent', ['type', 'inode', 'time', 'name', 'fd'])


def StartEv(): return LocalEvent(STARTED, -1, time(), '', -1)


def StopEv(): return LocalEvent(STOPPED, -1, time(), '', -1)


def CreateFileEv(inode, name, fd):
    return LocalEvent(CREATE_FILE, inode, time(), name, fd)


def CreateDirEv(inode, name, fd):
    return LocalEvent(CREATE_DIR, inode, time(), name, fd)


def WriteEv(inode, name, fd):
    return LocalEvent(WRITE, inode, time(), name, fd)


def DeleteEv(inode, name, fd):
    return LocalEvent(DELETE, inode, time(), name, fd)


def RenameEv(inode, name, fd):
    return LocalEvent(RENAME, inode, time(), name, fd)


def CopyEv(inode, name):
    return LocalEvent(COPY, inode, time(), name)
