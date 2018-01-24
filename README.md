# tangle

The start of a bi-directional file synchronization utility. Or at least I hope.

*Currently only supports BSD-like systems due to explicit usage of `kqueue(2)`
underpinnings.*
    
## Requirements

* Python 3.6 (need to figure out minimum Py3 version...3.4 or 3.5 maybe?)
  - No planned Py2.7 support
* BSD-based system, specifically tested on:
  - OpenBSD 6.2
  - macOS 10.13 (High Sierra)

## Why "tangle"?

My simple use case is basically similar to personal DropBox usage: I work on
many different machines (never simultaneously) and need constant access to the
latest version of a PowerPoint file or something.

### Why not Git? (Or git-based things?)

1. I don't care about "branching"
2. Many of these files will probably be MS Office or PDF files which don't
   lend well to version control approaches
3. I don't care about having access to all historical changes to files
