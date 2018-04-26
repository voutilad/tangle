import array
import logging
import os
import socket
from selectors import DefaultSelector, EVENT_READ
from tangle.events import dump_event, load_event, CREATE_FILE, WRITE, RENAME_FILE, RENAME_DIR


LOG = logging.getLogger(__name__)

# SELECTOR = DefaultSelector()


def send_event(sock, event):
    """
    Send a LocalEvent over a given socket including the approrpriate file
    descriptor
    """
    msg = dump_event(event)

    if event.type in [CREATE_FILE, WRITE, RENAME_FILE, RENAME_DIR]:
        anc_data = [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                     array.array('i', [event.fd]))]
        return sock.sendmsg([msg], anc_data)
    # TODO: handle partial sends and resend remaining data?
    return sock.sendmsg([msg])


def recv_event(sock, timeout=None):
    """
    Receive an LocalEvent via a given socket, expecting a file descriptor
    as well.
    """
    sel = DefaultSelector()
    sel.register(sock, EVENT_READ)
    events = sel.select(timeout=timeout)
    sel.unregister(sock)
    if len(events) < 1:
        print('ERR: timeout receiving events!')
        return None, None

    fds = array.array('i')
    cmsg_len = socket.CMSG_LEN(2 * fds.itemsize)
    (data, anc_data, _, _) = sock.recvmsg(4096, cmsg_len)

    # Case where we're not sending File Descrpitors
    if anc_data is None or len(anc_data) < 1:
        return load_event(data), None

    # Otherwise, let's look for file descriptors in the ancillary data
    for (level, msgtype, payload) in anc_data:
        if level == socket.SOL_SOCKET and msgtype == socket.SCM_RIGHTS:
            fd_bytestr = payload[:len(payload) - (len(payload) % fds.itemsize)]
            fds.fromstring(fd_bytestr)
            fd = fds[0]
            event = load_event(data)

            # sanity check
            stat = os.fstat(fd)
            inode = stat.st_ino
            assert inode == event.inode
            event._replace(fd=fd)

            if event.type in [CREATE_FILE, RENAME_FILE, WRITE]:
                return event, os.fdopen(fd)
            return event, None

    return None, None
