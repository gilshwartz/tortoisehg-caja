# lfprompt.py - prompt to add large files
#
# Copyright 2011 Fog Creek Software
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os

from mercurial import match
from tortoisehg.hgqt import qtlib
from tortoisehg.hgqt.i18n import _

class LfilesPrompt(qtlib.CustomPrompt):
    def __init__(self, parent, files=None):
        qtlib.CustomPrompt.__init__(self, _('Confirm Add'),
                                    _('Some of the files that you have selected are of a size '
                                      'over 10 MB.  You may make more efficient use of disk space '
                                      'by adding these files as largefiles, which will store only the '
                                      'most recent revision of each file in your local repository, '
                                      'with older revisions available on the server.  Do you wish '
                                      'to add these files as largefiles?'), parent,
                                      (_('Add as &Largefiles'), _('Add as &Normal Files'), _('Cancel')),
                                      0, 2, files)

def promptForLfiles(parent, ui, repo, files):
    lfiles = []
    uself = 'largefiles' in repo.extensions()
    section = 'largefiles'
    try:
        minsize = int(ui.config(section, 'minsize', default='10'))
    except ValueError:
        minsize = 10
    patterns = ui.config(section, 'patterns', default=())
    if patterns:
        patterns = patterns.split(' ')
        matcher = match.match(repo.root, '', list(patterns))
    else:
        matcher = None
    for wfile in files:
        if matcher and matcher(wfile):
            # patterns have always precedence over size
            lfiles.append(wfile)
        else:
            # check for minimal size
            filesize = os.path.getsize(repo.wjoin(wfile))
            if filesize > minsize*1024*1024:
                lfiles.append(wfile)
    if lfiles:
        ret = LfilesPrompt(parent, files).run()
        if ret == 0:
            # add as largefiles/bfiles
            for lfile in lfiles:
                files.remove(lfile)
        elif ret == 1:
            # add as normal files
            lfiles = []
        elif ret == 2:
            return None
    return files, lfiles
