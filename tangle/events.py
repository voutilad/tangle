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
    move = 5
    started = 6
    stopped = 7

CREATE_FILE = EventType.create_file
CREATE_DIR = EventType.create_dir
WRITE = EventType.write
DELETE = EventType.delete
RENAME = EventType.rename
MOVE = EventType.move
STARTED = EventType.started
STOPPED = EventType.stopped

LocalEvent = namedtuple('LocalEvent', ['type', 'inode', 'time', 'name'])

StartEv = lambda : LocalEvent(STARTED, -1, time(), '')
StopEv = lambda : LocalEvent(STOPPED, -1, time(), '')
CreateFileEv = lambda inode, name : LocalEvent(CREATE_FILE, inode, time(), name)
CreateDirEv = lambda inode, name : LocaleEvent(CREATE_DIR, inode, time(), name)
WriteEv = lambda inode, name : LocalEvent(WRITE, inode, time(), name)
DeleteEv = lambda inode, name : LocalEvent(DELETE, inode, time(), name)
RenameEv = lambda inode, name : LocalEvent(RENAME, inode, time(), name)
MoveEv = lambda inode, name : LocalEvent(MOVE, inode, time(), name)
