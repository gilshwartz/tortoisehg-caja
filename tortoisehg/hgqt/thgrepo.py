# thgrepo.py - TortoiseHg additions to key Mercurial classes
#
# Copyright 2010 George Marrows <george.marrows@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.
#
# See mercurial/extensions.py, comments to wrapfunction, for this approach
# to extending repositories and change contexts.

import os
import sys
import shutil
import tempfile
import re

from PyQt4.QtCore import *

from mercurial import hg, util, error, bundlerepo, extensions, filemerge, node
from mercurial import merge, subrepo
from mercurial import ui as uimod
from mercurial.util import propertycache

from tortoisehg.util import hglib, paths
from tortoisehg.util.patchctx import patchctx

_repocache = {}
_kbfregex = re.compile(r'^\.kbf/')
_lfregex = re.compile(r'^\.hglf/')

if 'THGDEBUG' in os.environ:
    def dbgoutput(*args):
        sys.stdout.write(' '.join([str(a) for a in args])+'\n')
else:
    def dbgoutput(*args):
        pass

def repository(_ui=None, path='', create=False, bundle=None):
    '''Returns a subclassed Mercurial repository to which new
    THG-specific methods have been added. The repository object
    is obtained using mercurial.hg.repository()'''
    if bundle:
        if _ui is None:
            _ui = uimod.ui()
        repo = bundlerepo.bundlerepository(_ui, path, bundle)
        repo.__class__ = _extendrepo(repo)
        repo._pyqtobj = ThgRepoWrapper(repo)
        return repo
    if create or path not in _repocache:
        if _ui is None:
            _ui = uimod.ui()
        try:
            repo = hg.repository(_ui, path, create)
            repo.__class__ = _extendrepo(repo)
            repo._pyqtobj = ThgRepoWrapper(repo)
            _repocache[path] = repo
            return repo
        except EnvironmentError:
            raise error.RepoError('Cannot open repository at %s' % path)
    if not os.path.exists(os.path.join(path, '.hg/')):
        del _repocache[path]
        # this error must be in local encoding
        raise error.RepoError('%s is not a valid repository' % path)
    return _repocache[path]

class _LockStillHeld(Exception):
    'Raised to abort status check due to lock existence'

class ThgRepoWrapper(QObject):

    configChanged = pyqtSignal()
    repositoryChanged = pyqtSignal()
    repositoryDestroyed = pyqtSignal()
    workingDirectoryChanged = pyqtSignal()
    workingBranchChanged = pyqtSignal()

    def __init__(self, repo):
        QObject.__init__(self)
        self.repo = repo
        self.busycount = 0
        repo.configChanged = self.configChanged
        repo.repositoryChanged = self.repositoryChanged
        repo.repositoryDestroyed = self.repositoryDestroyed
        repo.workingDirectoryChanged = self.workingDirectoryChanged
        repo.workingBranchChanged = self.workingBranchChanged
        self.recordState()

        monitorrepo = repo.ui.config('tortoisehg', 'monitorrepo', 'always')
        if isinstance(repo, bundlerepo.bundlerepository):
            dbgoutput('not watching F/S events for bundle repository')
        elif monitorrepo == 'localonly' and paths.netdrive_status(repo.path):
            dbgoutput('not watching F/S events for network drive')
        else:
            self.watcher = QFileSystemWatcher(self)
            self.watcher.addPath(hglib.tounicode(repo.path))
            self.watcher.addPath(hglib.tounicode(repo.path + '/store'))
            self.watcher.directoryChanged.connect(self.onDirChange)
            self.watcher.fileChanged.connect(self.onFileChange)
            self.addMissingPaths()

    @pyqtSlot(QString)
    def onDirChange(self, directory):
        'Catch any writes to .hg/ folder, most importantly lock files'
        self.pollStatus()
        self.addMissingPaths()

    @pyqtSlot(QString)
    def onFileChange(self, file):
        'Catch writes or deletions of files we are interested in'
        self.pollStatus()
        self.addMissingPaths()

    def addMissingPaths(self):
        'Add files to watcher that may have been added or replaced'
        existing = [f for f in self._getwatchedfiles() if os.path.isfile(f)]
        files = [unicode(f) for f in self.watcher.files()]
        for f in existing:
            if hglib.tounicode(f) not in files:
                dbgoutput('add file to watcher:', f)
                self.watcher.addPath(hglib.tounicode(f))
        for f in self.repo.uifiles()[1]:
            if f and os.path.exists(f) and hglib.tounicode(f) not in files:
                dbgoutput('add ui file to watcher:', f)
                self.watcher.addPath(hglib.tounicode(f))

    def pollStatus(self):
        if not os.path.exists(self.repo.path):
            dbgoutput('Repository destroyed', self.repo.root)
            self.repositoryDestroyed.emit()
            # disable watcher by removing all watched paths
            dirs = self.watcher.directories()
            if dirs:
                self.watcher.removePaths(dirs)
            files = self.watcher.files()
            if files:
                self.watcher.removePaths(files)
            if self.repo.root in _repocache:
                del _repocache[self.repo.root]
            return
        if self.locked():
            dbgoutput('locked, aborting')
            return
        try:
            if self._checkdirstate():
                dbgoutput('dirstate changed, exiting')
                return
            self._checkrepotime()
            self._checkuimtime()
        except _LockStillHeld:
            dbgoutput('lock still held - ignoring for now')

    def locked(self):
        if os.path.lexists(self.repo.join('wlock')):
            return True
        if os.path.lexists(self.repo.sjoin('lock')):
            return True
        return False

    def recordState(self):
        try:
            self._parentnodes = self._getrawparents()
            self._repomtime = self._getrepomtime()
            self._dirstatemtime = os.path.getmtime(self.repo.join('dirstate'))
            self._branchmtime = os.path.getmtime(self.repo.join('branch'))
            self._rawbranch = self.repo.opener('branch').read()
        except EnvironmentError, ValueError:
            self._dirstatemtime = None
            self._branchmtime = None
            self._rawbranch = None

    def _getrawparents(self):
        try:
            return self.repo.opener('dirstate').read(40)
        except EnvironmentError:
            return None

    def _getwatchedfiles(self):
        watchedfiles = [self.repo.sjoin('00changelog.i')]
        watchedfiles.append(self.repo.sjoin('phaseroots'))
        watchedfiles.append(self.repo.join('localtags'))
        watchedfiles.append(self.repo.join('bookmarks'))
        watchedfiles.append(self.repo.join('bookmarks.current'))
        if hasattr(self.repo, 'mq'):
            watchedfiles.append(self.repo.mq.path)
            watchedfiles.append(self.repo.mq.join('series'))
            watchedfiles.append(self.repo.mq.join('guards'))
            watchedfiles.append(self.repo.join('patches.queue'))
        return watchedfiles

    def _getrepomtime(self):
        'Return the last modification time for the repo'
        try:
            existing = [f for f in self._getwatchedfiles() if os.path.isfile(f)]
            mtime = [os.path.getmtime(wf) for wf in existing]
            if mtime:
                return max(mtime)
        except EnvironmentError:
            return None

    def _checkrepotime(self):
        'Check for new changelog entries, or MQ status changes'
        if self._repomtime < self._getrepomtime():
            dbgoutput('detected repository change')
            if self.locked():
                raise _LockStillHeld
            self.recordState()
            self.repo.thginvalidate()
            self.repositoryChanged.emit()

    def _checkdirstate(self):
        'Check for new dirstate mtime, then working parent changes'
        try:
            mtime = os.path.getmtime(self.repo.join('dirstate'))
        except EnvironmentError:
            return False
        if mtime <= self._dirstatemtime:
            return False
        changed = self._checkparentchanges() or self._checkbranch()
        self._dirstatemtime = mtime
        return changed

    def _checkparentchanges(self):
        nodes = self._getrawparents()
        if nodes != self._parentnodes:
            dbgoutput('dirstate change found')
            if self.locked():
                raise _LockStillHeld
            self.recordState()
            self.repo.thginvalidate()
            self.repositoryChanged.emit()
            return True
        return False

    def _checkbranch(self):
        try:
            mtime = os.path.getmtime(self.repo.join('branch'))
        except EnvironmentError:
            return False
        if mtime <= self._branchmtime:
            return False
        changed = self._checkbranchcontent()
        self._branchmtime = mtime
        return changed

    def _checkbranchcontent(self):
        try:
            newbranch = self.repo.opener('branch').read()
        except EnvironmentError:
            return False
        if newbranch != self._rawbranch:
            dbgoutput('branch time change')
            if self.locked():
                raise _LockStillHeld
            self._rawbranch = newbranch
            self.repo.thginvalidate()
            self.workingBranchChanged.emit()
            return True
        return False

    def _checkuimtime(self):
        'Check for modified config files, or a new .hg/hgrc file'
        try:
            oldmtime, files = self.repo.uifiles()
            mtime = [os.path.getmtime(f) for f in files if os.path.isfile(f)]
            if max(mtime) > oldmtime:
                dbgoutput('config change detected')
                self.repo.invalidateui()
                self.configChanged.emit()
        except (EnvironmentError, ValueError):
            pass

_uiprops = '''_uifiles _uimtime postpull tabwidth maxdiff
              deadbranches _exts _thghiddentags displayname summarylen
              shortname mergetools namedbranches'''.split()

# _bookmarkcurrent is a Mercurial property, we include it here to work
# around a bug in hg-1.8.  It should be removed when we drop support for
# Mercurial 1.8
_thgrepoprops = '''_thgmqpatchnames thgmqunappliedpatches
                   _branchheads _bookmarkcurrent'''.split()

def _extendrepo(repo):
    class thgrepository(repo.__class__):

        def __getitem__(self, changeid):
            '''Extends Mercurial's standard __getitem__() method to
            a) return a thgchangectx with additional methods
            b) return a patchctx if changeid is the name of an MQ
            unapplied patch
            c) return a patchctx if changeid is an absolute patch path
            '''

            # Mercurial's standard changectx() (rather, lookup())
            # implies that tags and branch names live in the same namespace.
            # This code throws patch names in the same namespace, but as
            # applied patches have a tag that matches their patch name this
            # seems safe.
            if changeid in self.thgmqunappliedpatches:
                q = self.mq # must have mq to pass the previous if
                return genPatchContext(self, q.join(changeid), rev=changeid)
            elif type(changeid) is str and '\0' not in changeid and \
                    os.path.isabs(changeid) and os.path.isfile(changeid):
                return genPatchContext(repo, changeid)

            changectx = super(thgrepository, self).__getitem__(changeid)
            changectx.__class__ = _extendchangectx(changectx)
            return changectx

        @propertycache
        def _thghiddentags(self):
            ht = self.ui.config('tortoisehg', 'hidetags', '')
            return [t.strip() for t in ht.split()]

        @propertycache
        def thgmqunappliedpatches(self):
            '''Returns a list of (patch name, patch path) of all self's
            unapplied MQ patches, in patch series order, first unapplied
            patch first.'''
            if not hasattr(self, 'mq'): return []

            q = self.mq
            applied = set([p.name for p in q.applied])

            return [pname for pname in q.series if not pname in applied]

        @propertycache
        def _thgmqpatchnames(self):
            '''Returns all tag names used by MQ patches. Returns []
            if MQ not in use.'''
            if not hasattr(self, 'mq'): return []

            self.mq.parseseries()
            return self.mq.series[:]

        @property
        def thgactivemqname(self):
            '''Currenty-active qqueue name (see hgext/mq.py:qqueue)'''
            if not hasattr(self, 'mq'):
                return
            n = os.path.basename(self.mq.path)
            if n.startswith('patches-'):
                return n[8:]
            else:
                return n

        @propertycache
        def _uifiles(self):
            cfg = self.ui._ucfg
            files = set()
            for line in cfg._source.values():
                f = line.rsplit(':', 1)[0]
                files.add(f)
            files.add(self.join('hgrc'))
            return files

        @propertycache
        def _uimtime(self):
            mtimes = [0] # zero will be taken if no config files
            for f in self._uifiles:
                try:
                    if os.path.exists(f):
                        mtimes.append(os.path.getmtime(f))
                except EnvironmentError:
                    pass
            return max(mtimes)

        @propertycache
        def _exts(self):
            lclexts = []
            allexts = [n for n,m in extensions.extensions()]
            for name, path in self.ui.configitems('extensions'):
                if name.startswith('hgext.'):
                    name = name[6:]
                if name in allexts:
                    lclexts.append(name)
            return lclexts

        @propertycache
        def postpull(self):
            pp = self.ui.config('tortoisehg', 'postpull')
            if pp in ('rebase', 'update', 'fetch'):
                return pp
            return 'none'

        @propertycache
        def tabwidth(self):
            tw = self.ui.config('tortoisehg', 'tabwidth')
            try:
                tw = int(tw)
                tw = min(tw, 16)
                return max(tw, 2)
            except (ValueError, TypeError):
                return 8

        @propertycache
        def maxdiff(self):
            maxdiff = self.ui.config('tortoisehg', 'maxdiff')
            try:
                maxdiff = int(maxdiff)
                if maxdiff < 1:
                    return sys.maxint
            except (ValueError, TypeError):
                maxdiff = 1024 # 1MB by default
            return maxdiff * 1024

        @propertycache
        def summarylen(self):
            slen = self.ui.config('tortoisehg', 'summarylen')
            try:
                slen = int(slen)
                if slen < 10:
                    return 80
            except (ValueError, TypeError):
                slen = 80
            return slen

        @propertycache
        def deadbranches(self):
            db = self.ui.config('tortoisehg', 'deadbranch', '')
            return [b.strip() for b in db.split(',')]

        @propertycache
        def displayname(self):
            'Display name is for window titles and similar'
            if self.ui.configbool('tortoisehg', 'fullpath'):
                name = self.root
            elif self.ui.config('web', 'name', False):
                name = self.ui.config('web', 'name')
            else:
                name = os.path.basename(self.root)
            return hglib.tounicode(name)

        @propertycache
        def shortname(self):
            'Short name is for tables, tabs, and sentences'
            if self.ui.config('web', 'name', False):
                name = self.ui.config('web', 'name')
            else:
                name = os.path.basename(self.root)
            return hglib.tounicode(name)

        @propertycache
        def mergetools(self):
            seen, installed = [], []
            for key, value in self.ui.configitems('merge-tools'):
                t = key.split('.')[0]
                if t not in seen:
                    seen.append(t)
                    if filemerge._findtool(self.ui, t):
                        installed.append(t)
            return installed

        @propertycache
        def namedbranches(self):
            allbranches = self.branchtags()
            openbrnodes = []
            for br in allbranches.iterkeys():
                openbrnodes.extend(self.branchheads(br, closed=False))
            dead = self.deadbranches
            return sorted(br for br, n in allbranches.iteritems()
                          if n in openbrnodes and br not in dead)

        @propertycache
        def _branchheads(self):
            heads = []
            for branchname, nodes in self.branchmap().iteritems():
                heads.extend(nodes)
            return heads

        def uifiles(self):
            'Returns latest mtime and complete list of config files'
            return self._uimtime, self._uifiles

        def extensions(self):
            'Returns list of extensions enabled in this repository'
            return self._exts

        def thgmqtag(self, tag):
            'Returns true if `tag` marks an applied MQ patch'
            return tag in self._thgmqpatchnames

        def getcurrentqqueue(self):
            'Returns the name of the current MQ queue'
            if 'mq' not in self._exts:
                return None
            cur = os.path.basename(self.mq.path)
            if cur.startswith('patches-'):
                cur = cur[8:]
            return cur

        def thgshelves(self):
            self.shelfdir = sdir = self.join('shelves')
            if os.path.isdir(sdir):
                def getModificationTime(x):
                    try:
                        return os.path.getmtime(os.path.join(sdir, x))
                    except EnvironmentError:
                        return 0
                shelves = sorted(os.listdir(sdir),
                    key=getModificationTime, reverse=True)
                return [s for s in shelves if \
                           os.path.isfile(os.path.join(self.shelfdir, s))]
            return []

        def makeshelf(self, patch):
            if not os.path.exists(self.shelfdir):
                os.mkdir(self.shelfdir)
            f = open(os.path.join(self.shelfdir, patch), "wb")
            f.close()

        def thginvalidate(self):
            'Should be called when mtime of repo store/dirstate are changed'
            self.dirstate.invalidate()
            if not isinstance(repo, bundlerepo.bundlerepository):
                self.invalidate()
            # mq.queue.invalidate does not handle queue changes, so force
            # the queue object to be rebuilt
            if 'mq' in self.__dict__:
                delattr(self, 'mq')
            for a in _thgrepoprops + _uiprops:
                if a in self.__dict__:
                    delattr(self, a)

        def invalidateui(self):
            'Should be called when mtime of ui files are changed'
            self.ui = uimod.ui()
            self.ui.readconfig(self.join('hgrc'))
            for a in _uiprops:
                if a in self.__dict__:
                    delattr(self, a)

        def incrementBusyCount(self):
            'A GUI widget is starting a transaction'
            self._pyqtobj.busycount += 1

        def decrementBusyCount(self):
            'A GUI widget has finished a transaction'
            self._pyqtobj.busycount -= 1
            if self._pyqtobj.busycount == 0:
                self._pyqtobj.pollStatus()
            else:
                # A lot of logic will depend on invalidation happening
                # within the context of this call.  Signals will not be
                # emitted till later, but we at least invalidate cached
                # data in the repository
                self.thginvalidate()

        def thgbackup(self, path):
            'Make a backup of the given file in the repository "trashcan"'
            # The backup name will be the same as the orginal file plus '.bak'
            trashcan = self.join('Trashcan')
            if not os.path.isdir(trashcan):
                os.mkdir(trashcan)
            if not os.path.exists(path):
                return
            name = os.path.basename(path)
            root, ext = os.path.splitext(name)
            dest = tempfile.mktemp(ext+'.bak', root+'_', trashcan)
            shutil.copyfile(path, dest)

        def isStandin(self, path):
            if 'largefiles' in self.extensions():
                if _lfregex.match(path):
                    return True
            if 'largefiles' in self.extensions() or 'kbfiles' in self.extensions():
                if _kbfregex.match(path):
                    return True
            return False

        def removeStandin(self, path):
            if 'largefiles' in self.extensions():
                path = _lfregex.sub('', path)
            if 'largefiles' in self.extensions() or 'kbfiles' in self.extensions():
                path = _kbfregex.sub('', path)
            return path
        
        def bfStandin(self, path):
            return '.kbf/' + path

        def lfStandin(self, path):
            return '.hglf/' + path
        
    return thgrepository

_maxchangectxclscache = 10
_changectxclscache = {}  # parentcls: extendedcls

def _extendchangectx(changectx):
    # cache extended changectx class, since we may create bunch of instances
    parentcls = changectx.__class__
    try:
        return _changectxclscache[parentcls]
    except KeyError:
        pass

    # in case each changectx instance is wrapped by some extension, there's
    # limit on cache size. it may be possible to use weakref.WeakKeyDictionary
    # on Python 2.5 or later.
    if len(_changectxclscache) >= _maxchangectxclscache:
        _changectxclscache.clear()
    _changectxclscache[parentcls] = cls = _createchangectxcls(parentcls)
    return cls

def _createchangectxcls(parentcls):
    class thgchangectx(parentcls):
        def sub(self, path):
            srepo = super(thgchangectx, self).sub(path)
            if isinstance(srepo, subrepo.hgsubrepo):
                srepo._repo.__class__ = _extendrepo(srepo._repo)
            return srepo

        def thgtags(self):
            '''Returns all unhidden tags for self'''
            htlist = self._repo._thghiddentags
            return [tag for tag in self.tags() if tag not in htlist]

        def thgwdparent(self):
            '''True if self is a parent of the working directory'''
            return self.rev() in [ctx.rev() for ctx in self._repo.parents()]

        def _thgmqpatchtags(self):
            '''Returns the set of self's tags which are MQ patch names'''
            mytags = set(self.tags())
            patchtags = self._repo._thgmqpatchnames
            result = mytags.intersection(patchtags)
            assert len(result) <= 1, "thgmqpatchname: rev has more than one tag in series"
            return result

        def thgmqappliedpatch(self):
            '''True if self is an MQ applied patch'''
            return self.rev() is not None and bool(self._thgmqpatchtags())

        def thgmqunappliedpatch(self):
            return False

        def thgid(self):
            return self._node

        def thgmqpatchname(self):
            '''Return self's MQ patch name. AssertionError if self not an MQ patch'''
            patchtags = self._thgmqpatchtags()
            assert len(patchtags) == 1, "thgmqpatchname: called on non-mq patch"
            return list(patchtags)[0]

        def thgbranchhead(self):
            '''True if self is a branch head'''
            return self.node() in self._repo._branchheads

        def changesToParent(self, whichparent):
            parent = self.parents()[whichparent]
            return self._repo.status(parent.node(), self.node())[:3]

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
        
        def hasStandin(self, file):
            if 'largefiles' in self._repo.extensions():
                if self._repo.lfStandin(file) in self.manifest():
                    return True
            elif 'largefiles' in self._repo.extensions() or 'kbfiles' in self._repo.extensions():
                if self._repo.bfStandin(file) in self.manifest():
                    return True
            return False

        def isStandin(self, path):
            return self._repo.isStandin(path)
        
        def removeStandin(self, path):
            return self._repo.removeStandin(path)
        
        def findStandin(self, file):
            if 'largefiles' in self._repo.extensions():
                if self._repo.lfStandin(file) in self.manifest():
                    return self._repo.lfStandin(file)
            return self._repo.bfStandin(file)

    return thgchangectx

_pctxcache = {}
def genPatchContext(repo, patchpath, rev=None):
    global _pctxcache
    try:
        if os.path.exists(patchpath) and patchpath in _pctxcache:
            cachedctx = _pctxcache[patchpath]
            if cachedctx._mtime == os.path.getmtime(patchpath) and \
               cachedctx._fsize == os.path.getsize(patchpath):
                return cachedctx
    except EnvironmentError:
        pass
    # create a new context object
    ctx = patchctx(patchpath, repo, rev=rev)
    _pctxcache[patchpath] = ctx
    return ctx

def recursiveMergeStatus(repo):
    ms = merge.mergestate(repo)
    for wfile in ms:
        yield repo.root, wfile, ms[wfile]
    try:
        wctx = repo[None]
        for s in wctx.substate:
            sub = wctx.sub(s)
            if isinstance(sub, subrepo.hgsubrepo):
                for root, file, status in recursiveMergeStatus(sub._repo):
                    yield root, file, status
    except (EnvironmentError, error.Abort, error.RepoError):
        pass

def relatedRepositories(repoid):
    'Yields root paths for local related repositories'
    from tortoisehg.hgqt import reporegistry, repotreemodel
    f = QFile(reporegistry.settingsfilename())
    f.open(QIODevice.ReadOnly)
    try:
        for e in repotreemodel.iterRepoItemFromXml(f):
            if e.basenode() == repoid:
                yield e.rootpath(), e.shortname()
    except:
        f.close()
        raise
    else:
        f.close()

def isBfStandin(path):
    return _kbfregex.match(path)

def isLfStandin(path):
    return _lfregex.match(path)
