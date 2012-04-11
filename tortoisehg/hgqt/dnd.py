# dnd.py - TortoiseHg's Drag and Drop handling
#
# Copyright 2011 Daniel Atallah <daniel.atallah@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt import thgrepo, quickop

def __do_run(ui, command, *pats, **_opts):
    root = paths.find_root()
    repo = thgrepo.repository(ui, root)

    pats = hglib.canonpaths(pats)

    cmdline = [command] + pats
 
    instance = quickop.HeadlessQuickop(repo, cmdline)
    return instance

def run_copy(ui, *pats, **opts):
    return __do_run(ui, "copy", *pats, **opts)

def run_move(ui, *pats, **opts):
    return __do_run(ui, "move", *pats, **opts)
