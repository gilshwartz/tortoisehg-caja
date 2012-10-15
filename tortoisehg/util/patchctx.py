# patchctx.py - TortoiseHg patch context class
#
# Copyright 2011 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import sys
import shlex
import binascii
import cStringIO

from mercurial import patch, util, error
from mercurial import node
from mercurial.util import propertycache
from hgext import mq, record

from tortoisehg.util import hglib

class patchctx(object):
    _parseErrorFileName = '*ParseError*'

    def __init__(self, patchpath, repo, pf=None, rev=None):
        """ Read patch context from file
        :param pf: currently ignored
            The provided handle is used to read the patch and
            the patchpath contains the name of the patch.
            The handle is NOT closed.
        """
        self._path = patchpath
        self._patchname = os.path.basename(patchpath)
        self._repo = repo
        self._rev = rev or 'patch'
        self._status = [[], [], []]
        self._fileorder = []
        self._user = ''
        self._desc = ''
        self._branch = ''
        self._node = node.nullid
        self._identity = node.nullid
        self._mtime = None
        self._fsize = 0
        self._parseerror = None
        self._phase = 'draft'

        try:
            self._mtime = os.path.getmtime(patchpath)
            self._fsize = os.path.getsize(patchpath)
            ph = mq.patchheader(self._path)
            self._ph = ph
            hash = util.sha1(self._path)
            hash.update(str(self._mtime))
            self._identity = hash.digest()
        except EnvironmentError:
            self._date = util.makedate()
            return

        try:
            self._branch = ph.branch or ''
            self._node = binascii.unhexlify(ph.nodeid)
            if self._repo.ui.configbool('mq', 'secret'):
                self._phase = 'secret'
        except TypeError:
            pass
        except AttributeError:
            # hacks to try to deal with older versions of mq.py
            self._branch = ''
            ph.diffstartline = len(ph.comments)
            if ph.message:
                ph.diffstartline += 1
        except error.ConfigError:
            pass

        self._user = ph.user or ''
        self._desc = ph.message and '\n'.join(ph.message).strip() or ''
        try:
            self._date = ph.date and util.parsedate(ph.date) or util.makedate()
        except error.Abort:
            self._date = util.makedate()

    def invalidate(self):
        # ensure the patch contents are re-read
        self._mtime = 0

    @property
    def substate(self):
        return {}  # unapplied patch won't include .hgsubstate

    def __contains__(self, key):
        return key in self._files

    def __str__(self):      return node.short(self.node())
    def node(self):         return self._node
    def files(self):        return self._files.keys()
    def rev(self):          return self._rev
    def hex(self):          return node.hex(self.node())
    def user(self):         return self._user
    def date(self):         return self._date
    def description(self):  return self._desc
    def branch(self):       return self._branch
    def parents(self):      return ()
    def tags(self):         return ()
    def bookmarks(self):    return ()
    def children(self):     return ()
    def extra(self):        return {}
    def p1(self):           return None
    def p2(self):           return None

    def flags(self, wfile):
        if wfile == self._parseErrorFileName:
            return ''
        if wfile in self._files:
            for gp in patch.readgitpatch(self._files[wfile][0].header):
                if gp.mode:
                    islink, isexec = gp.mode
                    if islink:
                        return 'l'
                    elif wfile in self._status[1]:
                        # Do not report exec mode change if file is added
                        return ''
                    elif isexec:
                        return 'x'
                    else:
                        # techincally, this case could mean the file has had its
                        # exec bit cleared OR its symlink state removed
                        # TODO: change readgitpatch() to differentiate
                        return '-'
        return ''

    # TortoiseHg methods
    def thgtags(self):              return []
    def thgwdparent(self):          return False
    def thgmqappliedpatch(self):    return False
    def thgmqpatchname(self):       return self._patchname
    def thgbranchhead(self):        return False
    def thgmqunappliedpatch(self):  return True
    def thgid(self):                return self._identity

    # largefiles/kbfiles methods
    def hasStandin(self, file):     return False
    def isStandin(self, path):      return False
    def removeStandin(self, path):  return path

    def longsummary(self):
        summary = hglib.tounicode(self.description())
        if self._repo.ui.configbool('tortoisehg', 'longsummary'):
            limit = 80
            lines = summary.splitlines()
            if lines:
                summary = lines.pop(0)
                while len(summary) < limit and lines:
                    summary += u'  ' + lines.pop(0)
                summary = summary[0:limit]
            else:
                summary = ''
        else:
            lines = summary.splitlines()
            summary = lines and lines[0] or ''

            if summary and len(lines) > 1:
                summary += u' \u2026' # ellipsis ...

        return summary

    def changesToParent(self, whichparent):
        'called by filelistmodel to get list of files'
        if whichparent == 0 and self._files:
            return self._status
        else:
            return [], [], []

    def thgmqpatchdata(self, wfile):
        'called by fileview to get diff data'
        if wfile == self._parseErrorFileName:
            return '\n\n\nErrors while parsing patch:\n'+str(self._parseerror)
        if wfile in self._files:
            buf = cStringIO.StringIO()
            for chunk in self._files[wfile]:
                chunk.write(buf)
            return buf.getvalue()
        return ''

    def phasestr(self):
        return self._phase

    @propertycache
    def _files(self):
        if not hasattr(self, '_ph') or not self._ph.haspatch:
            return {}

        M, A, R = 0, 1, 2
        def get_path(a, b):
            type = (a == '/dev/null') and A or M
            type = (b == '/dev/null') and R or type
            rawpath = (b != '/dev/null') and b or a
            if not (rawpath.startswith('a/') or rawpath.startswith('b/')):
                return type, rawpath
            return type, rawpath.split('/', 1)[-1]

        files = {}
        pf = open(self._path, 'rb')
        try:
            try:
                # consume comments and headers
                for i in range(self._ph.diffstartline):
                    pf.readline()
                for chunk in record.parsepatch(pf):
                    if not isinstance(chunk, record.header):
                        continue
                    top = patch.parsefilename(chunk.header[-2])
                    bot = patch.parsefilename(chunk.header[-1])
                    type, path = get_path(top, bot)
                    if path not in chunk.files():
                        type, path = 0, chunk.files()[-1]
                    if path not in files:
                        self._status[type].append(path)
                        files[path] = [chunk]
                        self._fileorder.append(path)
                    files[path].extend(chunk.hunks)
            except (patch.PatchError, AttributeError), e:
                self._status[2].append(self._parseErrorFileName)
                files[self._parseErrorFileName] = []
                self._parseerror = e
                if 'THGDEBUG' in os.environ:
                    print e
        finally:
            pf.close()
        return files
