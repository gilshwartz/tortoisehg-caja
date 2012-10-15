# repotreeitem.py - treeitems for the reporegistry
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import sys, os

from mercurial import node
from mercurial import ui, hg, util, error

from tortoisehg.util import hglib, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, hgrcutil

from PyQt4.QtCore import *
from PyQt4.QtGui import *


xmlClassMap = {
      'allgroup': 'AllRepoGroupItem',
      'group': 'RepoGroupItem',
      'repo': 'RepoItem',
      'subrepo': 'SubrepoItem',
      'treeitem': 'RepoTreeItem',
    }

inverseXmlClassMap = {}

def xmlToClass(ele):
    return xmlClassMap[ele]

def classToXml(classname):
    if len(inverseXmlClassMap) == 0:
        for k,v in xmlClassMap.iteritems():
            inverseXmlClassMap[v] = k
    return inverseXmlClassMap[classname]

def undumpObject(xr):
    classname = xmlToClass(str(xr.name().toString()))
    class_ = getattr(sys.modules[RepoTreeItem.__module__], classname)
    obj = class_()
    obj.undump(xr)
    return obj


class RepoTreeItem(object):
    def __init__(self, parent=None):
        self._parent = parent
        self.childs = []
        self._row = 0

    def appendChild(self, child):
        child._row = len(self.childs)
        child._parent = self
        self.childs.append(child)

    def insertChild(self, row, child):
        child._row = row
        child._parent = self
        self.childs.insert(row, child)

    def child(self, row):
        return self.childs[row]

    def childCount(self):
        return len(self.childs)

    def columnCount(self):
        return 2

    def data(self, column, role):
        return QVariant()

    def setData(self, column, value):
        return False

    def row(self):
        return self._row

    def parent(self):
        return self._parent

    def menulist(self):
        return []

    def flags(self):
        return Qt.NoItemFlags

    def removeRows(self, row, count):
        cs = self.childs
        remove = cs[row : row + count]
        keep = cs[:row] + cs[row + count:]
        self.childs = keep
        for c in remove:
            c._row = 0
            c._parent = None
        for i, c in enumerate(keep):
            c._row = i
        return True

    def dump(self, xw):
        for c in self.childs:
            c.dumpObject(xw)

    def undump(self, xr):
        while not xr.atEnd():
            xr.readNext()
            if xr.isStartElement():
                try:
                    item = undumpObject(xr)
                    self.appendChild(item)
                except KeyError:
                    pass # ignore unknown classes in xml
            elif xr.isEndElement():
                break

    def dumpObject(self, xw):
        xw.writeStartElement(classToXml(self.__class__.__name__))
        self.dump(xw)
        xw.writeEndElement()

    def isRepo(self):
        return False

    def details(self):
        return ''

    def getRepoItem(self, reporoot, lookForSubrepos=False):
        for c in self.childs:
            ri = c.getRepoItem(reporoot, lookForSubrepos=lookForSubrepos)
            if ri:
                return ri
        return None

    def okToDelete(self):
        return True

    def getSupportedDragDropActions(self):
        return Qt.MoveAction


class RepoItem(RepoTreeItem):
    shortnameChanged = pyqtSignal()
    def __init__(self, root=None, parent=None):
        RepoTreeItem.__init__(self, parent)
        self._root = root or ''
        self._shortname = u''
        self._basenode = node.nullid
        self._repotype = 'hg'
        # The _valid property is used to display a "warning" icon for repos
        # that cannot be open
        # If root is set we assume that the repo is valid (an actual validity
        # test would require calling hg.repository() which is expensive)
        # Regardless, self._valid may be set to False if self.undump() fails
        if self._root:
            self._valid = True
        else:
            self._valid = False
        self._isActiveTab = False

    def isRepo(self):
        return True

    def rootpath(self):
        return self._root

    def shortname(self):
        if self._shortname:
            return self._shortname
        else:
            return hglib.tounicode(os.path.basename(self._root))

    def repotype(self):
        return self._repotype

    def basenode(self):
        """Return node id of revision 0"""
        return self._basenode

    def setBaseNode(self, basenode):
        self._basenode = basenode

    def setShortName(self, uname):
        if uname != self._shortname:
            self._shortname = uname

    def data(self, column, role):
        if role == Qt.DecorationRole:
            if column == 0:
                baseiconname = 'hg'
                if paths.is_unc_path(self.rootpath()):
                    baseiconname = 'thg-remote-repo'
                ico = qtlib.geticon(baseiconname)
                if not self._valid:
                    ico = qtlib.getoverlaidicon(ico, qtlib.geticon('dialog-warning'))
                return QVariant(ico)
            return QVariant()
        elif role == Qt.FontRole:
            if self._isActiveTab:
                font = QFont()
                font.setBold(True)
            else:
                return QVariant()
            return QVariant(font)
        if column == 0:
            return QVariant(self.shortname())
        elif column == 1:
            return QVariant(self.shortpath())
        return QVariant()

    def getCommonPath(self):
        return self.parent().getCommonPath()

    def shortpath(self):
        try:
            cpath = self.getCommonPath()
        except:
            cpath = ''
        spath2 = spath = os.path.normpath(self._root)

        if os.name == 'nt':
            spath2 = spath2.lower()

        if cpath and spath2.startswith(cpath):
            iShortPathStart = len(cpath)
            spath = spath[iShortPathStart:]
            if spath and spath[0] in '/\\':
                # do not show a slash at the beginning of the short path
                spath = spath[1:]

        return hglib.tounicode(spath)

    def menulist(self):
        acts = ['open', 'clone', 'addsubrepo', None, 'explore',
                'terminal', 'copypath', None, 'rename', 'remove']
        if self.childCount() > 0:
            acts.extend([None, (_('Sort'), ['sortbyname', 'sortbyhgsub'])])
        acts.extend([None, 'settings'])
        return acts

    def flags(self):
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
            | Qt.ItemIsEditable)

    def dump(self, xw):
        xw.writeAttribute('root', hglib.tounicode(self._root))
        xw.writeAttribute('shortname', self.shortname())
        xw.writeAttribute('basenode', node.hex(self.basenode()))

    def undump(self, xr):
        self._valid = True
        a = xr.attributes()
        self._root = hglib.fromunicode(a.value('', 'root').toString())
        self._shortname = unicode(a.value('', 'shortname').toString())
        self._basenode = node.bin(str(a.value('', 'basenode').toString()))
        RepoTreeItem.undump(self, xr)

    def details(self):
        return _('Local Repository %s') % hglib.tounicode(self._root)

    def getRepoItem(self, reporoot, lookForSubrepos=False):
        reporoot = os.path.normcase(reporoot)
        if (reporoot == os.path.normcase(self._root)):
            return self
        if lookForSubrepos:
            return super(RepoItem, self).getRepoItem(reporoot, lookForSubrepos)
        return None

    def appendSubrepos(self, repo=None):
        invalidRepoList = []

        # Mercurial repos are the only ones that can have subrepos
        if self.repotype() == 'hg':
            try:
                sri = None
                if repo is None:
                    if not os.path.exists(self._root):
                        self._valid = False
                        return [self._root]
                    elif not os.path.exists(os.path.join(self._root, '.hgsub')):
                        return []  # skip repo creation, which is expensive
                    repo = hg.repository(ui.ui(), self._root)
                wctx = repo['.']
                sortkey = lambda x: os.path.basename(util.normpath(repo.wjoin(x)))
                for subpath in sorted(wctx.substate, key=sortkey):
                    sri = None
                    abssubpath = repo.wjoin(subpath)
                    subtype = wctx.substate[subpath][2]
                    sriIsValid = os.path.isdir(abssubpath)
                    sri = SubrepoItem(abssubpath, subtype=subtype)
                    sri._valid = sriIsValid
                    self.appendChild(sri)

                    if not sriIsValid:
                        self._valid = False
                        sri._valid = False
                        invalidRepoList.append(repo.wjoin(subpath))
                        return invalidRepoList
                        continue

                    if subtype == 'hg':
                        # Only recurse into mercurial subrepos
                        sctx = wctx.sub(subpath)
                        invalidSubrepoList = sri.appendSubrepos(sctx._repo)
                        if invalidSubrepoList:
                            self._valid = False
                            invalidRepoList += invalidSubrepoList

            except (EnvironmentError, error.RepoError, util.Abort), e:
                # Add the repo to the list of repos/subrepos
                # that could not be open
                self._valid = False
                if sri:
                    sri._valid = False
                    invalidRepoList.append(abssubpath)
                invalidRepoList.append(self._root)
            except Exception, e:
                # If any other sort of exception happens, show the corresponding
                # error message, but do not crash!
                # Note that we _also_ will mark the offending repos as invalid
                # It is unfortunate that Python 2.4, which we target does not
                # support combined try/except/finally clauses, forcing us
                # to duplicate some code here
                self._valid = False
                if sri:
                    sri._valid = False
                    invalidRepoList.append(abssubpath)
                invalidRepoList.append(self._root)

                # Show a warning message indicating that there was an error
                if repo:
                    rootpath = repo.root
                else:
                    rootpath = self._root
                warningMessage = (_('An exception happened while loading the ' \
                    'subrepos of:<br><br>"%s"<br><br>') + \
                    _('The exception error message was:<br><br>%s<br><br>') +\
                    _('Click OK to continue or Abort to exit.')) \
                    % (rootpath, e.message)
                res = qtlib.WarningMsgBox(_('Error loading subrepos'),
                                    warningMessage,
                                    buttons = QMessageBox.Ok | QMessageBox.Abort)
                # Let the user abort so that he gets the full exception info
                if res == QMessageBox.Abort:
                    raise
        return invalidRepoList

    def setActive(self, sel):
        # Will be set to true when this item corresponds to the currently
        # selected tab widget on the workbench
        self._isActiveTab = sel

    def setData(self, column, value):
        if column == 0:
            shortname = hglib.fromunicode(value.toString())
            abshgrcpath = os.path.join(self.rootpath(), '.hg', 'hgrc')
            if not hgrcutil.setConfigValue(abshgrcpath, 'web.name', shortname):
                qtlib.WarningMsgBox(_('Unable to update repository name'),
                    _('An error occurred while updating the repository hgrc '
                      'file (%s)') % hglib.tounicode(abshgrcpath))
                return False
            self.setShortName(shortname)
            return True
        return False


class SubrepoItem(RepoItem):
    _subrepoType2IcoMap = {
          'hg': 'hg',
          'git': 'thg-git-subrepo',
          'svn': 'thg-svn-subrepo',
    }

    def __init__(self, repo=None, parent=None, parentrepo=None, subtype='hg'):
        RepoItem.__init__(self, repo, parent)
        self._parentrepo = parentrepo
        self._repotype = subtype
        if self._repotype != 'hg':
            # Make sure that we cannot drag non hg subrepos
            # To do so we disable the dumpObject method for non hg subrepos
            def doNothing(dummy):
                pass
            self.dumpObject = doNothing

            # Limit the context menu to those actions that are valid for non
            # mercurial subrepos
            def nonHgMenulist():
                return ['remove', None, 'explore', 'terminal']
            self.menulist = nonHgMenulist

    def data(self, column, role):
        if role == Qt.DecorationRole:
            if column == 0:
                subiconame = SubrepoItem._subrepoType2IcoMap.get(self._repotype, None)
                if subiconame is None:
                    # Unknown (or generic) subrepo type
                    ico = qtlib.geticon('thg-subrepo')
                else:
                    # Overlay the "subrepo icon" on top of the selected subrepo
                    # type icon
                    ico = qtlib.geticon(subiconame)
                    ico = qtlib.getoverlaidicon(ico, qtlib.geticon('thg-subrepo'))

                if not self._valid:
                    ico = qtlib.getoverlaidicon(ico, qtlib.geticon('dialog-warning'))

                return QVariant(ico)
            return QVariant()
        else:
            return super(SubrepoItem, self).data(column, role)

    def menulist(self):
        if isinstance(self._parent, RepoGroupItem):
            return super(SubrepoItem, self).menulist()
        else:
            acts = ['open', 'clone', 'addsubrepo', None, 'explore',
                    'terminal', 'copypath']
            if self.childCount() > 0:
                acts.extend([None, (_('Sort'), ['sortbyname', 'sortbyhgsub'])])
            acts.extend([None, 'settings'])
            return acts

    def getSupportedDragDropActions(self):
        if issubclass(type(self.parent()), RepoGroupItem):
            return Qt.MoveAction
        else:
            return Qt.CopyAction

    def flags(self):
        # Only stand-alone subrepo items can be renamed
        if isinstance(self._parent, RepoGroupItem):
            return super(SubrepoItem, self).flags()
        else:
            return (Qt.ItemIsEnabled | Qt.ItemIsSelectable
                | Qt.ItemIsDragEnabled)


class RepoGroupItem(RepoTreeItem):
    def __init__(self, name=None, parent=None):
        RepoTreeItem.__init__(self, parent)
        if name:
            self.name = name
        else:
            self.name = QString()
        self._commonpath = ''

    def data(self, column, role):
        if role == Qt.DecorationRole:
            if column == 0:
                s = QApplication.style()
                ico = s.standardIcon(QStyle.SP_DirIcon)
                return QVariant(ico)
            return QVariant()
        if column == 0:
            return QVariant(self.name)
        elif column == 1:
            return QVariant(self.getCommonPath())
        return QVariant()

    def setData(self, column, value):
        if column == 0:
            self.name = value.toString()
            return True
        return False

    def menulist(self):
        return ['openAll', 'add', None, 'newGroup', None, 'rename', 'remove',
            None, (_('Sort'), ['sortbyname', 'sortbypath']), None,
            'reloadRegistry']

    def flags(self):
        return (Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled
            | Qt.ItemIsDragEnabled | Qt.ItemIsEditable)

    def childRoots(self):
        return [c._root for c in self.childs]

    def dump(self, xw):
        xw.writeAttribute('name', self.name)
        RepoTreeItem.dump(self, xw)

    def undump(self, xr):
        a = xr.attributes()
        self.name = a.value('', 'name').toString()
        RepoTreeItem.undump(self, xr)

    def okToDelete(self):
        return False

    def updateCommonPath(self, cpath=None):
        """
        Update or set the group 'common path'

        When called with no arguments, the group common path is calculated by
        looking for the common path of all the repos on a repo group

        When called with an argument, the group common path is set to the input
        argument. This is commonly used to set the group common path to an empty
        string, thus disabling the "show short paths" functionality.
        """
        if not cpath is None:
            self._commonpath = cpath
        elif len(self.childs) == 0:
            # If a group has no repo items, the common path is empty
            self._commonpath = ''
        else:
            childs = [os.path.normcase(child.rootpath())
                      for child in self.childs
                      if not isinstance(child, RepoGroupItem)]
            self._commonpath = os.path.dirname(os.path.commonprefix(childs))

        return self._commonpath

    def getCommonPath(self):
        return self._commonpath

class AllRepoGroupItem(RepoGroupItem):
    def __init__(self, parent=None):
        RepoGroupItem.__init__(self, name=_('default'), parent=parent)

    def menulist(self):
        return ['openAll', 'add', None, 'newGroup', None, 'rename',
            None, (_('Sort'), ['sortbyname', 'sortbypath']), None,
            'reloadRegistry']

    def undump(self, xr):
        a = xr.attributes()
        name = a.value('', 'name').toString()
        if name:
            self.name = name
        RepoTreeItem.undump(self, xr)
