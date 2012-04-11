# hgversion.py - Version information for Mercurial
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re

try:
    # post 1.1.2
    from mercurial import util
    hgversion = util.version()
except AttributeError:
    # <= 1.1.2
    from mercurial import version
    hgversion = version.get_version()

def checkhgversion(v):
    """range check the Mercurial version"""
    reqver = ['1', '9']
    v = v.split('+')[0]
    if not v or v == 'unknown' or len(v) >= 12:
        # can't make any intelligent decisions about unknown or hashes
        return
    vers = re.split(r'\.|-', v)[:2]
    if vers == reqver or len(vers) < 2:
        return
    nextver = list(reqver)
    nextver[1] = str(int(reqver[1])+1)
    if vers == nextver:
        return
    return (('This version of TortoiseHg requires Mercurial '
                       'version %s.n to %s.n, but found %s') %
                       ('.'.join(reqver), '.'.join(nextver), v))
