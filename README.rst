*********************************
Tangle: Quantum File Entanglement
*********************************

The start of a bi-directional file synchronization utility. Or at least I hope.

*Currently only supports BSD-like systems due to explicit usage of the
``kqueue(2)`` event queue mechanism found in the BSDs and macOS.*


Requirements
============
* **Python 3.6** (may work with 3.4 or 3.5...no Py2.7 support planned.)
* **BSD** based operating system, specifically tested on:
  - OpenBSD 6.2
  - macOS 10.13 (High Sierra)

    
Why "tangle"?
=============
My use case is simple and very similar to personal DropBox usage. I work on
many different machines (never simultaneously) and need constant access to the
latest version of a PowerPoint file or something.

Why not Git?
------------
1. I don't care about "branching" in this situation
2. Many of these files will probably be *MS Office* or *PDF* files, which don't
   lend well to version control approaches
3. I don't care about deep, historical change logs
4. No need for patches or diffs

Why not some web-based thing?
-----------------------------
I want this to be seamless and just want the benefit of using my local
filesystem as I normally would without opening Chrome or FireFox and dealin
with crappy UX.


License & Usage
===============
Tangle, and all the included files, are provided under the permissive
`BSD 2-Clause License <./LICENSE>` and provided "as is" with no warranties.

It is software the manipulates your data, possibly sending it somewhere else,
and possibly synchronizing things like deletes to data. While the purpose and
intent of the software is to handle your data safely, sanely, and securely,
ultimately it is your choice to use the software and your responsibility for
the outcome.

