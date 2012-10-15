# manifestmodel.py - Model for TortoiseHg manifest view
#
# Copyright (C) 2009-2010 LOGILAB S.A. <http://www.logilab.fr/>
# Copyright (C) 2010 Yuya Nishihara <yuya@tcha.org>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.

import os, itertools, fnmatch

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import util
from mercurial.subrepo import hgsubrepo
from tortoisehg.util import hglib
from tortoisehg.hgqt import qtlib, status, visdiff

class ManifestModel(QAbstractItemModel):
    """
    Qt model to display a hg manifest, ie. the tree of files at a
    given revision. To be used with a QTreeView.
    """

    StatusRole = Qt.UserRole + 1
    """Role for file change status"""

    _fileiconprovider = QFileIconProvider()
    _icons = {}

    def __init__(self, repo, rev=None, namefilter=None, statusfilter='MASC',
                 parent=None):
        QAbstractItemModel.__init__(self, parent)

        self._diricon = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        self._fileicon = QApplication.style().standardIcon(QStyle.SP_FileIcon)
        self._repo = repo
        self._rev = rev
        self._subinfo = {}

        self._namefilter = namefilter
        assert util.all(c in 'MARSC' for c in statusfilter)
        self._statusfilter = statusfilter

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return

        if role == Qt.DecorationRole:
            return self.fileIcon(index)
        if role == self.StatusRole:
            return self.fileStatus(index)

        e = index.internalPointer()
        if role in (Qt.DisplayRole, Qt.EditRole):
            return e.name

    def filePath(self, index):
        """Return path at the given index [unicode]"""
        if not index.isValid():
            return ''

        return index.internalPointer().path

    def fileSubrepoCtx(self, index):
        """Return the subrepo context of the specified index"""
        path = self.filePath(index)
        return self.fileSubrepoCtxFromPath(path)

    def fileSubrepoCtxFromPath(self, path):
        """Return the subrepo context of the specified file"""
        if not path:
            return None, path
        for subpath in sorted(self._subinfo.keys())[::-1]:
            if path.startswith(subpath + '/'):
                return self._subinfo[subpath]['ctx'], path[len(subpath)+1:]
        return None, path

    def subrepoType(self, index):
        """Return the subrepo type the specified index"""
        path = self.filePath(index)
        return self.subrepoTypeFromPath(path)

    def subrepoTypeFromPath(self, path):
        """Return the subrepo type of the specified subrepo"""
        if not path:
            return None
        try:
            substate = self._subinfo[path]
            return substate['substate'][2]
        except:
            return None

    def fileIcon(self, index):
        if not index.isValid():
            if self.isDir(index):
                return self._diricon
            else:
                return self._fileicon
        e = index.internalPointer()
        ic = e.icon
        if not ic:
            if self.isDir(index):
                ic = self._diricon
            else:
                ext = os.path.splitext(e.path)[1]
                if not ext:
                    ic = self._fileicon
                else:
                    ic = self._icons.get(ext, None)
                    if not ic:
                        ic = self._fileiconprovider.icon(QFileInfo(self._wjoin(e.path)))
                        if not ic.availableSizes():
                            ic = self._fileicon
                        self._icons[ext] = ic
            e.seticon(ic)

        if not e.status:
            return ic
        st = status.statusTypes[e.status]
        if st.icon:
            icOverlay = qtlib.geticon(st.icon[:-4])
            if e.status == 'S':
                _subrepoType2IcoMap = {
                  'hg': 'hg',
                  'git': 'thg-git-subrepo',
                  'svn': 'thg-svn-subrepo',
                }
                stype = self.subrepoType(index)
                if stype in _subrepoType2IcoMap:
                    ic = qtlib.geticon(_subrepoType2IcoMap[stype])
            ic = qtlib.getoverlaidicon(ic, icOverlay)
        return ic

    def fileStatus(self, index):
        """Return the change status of the specified file"""
        if not index.isValid():
            return
        e = index.internalPointer()
        return e.status

    def isDir(self, index):
        if not index.isValid():
            return True  # root entry must be a directory
        e = index.internalPointer()
        if e.status == 'S':
            # Consider subrepos as dirs as well
            return True
        else:
            return len(e) != 0

    def mimeData(self, indexes):
        def preparefiles():
            files = [self.filePath(i) for i in indexes if i.isValid()]
            if self._rev is not None:
                base, _fns = visdiff.snapshot(self._repo, files,
                                              self._repo[self._rev])
            else:  # working copy
                base = self._repo.root
            return iter(os.path.join(base, e) for e in files)

        m = QMimeData()
        m.setUrls([QUrl.fromLocalFile(e) for e in preparefiles()])
        return m

    def mimeTypes(self):
        return ['text/uri-list']

    def flags(self, index):
        if not index.isValid():
            return Qt.ItemIsEnabled
        f = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not (self.isDir(index) or self.fileStatus(index) == 'R'):
            f |= Qt.ItemIsDragEnabled
        return f

    def index(self, row, column, parent=QModelIndex()):
        try:
            return self.createIndex(row, column,
                                    self._parententry(parent).at(row))
        except IndexError:
            return QModelIndex()

    def indexFromPath(self, path, column=0):
        """Return index for the specified path if found [unicode]

        If not found, returns invalid index.
        """
        if not path:
            return QModelIndex()

        e = self._rootentry
        paths = path and unicode(path).split('/') or []
        try:
            for p in paths:
                e = e[p]
        except KeyError:
            return QModelIndex()

        return self.createIndex(e.parent.index(e.name), column, e)

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()

        e = index.internalPointer()
        if e.path:
            return self.indexFromPath(e.parent.path, index.column())
        else:
            return QModelIndex()

    def _parententry(self, parent):
        if parent.isValid():
            return parent.internalPointer()
        else:
            return self._rootentry

    def rowCount(self, parent=QModelIndex()):
        return len(self._parententry(parent))

    def columnCount(self, parent=QModelIndex()):
        return 1

    @pyqtSlot(unicode)
    def setNameFilter(self, pattern):
        """Filter file name by partial match of glob pattern"""
        pattern = pattern and unicode(pattern) or None
        if self._namefilter == pattern:
            return
        self._namefilter = pattern
        self._rebuildrootentry()

    @property
    def nameFilter(self):
        """Return the current name filter if available; otherwise None"""
        return self._namefilter

    @pyqtSlot(str)
    def setStatusFilter(self, status):
        """Filter file tree by change status 'MARSC'"""
        status = str(status)
        assert util.all(c in 'MARSC' for c in status)
        if self._statusfilter == status:
            return  # for performance reason
        self._statusfilter = status
        self._rebuildrootentry()

    @property
    def statusFilter(self):
        """Return the current status filter"""
        return self._statusfilter

    def _wjoin(self, path):
        return os.path.join(hglib.tounicode(self._repo.root), unicode(path))

    @property
    def _rootentry(self):
        try:
            return self.__rootentry
        except (AttributeError, TypeError):
            self.__rootentry = self._newrootentry()
            return self.__rootentry

    def _rebuildrootentry(self):
        """Rebuild the tree of files and directories"""
        roote = self._newrootentry()

        self.layoutAboutToBeChanged.emit()
        try:
            oldindexmap = [(i, self.filePath(i))
                           for i in self.persistentIndexList()]
            self.__rootentry = roote
            for oi, path in oldindexmap:
                self.changePersistentIndex(oi, self.indexFromPath(path))
        finally:
            self.layoutChanged.emit()

    def _newrootentry(self):
        """Create the tree of files and directories and return its root"""

        def pathinstatus(path, status, uncleanpaths):
            """Test path is included by the status filter"""
            if util.any(c in self._statusfilter and path in e
                        for c, e in status.iteritems()):
                return True
            if 'C' in self._statusfilter and path not in uncleanpaths:
                return True
            return False

        def getctxtreeinfo(ctx):
            """
            Get the context information that is relevant to populating the tree
            """
            status = dict(zip(('M', 'A', 'R'),
                      (set(a) for a in self._repo.status(ctx.parents()[0],
                                                             ctx)[:3])))
            uncleanpaths = status['M'] | status['A'] | status['R']
            files = itertools.chain(ctx.manifest(), status['R'])
            return status, uncleanpaths, files

        def addfilestotree(treeroot, files, status, uncleanpaths):
            """Add files to the tree according to their state"""
            if self._namefilter:
                files = fnmatch.filter(files, '*%s*' % self._namefilter)
            for path in files:
                if not pathinstatus(path, status, uncleanpaths):
                    continue

                origpath = path
                path = self._repo.removeStandin(path)
                
                e = treeroot
                for p in hglib.tounicode(path).split('/'):
                    if not p in e:
                        e.addchild(p)
                    e = e[p]

                for st, filesofst in status.iteritems():
                    if origpath in filesofst:
                        e.setstatus(st)
                        break
                else:
                    e.setstatus('C')

        # Add subrepos to the tree
        def addrepocontentstotree(roote, ctx, toproot=''):
            subpaths = ctx.substate.keys()
            for path in subpaths:
                if not 'S' in self._statusfilter:
                    break
                e = roote
                pathelements = hglib.tounicode(path).split('/')
                for p in pathelements[:-1]:
                    if not p in e:
                        e.addchild(p)
                    e = e[p]

                p = pathelements[-1]
                if not p in e:
                    e.addchild(p)
                e = e[p]
                e.setstatus('S')

                # If the subrepo exists in the working directory
                # and it is a mercurial subrepo,
                # add the files that it contains to the tree as well, according
                # to the status filter
                abspath = os.path.join(ctx._repo.root, path)
                if os.path.isdir(abspath):
                    # Add subrepo files to the tree
                    substate = ctx.substate[path]
                    # Add the subrepo info to the _subinfo dictionary:
                    # The value is the subrepo context, while the key is
                    # the path of the subrepo relative to the topmost repo
                    if toproot:
                        # Note that we cannot use os.path.join() because we
                        # need path items to be separated by "/"
                        toprelpath = '/'.join([toproot, path])
                    else:
                        toprelpath = path
                    toprelpath = util.pconvert(toprelpath)
                    self._subinfo[toprelpath] = \
                        {'substate': substate, 'ctx': None}
                    srev = substate[1]
                    sub = ctx.sub(path)
                    if srev and isinstance(sub, hgsubrepo):
                        srepo = sub._repo
                        if srev in srepo:
                            sctx = srepo[srev]

                            self._subinfo[toprelpath]['ctx'] = sctx

                            # Add the subrepo contents to the tree
                            e = addrepocontentstotree(e, sctx, toprelpath)

            # Add regular files to the tree
            status, uncleanpaths, files = getctxtreeinfo(ctx)

            addfilestotree(roote, files, status, uncleanpaths)
            return roote

        # Clear the _subinfo
        self._subinfo = {}
        roote = _Entry()
        ctx = self._repo[self._rev]

        addrepocontentstotree(roote, ctx)
        roote.sort()
        return roote

class _Entry(object):
    """Each file or directory"""
    def __init__(self, name='', parent=None):
        self._name = name
        self._parent = parent
        self._status = None
        self._icon = None
        self._child = {}
        self._nameindex = []

    @property
    def parent(self):
        return self._parent

    @property
    def path(self):
        if self.parent is None or not self.parent.name:
            return self.name
        else:
            return self.parent.path + '/' + self.name

    @property
    def name(self):
        return self._name

    @property
    def icon(self):
        return self._icon

    def seticon(self, icon):
        self._icon = icon

    @property
    def status(self):
        """Return file change status"""
        return self._status

    def setstatus(self, status):
        assert status in 'MARSC'
        self._status = status

    def __len__(self):
        return len(self._child)

    def __getitem__(self, name):
        return self._child[name]

    def addchild(self, name):
        if name not in self._child:
            self._nameindex.append(name)
        self._child[name] = self.__class__(name, parent=self)

    def __contains__(self, item):
        return item in self._child

    def at(self, index):
        return self._child[self._nameindex[index]]

    def index(self, name):
        return self._nameindex.index(name)

    def sort(self, reverse=False):
        """Sort the entries recursively; directories first"""
        for e in self._child.itervalues():
            e.sort(reverse=reverse)
        self._nameindex.sort(
            key=lambda s: '%s%s' % (self[s] and 'D' or 'F', s),
            reverse=reverse)

class ManifestCompleter(QCompleter):
    """QCompleter for ManifestModel"""

    def splitPath(self, path):
        """
        >>> c = ManifestCompleter()
        >>> c.splitPath(QString('foo/bar'))
        [u'foo', u'bar']

        trailing slash appends extra '', so that QCompleter can descend to
        next level:
        >>> c.splitPath(QString('foo/'))
        [u'foo', u'']
        """
        return unicode(path).split('/')

    def pathFromIndex(self, index):
        if not index.isValid():
            return ''
        m = self.model()
        if not m:
            return ''
        return m.filePath(index)
