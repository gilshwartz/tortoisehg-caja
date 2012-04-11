# Copyright (c) 2009-2010 LOGILAB S.A. (Paris, FRANCE).
# http://www.logilab.fr/ -- mailto:contact@logilab.fr
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free Software
# Foundation; either version 2 of the License, or (at your option) any later
# version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

from tortoisehg.util import hglib, patchctx

from tortoisehg.hgqt.qtlib import geticon, getoverlaidicon

from PyQt4.QtCore import *
from PyQt4.QtGui import *

nullvariant = QVariant()

def getSubrepoIcoDict():
    'Return a dictionary mapping each subrepo type to the corresponding icon'
    _subrepoType2IcoMap = {
      'hg': 'hg',
      'git': 'thg-git-subrepo',
      'svn': 'thg-svn-subrepo',
      'hgsubversion': 'thg-svn-subrepo',
      'empty': 'hg'
    }
    icOverlay = geticon('thg-subrepo')
    subrepoIcoDict = {}
    for stype in _subrepoType2IcoMap:
        ic = geticon(_subrepoType2IcoMap[stype])
        ic = getoverlaidicon(ic, icOverlay)
        subrepoIcoDict[stype] = ic
    return subrepoIcoDict

class HgFileListModel(QAbstractTableModel):
    """
    Model used for listing (modified) files of a given Hg revision
    """
    showMessage = pyqtSignal(QString)

    def __init__(self, parent):
        QAbstractTableModel.__init__(self, parent)
        self._boldfont = parent.font()
        self._boldfont.setBold(True)
        self._ctx = None
        self._files = []
        self._filesdict = {}
        self._fulllist = False
        self._subrepoIcoDict = getSubrepoIcoDict()

    @pyqtSlot(bool)
    def toggleFullFileList(self, value):
        self._fulllist = value
        self.loadFiles()
        self.layoutChanged.emit()

    def __len__(self):
        return len(self._files)

    def rowCount(self, parent=None):
        return len(self)

    def columnCount(self, parent=None):
        return 1

    def file(self, row):
        return self._files[row]['path']

    def setContext(self, ctx):
        reload = False
        if not self._ctx:
            reload = True
        elif self._ctx.rev() is None:
            reload = True
        elif ctx.thgid() != self._ctx.thgid():
            reload = True
        if reload:
            self._ctx = ctx
            self.loadFiles()
            self.layoutChanged.emit()

    def fileFromIndex(self, index):
        if not index.isValid() or index.row()>=len(self) or not self._ctx:
            return None
        row = index.row()
        return self._files[row]['path']

    def dataFromIndex(self, index):
        if not index.isValid() or index.row()>=len(self) or not self._ctx:
            return None
        row = index.row()
        return self._files[row]

    def indexFromFile(self, filename):
        if filename in self._filesdict:
            row = self._files.index(self._filesdict[filename])
            return self.index(row, 0)
        return QModelIndex()

    def _buildDesc(self, parent):
        files = []
        ctxfiles = self._ctx.files()
        modified, added, removed = self._ctx.changesToParent(parent)
        ismerge = bool(self._ctx.p2())

        # Add the list of modified subrepos to the top of the list
        if not isinstance(self._ctx, patchctx.patchctx):
            if ".hgsubstate" in ctxfiles or ".hgsub" in ctxfiles:
                from mercurial import subrepo
                # Add the list of modified subrepos
                for s, sd in self._ctx.substate.items():
                    srev = self._ctx.substate.get(s, subrepo.nullstate)[1]
                    stype = self._ctx.substate.get(s, subrepo.nullstate)[2]
                    sp1rev = self._ctx.p1().substate.get(s, subrepo.nullstate)[1]
                    sp2rev = ''
                    if ismerge:
                        sp2rev = self._ctx.p2().substate.get(s, subrepo.nullstate)[1]
                    if srev != sp1rev or (sp2rev != '' and srev != sp2rev):
                        wasmerged = ismerge and s in ctxfiles
                        files.append({'path': s, 'status': 'S', 'parent': parent,
                          'wasmerged': wasmerged, 'stype': stype})
                # Add the list of missing subrepos
                subreposet = set(self._ctx.substate.keys())
                subrepoparent1set = set(self._ctx.p1().substate.keys())
                missingsubreposet = subrepoparent1set.difference(subreposet)
                for s in missingsubreposet:
                    wasmerged = ismerge and s in ctxfiles
                    stype = self._ctx.p1().substate.get(s, subrepo.nullstate)[2]
                    files.append({'path': s, 'status': 'S', 'parent': parent,
                      'wasmerged': wasmerged, 'stype': stype})

        if self._fulllist and ismerge:
            func = lambda x: True
        else:
            func = lambda x: x in ctxfiles
        for lst, flag in ((added, 'A'), (modified, 'M'), (removed, 'R')):
            for f in filter(func, lst):
                wasmerged = ismerge and f in ctxfiles
                files.append({'path': f, 'status': flag, 'parent': parent,
                              'wasmerged': wasmerged})
        return files

    def loadFiles(self):
        self._files = []
        try:
            self._files = self._buildDesc(0)
            if bool(self._ctx.p2()):
                _paths = [x['path'] for x in self._files]
                _files = self._buildDesc(1)
                self._files += [x for x in _files if x['path'] not in _paths]
        except EnvironmentError, e:
            self.showMessage.emit(hglib.tounicode(str(e)))
        self._filesdict = dict([(f['path'], f) for f in self._files])

    def data(self, index, role):
        if not index.isValid() or index.row()>len(self) or not self._ctx:
            return nullvariant
        if index.column() != 0:
            return nullvariant

        row = index.row()
        column = index.column()

        current_file_desc = self._files[row]
        current_file = current_file_desc['path']

        if role in (Qt.DisplayRole, Qt.ToolTipRole):
            return QVariant(hglib.tounicode(current_file))
        elif role == Qt.DecorationRole:
            if self._fulllist and bool(self._ctx.p2()):
                if current_file_desc['wasmerged']:
                    icn = geticon('thg-file-merged')
                elif current_file_desc['parent'] == 0:
                    icn = geticon('thg-file-p0')
                elif current_file_desc['parent'] == 1:
                    icn = geticon('thg-file-p1')
                return QVariant(icn.pixmap(20,20))
            elif current_file_desc['status'] == 'A':
                return QVariant(geticon('fileadd'))
            elif current_file_desc['status'] == 'R':
                return QVariant(geticon('filedelete'))
            elif current_file_desc['status'] == 'S':
                stype = current_file_desc.get('stype', 'hg')
                return QVariant(self._subrepoIcoDict[stype])
            #else:
            #    return QVariant(geticon('filemodify'))
        elif role == Qt.FontRole:
            if current_file_desc['wasmerged']:
                return QVariant(self._boldfont)
        else:
            return nullvariant
