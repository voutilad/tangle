"""
File Events
"""
from pickle import loads, dumps
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
    rename_file = 4
    rename_dir = 5
    started = 9
    stopped = 10
    shutdown = 69


CREATE_FILE = EventType.create_file
CREATE_DIR = EventType.create_dir
WRITE = EventType.write
DELETE = EventType.delete
RENAME_FILE = EventType.rename_file
RENAME_DIR = EventType.rename_dir
STARTED = EventType.started
STOPPED = EventType.stopped
SHUTDOWN = EventType.shutdown

LocalEvent = namedtuple('LocalEvent', ['type', 'inode', 'time', 'name', 'fd'])

def dump_event(event):
    return dumps(event._asdict())

def load_event(event_str):
    return LocalEvent._make(loads(event_str).values())


def StartEv(): return LocalEvent(STARTED, -1, time(), '', None)


def StopEv(): return LocalEvent(STOPPED, -1, time(), '', None)


def CreateFileEv(inode, name, fd):
    return LocalEvent(CREATE_FILE, inode, time(), name, fd)


def CreateDirEv(inode, name, fd):
    return LocalEvent(CREATE_DIR, inode, time(), name, fd)


def WriteEv(inode, name, fd):
    return LocalEvent(WRITE, inode, time(), name, fd)


def DeleteEv(inode, name, fd):
    return LocalEvent(DELETE, inode, time(), name, fd)


def RenameFileEv(inode, name, fd):
    return LocalEvent(RENAME_FILE, inode, time(), name, fd)

def RenameDirEv(inode, name, fd):
    return LocalEvent(RENAME_DIR, inode, time(), name, fd)
