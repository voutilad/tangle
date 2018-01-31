Just some thoughts
==================

* Add some safety to any racy `watcher` routines, specifically around calls to
  `os.stat` to get inode numbers when enumerating directories.
  - directories _could_ be deleted while we're iterating over them
  - files, too, could be destroyed or moved

* Downline, we need to ultimately treat the events as a stream and add a
  temporal element
  - if a file is _hot_, i.e. *n-writes per second* occurring, don't queue it for
    synchronization until it _cools down_
  - use this to limit operations that result in IO and trips through kernelspace
