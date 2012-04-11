# repotreemodel.py - model for the reporegistry
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib

from repotreeitem import undumpObject, AllRepoGroupItem, RepoGroupItem
from repotreeitem import RepoItem, RepoTreeItem, SubrepoItem

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os


extractXmlElementName = 'reporegextract'
reporegistryXmlElementName = 'reporegistry'

repoRegMimeType = 'application/thg-reporegistry'
repoExternalMimeType = 'text/uri-list'


def writeXml(target, item, rootElementName):
    xw = QXmlStreamWriter(target)
    xw.setAutoFormatting(True)
    xw.setAutoFormattingIndent(2)
    xw.writeStartDocument()
    xw.writeStartElement(rootElementName)
    item.dumpObject(xw)
    xw.writeEndElement()
    xw.writeEndDocument()

def readXml(source, rootElementName):
    itemread = None
    xr = QXmlStreamReader(source)
    if xr.readNextStartElement():
        ele = str(xr.name().toString())
        if ele != rootElementName:
            print "unexpected xml element '%s' "\
                  "(was looking for %s)" % (ele, rootElementName)
            return
    if xr.hasError():
        print str(xr.errorString())
    if xr.readNextStartElement():
        itemread = undumpObject(xr)
        xr.skipCurrentElement()
    if xr.hasError():
        print str(xr.errorString())
    return itemread

def iterRepoItemFromXml(source):
    'Used by thgrepo.relatedRepositories to scan the XML file'
    xr = QXmlStreamReader(source)
    while not xr.atEnd():
        t = xr.readNext()
        if t == QXmlStreamReader.StartElement and xr.name() in ('repo', 'subrepo'):
            yield undumpObject(xr)

def getRepoItemList(root, includeSubRepos=False):
    if not includeSubRepos and isinstance(root, RepoItem):
        return [root]
    if not isinstance(root, RepoTreeItem):
        return []
    return reduce(lambda a, b: a + b,
                  (getRepoItemList(c, includeSubRepos=includeSubRepos) \
                    for c in root.childs), [])


class RepoTreeModel(QAbstractItemModel):

    def __init__(self, filename, parent, showSubrepos=False,
            showNetworkSubrepos=False, showShortPaths=False):
        QAbstractItemModel.__init__(self, parent)

        self.showSubrepos = showSubrepos
        self.showNetworkSubrepos = showNetworkSubrepos
        self.showShortPaths = showShortPaths

        root = None
        all = None

        if filename:
            f = QFile(filename)
            if f.open(QIODevice.ReadOnly):
                root = readXml(f, reporegistryXmlElementName)
                f.close()
                if root:
                    for c in root.childs:
                        if isinstance(c, AllRepoGroupItem):
                            all = c
                            break

                    if self.showSubrepos:
                        self.loadSubrepos(root)

        if not root:
            root = RepoTreeItem(self)
            all = AllRepoGroupItem(self)
            root.appendChild(all)

        self.rootItem = root
        self.allrepos = all
        self.updateCommonPaths()

    # see http://doc.qt.nokia.com/4.6/model-view-model-subclassing.html

    # overrides from QAbstractItemModel

    def index(self, row, column, parent):
        if not self.hasIndex(row, column, parent):
            return QModelIndex()
        if (not parent.isValid()):
            parentItem = self.rootItem
        else:
            parentItem = parent.internalPointer()
        childItem = parentItem.child(row)
        if childItem:
            return self.createIndex(row, column, childItem)
        else:
            return QModelIndex()

    def parent(self, index):
        if not index.isValid():
            return QModelIndex()
        childItem = index.internalPointer()
        parentItem = childItem.parent()
        if parentItem is self.rootItem:
            return QModelIndex()
        return self.createIndex(parentItem.row(), 0, parentItem)

    def rowCount(self, parent):
        if parent.column() > 0:
            return 0
        if not parent.isValid():
            parentItem = self.rootItem;
        else:
            parentItem = parent.internalPointer()
        return parentItem.childCount()

    def columnCount(self, parent):
        if parent.isValid():
            return parent.internalPointer().columnCount()
        else:
            return self.rootItem.columnCount()

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        if role not in (Qt.DisplayRole, Qt.EditRole, Qt.DecorationRole,
                Qt.FontRole):
            return QVariant()
        item = index.internalPointer()
        return item.data(index.column(), role)

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole:
            if orientation == Qt.Horizontal:
                if section == 1:
                    return QString(_('Path'))
        return QVariant()

    def flags(self, index):
        if not index.isValid():
            return Qt.NoItemFlags
        item = index.internalPointer()
        return item.flags()

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction | Qt.LinkAction

    def removeRows(self, row, count, parent):
        item = parent.internalPointer()
        if item is None:
            item = self.rootItem
        self.beginRemoveRows(parent, row, row+count-1)
        res = item.removeRows(row, count)
        self.endRemoveRows()
        return res

    def mimeTypes(self):
        return QStringList([repoRegMimeType, repoExternalMimeType])

    def mimeData(self, indexes):
        i = indexes[0]
        item = i.internalPointer()
        buf = QByteArray()
        writeXml(buf, item, extractXmlElementName)
        d = QMimeData()
        d.setData(repoRegMimeType, buf)
        if isinstance(item, RepoItem):
            d.setUrls([QUrl.fromLocalFile(hglib.tounicode(item.rootpath()))])
        else:
            d.setText(QString(item.name))
        return d

    def dropMimeData(self, data, action, row, column, parent):
        group = parent.internalPointer()
        d = str(data.data(repoRegMimeType))
        if not data.hasUrls():
            # don't allow nesting of groups
            row = parent.row()
            group = self.rootItem
            parent = QModelIndex()
        itemread = readXml(d, extractXmlElementName)
        if itemread is None:
            return False
        if group is None:
            return False
        # Avoid copying subrepos multiple times
        if Qt.CopyAction == action and self.getRepoItem(itemread.rootpath()):
            return False
        if row < 0:
            row = 0
        if self.showSubrepos:
            self.loadSubrepos(itemread)
        self.beginInsertRows(parent, row, row)
        group.insertChild(row, itemread)
        self.endInsertRows()
        if isinstance(itemread, AllRepoGroupItem):
            self.allrepos = itemread
        return True

    def setData(self, index, value, role):
        if not index.isValid() or role != Qt.EditRole:
            return False
        s = value.toString()
        if s.isEmpty():
            return False
        item = index.internalPointer()
        if item.setData(index.column(), value):
            self.dataChanged.emit(index, index)
            return True
        return False

    # functions not defined in QAbstractItemModel

    def allreposIndex(self):
        return self.createIndex(self.allrepos.row(), 0, self.allrepos)

    def addRepo(self, group, root, row=-1):
        grp = group
        if grp == None:
            grp = self.allreposIndex()
        rgi = grp.internalPointer()
        if row < 0:
            row = rgi.childCount()

        # Is the root of the repo that we want to add a subrepo contained
        # within a repo or subrepo? If so, assume it is an hg subrepo
        itemIsSubrepo = not paths.find_root(os.path.dirname(root)) is None
        self.beginInsertRows(grp, row, row)
        if itemIsSubrepo:
            ri = SubrepoItem(root)
        else:
            ri = RepoItem(root)
        rgi.insertChild(row, ri)

        if not self.showSubrepos \
                or (not self.showNetworkSubrepos and paths.netdrive_status(root)):
            self.endInsertRows()
            return

        invalidRepoList = ri.appendSubrepos()

        self.endInsertRows()

        if invalidRepoList:
            if invalidRepoList[0] == root:
                qtlib.WarningMsgBox(_('Could not get subrepository list'),
                    _('It was not possible to get the subrepository list for '
                    'the repository in:<br><br><i>%s</i>') % root)
            else:
                qtlib.WarningMsgBox(_('Could not open some subrepositories'),
                    _('It was not possible to fully load the subrepository '
                    'list for the repository in:<br><br><i>%s</i><br><br>'
                    'The following subrepositories may be missing, broken or '
                    'on an inconsistent state and cannot be accessed:'
                    '<br><br><i>%s</i>')  %
                    (root, "<br>".join(invalidRepoList)))

    def getRepoItem(self, reporoot, lookForSubrepos=False):
        return self.rootItem.getRepoItem(os.path.normcase(reporoot),
                    lookForSubrepos=lookForSubrepos)

    def addGroup(self, name):
        ri = self.rootItem
        cc = ri.childCount()
        self.beginInsertRows(QModelIndex(), cc, cc + 1)
        ri.appendChild(RepoGroupItem(name, ri))
        self.endInsertRows()

    def write(self, fn):
        f = QFile(fn)
        f.open(QIODevice.WriteOnly)
        writeXml(f, self.rootItem, reporegistryXmlElementName)
        f.close()

    def depth(self, index):
        count = 1
        while True:
            index = index.parent()
            if index.row() < 0:
                return count
            count += 1

    def loadSubrepos(self, root, filterFunc=(lambda r: True)):
        for c in getRepoItemList(root):
            if filterFunc(c.rootpath()):
                if self.showNetworkSubrepos \
                        or not paths.netdrive_status(c.rootpath()):
                    self.removeRows(0, c.childCount(),
                        self.createIndex(c.row(), 0, c))
                    c.appendSubrepos()

    def updateCommonPaths(self, showShortPaths=None):
        if not showShortPaths is None:
            self.showShortPaths = showShortPaths
        for grp in self.rootItem.childs:
            if isinstance(grp, RepoGroupItem):
                if self.showShortPaths:
                    grp.updateCommonPath()
                else:
                    grp.updateCommonPath('')

