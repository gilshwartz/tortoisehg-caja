# sync.py - TortoiseHg's sync widget
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

import os
import re
import tempfile
import urlparse

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from mercurial import hg, ui, url, util, error, demandimport
from mercurial import merge as mergemod

from tortoisehg.util import hglib, wconfig, paths
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, thgrepo, rebase, resolve, hgrcutil

def parseurl(path):
    if path.startswith('ssh://'):
        scheme = 'ssh'
        p = path[len('ssh://'):]
        user, passwd = None, None
        if p.find('@') != -1:
            user, p = tuple(p.rsplit('@', 1))
            if user.find(':') != -1:
                user, passwd = tuple(user.rsplit(':', 1))
        m = re.match(r'([^:/]+)(:(\d+))?(/(.*))?$', p)
        if m:
            host = m.group(1)
            port = m.group(3)
            folder = m.group(5) or '.'
        else:
            qtlib.WarningMsgBox(_('Malformed ssh URL'), hglib.tounicode(path))
            host, port, folder = '', '', ''
    elif path.startswith(('http://', 'https://', 'svn+https://')):
        snpaqf = urlparse.urlparse(path)
        scheme, netloc, folder, params, query, fragment = snpaqf
        host, port, user, passwd = hglib.netlocsplit(netloc)
        if folder.startswith('/'):
            folder = folder[1:]
    else:
        user, host, port, passwd = [''] * 4
        folder = path
        scheme = 'local'
    return user, host, port, folder, passwd, scheme

class SyncWidget(QWidget, qtlib.TaskWidget):
    syncStarted = pyqtSignal()  # incoming/outgoing/pull/push started
    outgoingNodes = pyqtSignal(object)
    incomingBundle = pyqtSignal(QString)
    showMessage = pyqtSignal(unicode)
    pullCompleted = pyqtSignal()
    pushCompleted = pyqtSignal()

    output = pyqtSignal(QString, QString)
    progress = pyqtSignal(QString, object, QString, QString, object)
    makeLogVisible = pyqtSignal(bool)
    beginSuppressPrompt = pyqtSignal()
    endSuppressPrompt = pyqtSignal()
    showBusyIcon = pyqtSignal(QString)
    hideBusyIcon = pyqtSignal(QString)

    def __init__(self, repo, parent, **opts):
        QWidget.__init__(self, parent)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.setLayout(layout)
        self.setAcceptDrops(True)

        self._schemes = ['local', 'ssh', 'http', 'https']
        if 'hgsubversion' in repo.extensions():
            self._schemes.append('svn+https')

        self.repo = repo
        self.finishfunc = None
        self.curuser = None
        self.default_user = None
        self.lastsshuser = None
        self.curpw = None
        self.updateInProgress = False
        self.opts = {}
        self.cmenu = None
        self.embedded = bool(parent)
        self.targetargs = []

        self.repo.configChanged.connect(self.configChanged)

        if self.embedded:
            layout.setContentsMargins(2, 2, 2, 2)
        else:
            self.setWindowTitle(_('TortoiseHg Sync'))
            self.setWindowIcon(qtlib.geticon('thg-sync'))
            self.resize(850, 550)

        tb = QToolBar(self)
        tb.setStyleSheet(qtlib.tbstylesheet)
        self.layout().addWidget(tb)
        self.opbuttons = []

        def newaction(tip, icon, cb):
            a = QAction(self)
            a.setToolTip(tip)
            a.setIcon(qtlib.geticon(icon))
            a.triggered.connect(cb)
            self.opbuttons.append(a)
            tb.addAction(a)
            return a

        self.incomingAction = \
        newaction(_('Preview incoming changesets from remote repository'),
             'hg-incoming', self.inclicked)
        self.pullAction = \
        newaction(_('Pull incoming changesets from remote repository'),
             'hg-pull', self.pullclicked)
        self.outgoingAction = \
        newaction(_('Filter outgoing changesets to remote repository'),
             'hg-outgoing', self.outclicked)
        self.pushAction = \
        newaction(_('Push outgoing changesets to remote repository'),
             'hg-push', lambda: self.pushclicked(True))
        newaction(_('Email outgoing changesets for remote repository'),
             'mail-forward', self.emailclicked)

        if 'perfarce' in self.repo.extensions():
            a = QAction(self)
            a.setToolTip(_('Manage pending perforce changelists'))
            a.setText('P4')
            a.triggered.connect(self.p4pending)
            self.opbuttons.append(a)
            tb.addAction(a)
        tb.addSeparator()
        newaction(_('Unbundle'),
             'hg-unbundle', self.unbundle)
        tb.addSeparator()
        self.stopAction = a = QAction(self)
        a.setToolTip(_('Stop current operation'))
        a.setIcon(qtlib.geticon('process-stop'))
        a.triggered.connect(self.stopclicked)
        a.setEnabled(False)
        tb.addAction(a)

        tb.addSeparator()
        self.optionsbutton = QPushButton(_('Options'))
        self.postpullbutton = QPushButton()
        tb.addWidget(self.postpullbutton)
        tb.addWidget(self.optionsbutton)

        self.targetcombo = QComboBox()
        self.targetcombo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.targetcombo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLength)
        self.targetcombo.setEnabled(False)
        self.targetcheckbox = QCheckBox(_('Target:'))
        self.targetcheckbox.toggled.connect(self.targetcombo.setEnabled)
        if self.embedded:
            tb.addSeparator()
            tb.addWidget(self.targetcheckbox)
            tb.addWidget(self.targetcombo)

        bottomlayout = QVBoxLayout()
        if not parent:
            bottomlayout.setContentsMargins(5, 5, 5, 5)
        else:
            bottomlayout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(bottomlayout)

        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        bottomlayout.addLayout(hbox)
        self.optionshdrlabel = lbl = QLabel(_('<b>Selected Options:</b>'))
        hbox.addWidget(lbl)
        self.optionslabel = QLabel()
        self.optionslabel.setAcceptDrops(False)
        hbox.addWidget(self.optionslabel)
        hbox.addStretch()

        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        bottomlayout.addLayout(hbox)
        hbox.addWidget(QLabel(_('<b>Remote Repository:</b>')))
        self.urllabel = QLabel()
        self.urllabel.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.urllabel.setAcceptDrops(False)
        hbox.addWidget(self.urllabel)
        hbox.addStretch()

        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        bottomlayout.addLayout(hbox)

        self.pathEditToolbar = tbar = QToolBar(_('Path Edit Toolbar'))
        tbar.setStyleSheet(qtlib.tbstylesheet)
        tbar.setIconSize(QSize(16, 16))
        hbox.addWidget(tbar)
        self.schemecombo = QComboBox()
        for s in self._schemes:
            self.schemecombo.addItem(s)
        self.schemecombo.currentIndexChanged.connect(self.schemeChange)
        tbar.addWidget(self.schemecombo)
        tbar.addWidget(qtlib.Spacer(2, 2))

        a = tbar.addAction(qtlib.geticon('thg-password'), _('Security'))
        a.setToolTip(_('Manage HTTPS connection security and user authentication'))
        self.securebutton = a
        tbar.addWidget(qtlib.Spacer(2, 2))

        self.hostAndPortActions = []

        fontm = QFontMetrics(self.font())
        self.hostentry = QLineEdit()
        self.hostentry.setToolTip(_('Hostname'))
        self.hostentry.setAcceptDrops(False)
        self.hostentry.setFixedWidth(30 * fontm.width('9'))
        self.hostentry.textChanged.connect(self.refreshUrl)
        self.hostAndPortActions.append(tbar.addWidget(self.hostentry))
        self.hostAndPortActions.append(tbar.addWidget(qtlib.Spacer(2, 2)))

        w = QLabel(':')
        self.hostAndPortActions.append(tbar.addWidget(w))
        self.hostAndPortActions.append(tbar.addWidget(qtlib.Spacer(2, 2)))
        self.portentry = QLineEdit()
        self.portentry.setAcceptDrops(False)
        self.portentry.setToolTip(_('Port'))
        self.portentry.setFixedWidth(8 * fontm.width('9'))
        self.portentry.setValidator(QIntValidator(0, 65536, self.portentry))
        self.portentry.textChanged.connect(self.refreshUrl)
        self.hostAndPortActions.append(tbar.addWidget(self.portentry))
        self.hostAndPortActions.append(tbar.addWidget(qtlib.Spacer(2, 2)))
        w = QLabel('/')
        self.hostAndPortActions.append(tbar.addWidget(w))
        self.hostAndPortActions.append(tbar.addWidget(qtlib.Spacer(2, 2)))
        self.pathentry = QLineEdit()
        self.pathentry.setAcceptDrops(False)
        self.pathentry.setToolTip(_('Path'))
        self.pathentry.textChanged.connect(self.refreshUrl)
        tbar.addWidget(self.pathentry)
        tbar.addWidget(qtlib.Spacer(2, 2))

        style = QApplication.style()
        a = tbar.addAction(style.standardIcon(QStyle.SP_DialogSaveButton),
                          _('Save'))
        a.setToolTip(_('Save current URL under an alias'))
        self.savebutton = a

        hbox = QHBoxLayout()
        hbox.setContentsMargins(0, 0, 0, 0)
        self.hgrctv = PathsTree(self, True)
        self.hgrctv.clicked.connect(self.pathSelected)
        self.hgrctv.removeAlias.connect(self.removeAlias)
        self.hgrctv.menuRequest.connect(self.menuRequest)
        pathsframe = QFrame()
        pathsframe.setFrameStyle(QFrame.StyledPanel|QFrame.Raised)
        pathsbox = QVBoxLayout()
        pathsbox.setContentsMargins(0, 0, 0, 0)
        pathsframe.setLayout(pathsbox)
        lbl = QLabel(_('Paths in Repository Settings:'))
        pathsbox.addWidget(lbl)
        pathsbox.addWidget(self.hgrctv)
        hbox.addWidget(pathsframe)

        self.reltv = PathsTree(self, False)
        self.reltv.clicked.connect(self.pathSelected)
        self.reltv.menuRequest.connect(self.menuRequest)
        self.reltv.clicked.connect(self.hgrctv.clearSelection)
        self.hgrctv.clicked.connect(self.reltv.clearSelection)
        pathsframe = QFrame()
        pathsframe.setFrameStyle(QFrame.StyledPanel|QFrame.Raised)
        pathsbox = QVBoxLayout()
        pathsbox.setContentsMargins(0, 0, 0, 0)
        pathsframe.setLayout(pathsbox)
        lbl = QLabel(_('Related Paths:'))
        pathsbox.addWidget(lbl)
        pathsbox.addWidget(self.reltv)
        hbox.addWidget(pathsframe)

        bottomlayout.addLayout(hbox, 1)

        self.savebutton.triggered.connect(self.saveclicked)
        self.securebutton.triggered.connect(self.secureclicked)
        self.postpullbutton.clicked.connect(self.postpullclicked)
        self.optionsbutton.pressed.connect(self.editOptions)

        cmd = cmdui.Widget(not self.embedded, True, self)
        cmd.commandStarted.connect(self.beginSuppressPrompt)
        cmd.commandStarted.connect(self.commandStarted)
        cmd.commandFinished.connect(self.endSuppressPrompt)
        cmd.commandFinished.connect(self.commandFinished)
        cmd.makeLogVisible.connect(self.makeLogVisible)
        cmd.output.connect(self.output)
        cmd.output.connect(self.outputHook)
        cmd.progress.connect(self.progress)
        if not self.embedded:
            self.showMessage.connect(cmd.stbar.showMessage)

        bottomlayout.addWidget(cmd)
        cmd.setVisible(False)
        self.cmd = cmd

        self.reload()
        if 'default' in self.paths:
            self.setUrl(self.paths['default'])
            self.curalias = 'default'
        else:
            self.setUrl('')
            self.curalias = None

        self.default_user = self.curuser
        self.lastsshuser = self.curuser

    def canswitch(self):
        return not self.targetcheckbox.isChecked()

    def schemeChange(self):
        if self.default_user:
            scheme = self._schemes[self.schemecombo.currentIndex()]
            if scheme == 'ssh':
                self.default_user = self.curuser
                self.curuser = self.lastsshuser
            else:
                self.curuser = self.default_user

        self.refreshUrl()

    def refreshStatusTips(self):
        url = self.currentUrl(True)
        urlu = hglib.tounicode(url)
        self.incomingAction.setStatusTip(_('Preview incoming changesets from %s') % urlu)
        self.pullAction.setStatusTip(_('Pull incoming changesets from %s') % urlu)
        self.outgoingAction.setStatusTip(_('Filter outgoing changesets to %s') % urlu)
        self.pushAction.setStatusTip(_('Push outgoing changesets to %s') % urlu)

    def loadTargets(self, ctx):
        self.targetcombo.clear()
        #The parallel targetargs record is the argument list to pass to hg
        self.targetargs = []
        selIndex = 0;
        self.targetcombo.addItem(_('rev: %d (%s)') % (ctx.rev(), str(ctx)))
        self.targetargs.append(['--rev', str(ctx.rev())])

        for name in self.repo.namedbranches:
            uname = hglib.tounicode(name)
            self.targetcombo.addItem(_('branch: ') + uname)
            self.targetcombo.setItemData(self.targetcombo.count() - 1, name, Qt.ToolTipRole)
            self.targetargs.append(['--branch', name])
            if ctx.thgbranchhead() and name == ctx.branch():
                selIndex = self.targetcombo.count() - 1
        for name in self.repo._bookmarks.keys():
            uname = hglib.tounicode(name)
            self.targetcombo.addItem(_('bookmark: ') + uname)
            self.targetcombo.setItemData(self.targetcombo.count() - 1, name, Qt.ToolTipRole)
            self.targetargs.append(['--bookmark', name])
            if name in ctx.bookmarks():
                selIndex = self.targetcombo.count() - 1

        return selIndex

    def refreshTargets(self, rev):
        if type(rev) is not int:
            return

        if rev >= len(self.repo):
            return

        ctx = self.repo.changectx(rev)
        index = self.loadTargets(ctx)

        if index < 0:
            index = 0
        self.targetcombo.setCurrentIndex(index)

    def configChanged(self):
        'Repository is reporting its config files have changed'
        self.reload()

    def editOptions(self):
        dlg = OptionsDialog(self.opts, self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.opts.update(dlg.outopts)
            self.refreshUrl()

    def reload(self):
        # Refresh configured paths
        self.paths = {}
        fn = self.repo.join('hgrc')
        fn, cfg = hgrcutil.loadIniFile([fn], self)
        if 'paths' in cfg:
            for alias in cfg['paths']:
                self.paths[ alias ] = cfg['paths'][ alias ]
        tm = PathsModel(self.paths.items(), self)
        self.hgrctv.setModel(tm)

        # Refresh post-pull
        self.cachedpp = self.repo.postpull
        name = _('Post Pull: ') + self.repo.postpull.title()
        self.postpullbutton.setText(name)

        # Refresh related paths
        known = set()
        known.add(os.path.abspath(self.repo.root).lower())
        for path in self.paths.values():
            if hg.islocal(path):
                known.add(os.path.abspath(hglib.localpath(path)).lower())
            else:
                known.add(path)
        related = {}
        for root, shortname in thgrepo.relatedRepositories(self.repo[0].node()):
            if root == self.repo.root:
                continue
            abs = os.path.abspath(root).lower()
            if abs not in known:
                related[root] = shortname
                known.add(abs)
            if root in thgrepo._repocache:
                # repositories already opened keep their ui instances in sync
                repo = thgrepo._repocache[root]
                ui = repo.ui
            elif paths.is_on_fixed_drive(root):
                # directly read the repository's configuration file
                tempui = self.repo.ui.copy()
                tempui.readconfig(os.path.join(root, '.hg', 'hgrc'))
                ui = tempui
            else:
                continue
            for alias, path in ui.configitems('paths'):
                if hg.islocal(path):
                    abs = os.path.abspath(hglib.localpath(path)).lower()
                else:
                    abs = path
                if abs not in known:
                    related[path] = alias
                    known.add(abs)
        pairs = [(alias, path) for path, alias in related.items()]
        tm = PathsModel(pairs, self)
        self.reltv.setModel(tm)

    def refreshUrl(self):
        'User has changed schema/host/port/path'
        if self.updateInProgress:
            return
        self.urllabel.setText(hglib.tounicode(self.currentUrl(True)))
        schemeIndex = self.schemecombo.currentIndex()
        for w in self.hostAndPortActions:
            w.setVisible(schemeIndex != 0)
        self.securebutton.setVisible(schemeIndex >= 3)

        opts = []
        for opt, value in self.opts.iteritems():
            if value is True:
                opts.append('--'+opt)
            elif value:
                opts.append('--'+opt+'='+value)
        self.optionslabel.setText(' '.join(opts))
        self.optionslabel.setVisible(bool(opts))
        self.optionshdrlabel.setVisible(bool(opts))

    def currentUrl(self, hidepw):
        scheme = self._schemes[self.schemecombo.currentIndex()]
        if scheme == 'local':
            return hglib.fromunicode(self.pathentry.text())
        else:
            path = self.pathentry.text()
            host = self.hostentry.text()
            port = self.portentry.text()
            parts = [scheme, '://']
            if scheme == 'ssh' and '@' in host:
                user, host = unicode(host).split('@', 1)
                self.curuser = hglib.fromunicode(user)
                self.lastsshuser = self.curuser
            if self.curuser:
                parts.append(self.curuser)
                if self.curpw:
                    parts.append(':')
                    parts.append(hidepw and '***' or self.curpw)
                parts.append('@')
            parts.append(hglib.fromunicode(host))
            if port:
                parts.extend([':', hglib.fromunicode(port)])
            parts.extend(['/', hglib.fromunicode(path)])
            return ''.join(parts)

    def pathSelected(self, index):
        path = index.model().realUrl(index)
        self.setUrl(path)
        aliasindex = index.sibling(index.row(), 0)
        alias = aliasindex.data(Qt.DisplayRole).toString()
        self.curalias = hglib.fromunicode(alias)

    def setUrl(self, newurl):
        'User has selected a new URL: newurl is expected in local encoding'
        try:
            user, host, port, folder, passwd, scheme = parseurl(newurl)
        except TypeError:
            return
        self.updateInProgress = True
        for i, val in enumerate(self._schemes):
            if scheme == val:
                self.schemecombo.setCurrentIndex(i)
                break
        self.hostentry.setText(hglib.tounicode(host or ''))
        self.portentry.setText(hglib.tounicode(port or ''))
        self.pathentry.setText(hglib.tounicode(folder or ''))
        self.curuser = user
        self.curpw = passwd
        self.updateInProgress = False
        self.refreshUrl()
        self.refreshStatusTips()

    def dragEnterEvent(self, event):
        data = event.mimeData()
        if data.hasUrls() or data.hasText():
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        data = event.mimeData()
        if data.hasUrls() or data.hasText():
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()

    def dropEvent(self, event):
        data = event.mimeData()
        if data.hasUrls():
            url = data.urls()[0]
            lurl = hglib.fromunicode(url.toString())
            event.setDropAction(Qt.CopyAction)
            event.accept()
        elif data.hasText():
            text = data.text()
            lurl = hglib.fromunicode(text)
            event.setDropAction(Qt.CopyAction)
            event.accept()
        else:
            return
        if lurl.startswith('file:///'):
            lurl = lurl[8:]
        self.setUrl(lurl)

    def canExit(self):
        return not self.cmd.core.running()

    @pyqtSlot(QPoint, QString, QString, bool)
    def menuRequest(self, point, url, alias, editable):
        'menu event emitted by one of the two URL lists'
        if not self.cmenu:
            acts = []
            menu = QMenu(self)
            for text, cb, icon in (
                (_('Explore'), self.exploreurl, 'system-file-manager'),
                (_('Terminal'), self.terminalurl, 'utilities-terminal'),
                (_('Remove'), self.removeurl, 'menudelete')):
                act = QAction(text, self)
                act.setIcon(qtlib.getmenuicon(icon))
                act.triggered.connect(cb)
                acts.append(act)
                menu.addAction(act)
            self.cmenu = menu
            self.acts = acts

        self.menuurl = url
        self.menualias = alias
        self.acts[-1].setEnabled(editable)
        self.cmenu.exec_(point)

    def exploreurl(self):
        url = hglib.fromunicode(self.menuurl)
        u, h, p, folder, pw, scheme = parseurl(url)
        if scheme == 'local':
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        else:
            QDesktopServices.openUrl(QUrl(url))

    def terminalurl(self):
        url = hglib.fromunicode(self.menuurl)
        u, h, p, folder, pw, scheme = parseurl(url)
        if scheme != 'local':
            qtlib.InfoMsgBox(_('Repository not local'),
                        _('A terminal shell cannot be opened for remote'))
            return
        qtlib.openshell(folder, 'repo ' + folder)

    def removeurl(self):
        if qtlib.QuestionMsgBox(_('Confirm path delete'),
            _('Delete %s from your repo configuration file?') % self.menualias,
            parent=self):
            self.removeAlias(self.menualias)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Refresh):
            self.reload()
        elif event.key() == Qt.Key_Escape:
            if self.cmd.core.running():
                self.cmd.cancel()
            elif not self.embedded:
                self.close()
        else:
            return super(SyncWidget, self).keyPressEvent(event)

    def stopclicked(self):
        if self.cmd.core.running():
            self.cmd.cancel()

    def saveclicked(self):
        if self.curalias:
            alias = self.curalias
        elif 'default' not in self.paths:
            alias = 'default'
        else:
            alias = 'new'
        url = self.currentUrl(False)
        safeurl = self.currentUrl(True)
        dlg = SaveDialog(self.repo, alias, url, safeurl, self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        if dlg.exec_() == QDialog.Accepted:
            self.curalias = hglib.fromunicode(dlg.aliasentry.text())

    def secureclicked(self):
        dlg = SecureDialog(self.repo, self.currentUrl(False), self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.exec_()

    def commandStarted(self):
        for b in self.opbuttons:
            b.setEnabled(False)
        self.stopAction.setEnabled(True)
        if self.embedded:
            self.showBusyIcon.emit('thg-sync')
        else:
            self.cmd.setShowOutput(True)
            self.cmd.setVisible(True)

    def commandFinished(self, ret):
        self.hideBusyIcon.emit('thg-sync')
        self.repo.decrementBusyCount()
        for b in self.opbuttons:
            b.setEnabled(True)
        self.stopAction.setEnabled(False)
        if self.finishfunc:
            output = self.cmd.core.rawoutput()
            self.finishfunc(ret, output)

    def run(self, cmdline, details):
        if self.cmd.core.running():
            return
        self.lastcmdline = list(cmdline)
        for name in list(details) + ['remotecmd']:
            val = self.opts.get(name)
            if not val:
                continue
            if isinstance(val, bool):
                if val:
                    cmdline.append('--' + name)
            elif val:
                cmdline.append('--' + name)
                cmdline.append(val)

        if 'rev' in details and '--rev' not in cmdline:
            if self.embedded and self.targetcheckbox.isChecked():
                idx = self.targetcombo.currentIndex()
                if idx != -1 and idx < len(self.targetargs):
                    args = self.targetargs[idx]
                    if args[0][2:] not in details:
                        args[0] = '--rev'
                    cmdline += args
        if self.opts.get('noproxy'):
            cmdline += ['--config', 'http_proxy.host=']
        if self.opts.get('debug'):
            cmdline.append('--debug')

        cururl = self.currentUrl(False)
        if not cururl:
            qtlib.InfoMsgBox(_('No URL selected'),
                    _('An URL must be selected for this operation.'),
                    parent=self)
            return

        user, host, port, folder, passwd, scheme = parseurl(cururl)
        if scheme == 'https':
            if self.repo.ui.configbool('insecurehosts', host):
                cmdline.append('--insecure')
            if user:
                cleanurl = hglib.removeauth(cururl)
                res = hglib.readauthforuri(self.repo.ui, cleanurl, user)
                if res:
                    group, auth = res
                    if auth.get('username'):
                        if qtlib.QuestionMsgBox(
                            _('Redundant authentication info'),
                            _('You have authentication info configured for '
                              'this host and inside this URL.  Remove '
                              'authentication info from this URL?'),
                            parent=self):
                            self.setUrl(cleanurl)
                            self.saveclicked()

        safeurl = self.currentUrl(True)
        display = ' '.join(cmdline + [safeurl]).replace('\n', '^M')
        cmdline.append(cururl)
        self.repo.incrementBusyCount()
        self.cmd.run(cmdline, display=display, useproc='p4://' in cururl)

    def outputHook(self, msg, label):
        if '\'hg push --new-branch\'' in msg:
            self.needNewBranch = True

    ##
    ## Workbench toolbar buttons
    ##

    def incoming(self):
        if self.cmd.core.running():
            self.showMessage.emit(_('sync command already running'))
        else:
            self.inclicked()

    def pull(self):
        if self.cmd.core.running():
            self.showMessage.emit(_('sync command already running'))
        else:
            self.pullclicked()

    def outgoing(self):
        if self.cmd.core.running():
            self.showMessage.emit(_('sync command already running'))
        else:
            self.outclicked()

    def push(self, confirm, rev=None, branch=None):
        if self.cmd.core.running():
            self.showMessage.emit(_('sync command already running'))
        else:
            self.pushclicked(confirm, rev, branch)

    def pullBundle(self, bundle, rev):
        'accept bundle changesets'
        if self.cmd.core.running():
            self.output.emit(_('sync command already running'), 'control')
            return
        save = self.currentUrl(False)
        orev = self.opts.get('rev')
        self.setUrl(bundle)
        if rev is not None:
            self.opts['rev'] = str(rev)
        self.pullclicked()
        self.setUrl(save)
        self.opts['rev'] = orev

    ##
    ## Sync dialog buttons
    ##

    def inclicked(self):
        self.syncStarted.emit()
        url = self.currentUrl(True)
        urlu = hglib.tounicode(url)
        self.showMessage.emit(_('Getting incoming changesets from %s...') % urlu)
        if self.embedded and not url.startswith('p4://') and \
           not self.opts.get('subrepos'):
            def finished(ret, output):
                if ret == 0 and os.path.exists(bfile):
                    self.showMessage.emit(_('Found incoming changesets from %s') % urlu)
                    self.incomingBundle.emit(hglib.tounicode(bfile))
                elif ret == 1:
                    self.showMessage.emit(_('No incoming changesets from %s') % urlu)
                else:
                    self.showMessage.emit(_('Incoming from %s aborted, ret %d') % (urlu, ret))
            bfile = url
            for badchar in (':', '*', '\\', '?', '#'):
                bfile = bfile.replace(badchar, '')
            bfile = bfile.replace('/', '_')
            bfile = tempfile.mktemp('.hg', bfile+'_', qtlib.gettempdir())
            self.finishfunc = finished
            cmdline = ['--repository', self.repo.root, 'incoming', '--quiet',
                       '--bundle', bfile]
            self.run(cmdline, ('force', 'branch', 'rev'))
        else:
            def finished(ret, output):
                if ret == 0:
                    self.showMessage.emit(_('Found incoming changesets from %s') % urlu)
                elif ret == 1:
                    self.showMessage.emit(_('No incoming changesets from %s') % urlu)
                else:
                    self.showMessage.emit(_('Incoming from %s aborted, ret %d') % (urlu, ret))
            self.finishfunc = finished
            cmdline = ['--repository', self.repo.root, 'incoming']
            self.run(cmdline, ('force', 'branch', 'rev', 'subrepos'))

    def pullclicked(self):
        self.syncStarted.emit()
        url = self.currentUrl(True)
        urlu = hglib.tounicode(url)
        def finished(ret, output):
            if ret == 0:
                self.showMessage.emit(_('Pull from %s completed') % urlu)
            else:
                self.showMessage.emit(_('Pull from %s aborted, ret %d') % (urlu, ret))
            self.pullCompleted.emit()
            # handle file conflicts during rebase
            if self.opts.get('rebase'):
                if os.path.exists(self.repo.join('rebasestate')):
                    dlg = rebase.RebaseDialog(self.repo, self)
                    dlg.finished.connect(dlg.deleteLater)
                    dlg.exec_()
                    return
            # handle file conflicts during update
            for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
                if status == 'u':
                    qtlib.InfoMsgBox(_('Merge caused file conflicts'),
                                    _('File conflicts need to be resolved'))
                    dlg = resolve.ResolveDialog(self.repo, self)
                    dlg.finished.connect(dlg.deleteLater)
                    dlg.exec_()
                    return
        self.finishfunc = finished
        self.showMessage.emit(_('Pulling from %s...') % urlu)
        cmdline = ['--repository', self.repo.root, 'pull', '--verbose']
        uimerge = self.repo.ui.configbool('tortoisehg', 'autoresolve') \
            and 'ui.merge=internal:merge' or 'ui.merge=internal:fail'
        if self.cachedpp == 'rebase':
            cmdline += ['--rebase', '--config', uimerge]
        elif self.cachedpp == 'update':
            cmdline += ['--update', '--config', uimerge]
        elif self.cachedpp == 'fetch':
            cmdline[2] = 'fetch'
        self.run(cmdline, ('force', 'branch', 'rev', 'bookmark'))

    def outclicked(self):
        self.syncStarted.emit()
        url = self.currentUrl(True)
        urlu = hglib.tounicode(url)
        self.showMessage.emit(_('Finding outgoing changesets to %s...') % urlu)
        if self.embedded and not self.opts.get('subrepos'):
            def verifyhash(hash):
                if len(hash) != 40:
                    return False
                bad = [c for c in hash if c not in '0123456789abcdef']
                return not bad
            def outputnodes(ret, data):
                if ret == 0:
                    nodes = [n for n in data.splitlines() if verifyhash(n)]
                    if nodes:
                        self.outgoingNodes.emit(nodes)
                    self.showMessage.emit(_('%d outgoing changesets to %s') %
                                          (len(nodes), urlu))
                elif ret == 1:
                    self.showMessage.emit(_('No outgoing changesets to %s') % urlu)
                else:
                    self.showMessage.emit(_('Outgoing to %s aborted, ret %d') % (urlu, ret))
            self.finishfunc = outputnodes
            cmdline = ['--repository', self.repo.root, 'outgoing', '--quiet',
                       '--template', '{node}\n']
            self.run(cmdline, ('force', 'branch', 'rev'))
        else:
            self.finishfunc = None
            cmdline = ['--repository', self.repo.root, 'outgoing']
            self.run(cmdline, ('force', 'branch', 'rev', 'subrepos'))

    def p4pending(self):
        p4url = self.currentUrl(False)
        def finished(ret, output):
            pending = {}
            if ret == 0:
                for line in output.splitlines():
                    if line.startswith('ignoring hg revision'):
                        continue
                    try:
                        hashes = line.split(' ')
                        changelist = hashes.pop(0)
                        clnum = int(changelist)
                        if len(hashes)>1 and len(hashes[0])==1:
                            state = hashes.pop(0)
                            if state == 's':
                                changelist = _('%s (submitted)') % changelist
                            elif state == 'p':
                                changelist = _('%s (pending)') % changelist
                            else:
                                raise ValueError
                            pending[changelist] = hashes
                    except (ValueError, IndexError):
                        text = _('Unable to parse p4pending output')
                if pending:
                    text = _('%d pending changelists found') % len(pending)
                else:
                    text = _('No pending Perforce changelists')
            elif ret is None:
                text = _('Aborted p4pending')
            else:
                text = _('Unable to determine pending changesets')
            self.showMessage.emit(text)
            if pending:
                from tortoisehg.hgqt.p4pending import PerforcePending
                dlg = PerforcePending(self.repo, pending, p4url, self)
                dlg.showMessage.connect(self.showMessage)
                dlg.output.connect(self.output)
                dlg.makeLogVisible.connect(self.makeLogVisible)
                dlg.exec_()
        self.finishfunc = finished
        self.showMessage.emit(_('Perforce pending...'))
        self.run(['--repository', self.repo.root, 'p4pending', '--verbose'], ())

    def pushclicked(self, confirm, rev=None, branch=None):
        validopts = ('force', 'new-branch', 'branch', 'rev', 'bookmark')
        self.syncStarted.emit()
        url = self.currentUrl(True)
        urlu = hglib.tounicode(url)
        if (not hg.islocal(self.currentUrl(False)) and confirm
            and not self.targetcheckbox.isChecked()):
            r = qtlib.QuestionMsgBox(_('Confirm Push to remote Repository'),
                                     _('Push to remote repository\n%s\n?')
                                     % urlu, parent=self)
            if not r:
                self.showMessage.emit(_('Push to %s aborted') % urlu)
                self.pushCompleted.emit()
                return

        self.showMessage.emit(_('Pushing to %s...') % urlu)
        def finished(ret, output):
            if ret == 0:
                self.showMessage.emit(_('Push to %s completed') % urlu)
            else:
                self.showMessage.emit(_('Push to %s aborted, ret %d') % (urlu, ret))
                if self.needNewBranch:
                    r = qtlib.QuestionMsgBox(_('Confirm New Branch'),
                                             _('One or more of the changesets that you '
                                               'are attempting to push involve the '
                                               'creation of a new branch.  Do you want '
                                               'to create a new branch in the remote '
                                               'repository?'), parent=self)
                    if r:
                        cmdline = self.lastcmdline
                        cmdline.extend(['--new-branch'])
                        self.run(cmdline, validopts)
                        return
            self.pushCompleted.emit()
        self.finishfunc = finished
        cmdline = ['--repository', self.repo.root, 'push']
        if rev:
            cmdline.extend(['--rev', str(rev)])
        if branch:
            cmdline.extend(['--branch', branch])
        self.needNewBranch = False
        self.run(cmdline, validopts)

    def postpullclicked(self):
        dlg = PostPullDialog(self.repo, self)
        dlg.setWindowFlags(Qt.Sheet)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.exec_()

    def emailclicked(self):
        self.showMessage.emit(_('Determining outgoing changesets to email...'))
        def outputnodes(ret, data):
            if ret == 0:
                nodes = [n for n in data.splitlines() if len(n) == 40]
                self.showMessage.emit(_('%d outgoing changesets') %
                                        len(nodes))
                try:
                    outgoingrevs = [cmdline[cmdline.index('--rev') + 1]]
                except ValueError:
                    outgoingrevs = None
                from tortoisehg.hgqt import run as _run
                _run.email(ui.ui(), repo=self.repo, rev=nodes,
                           outgoing=True, outgoingrevs=outgoingrevs)
            elif ret == 1:
                self.showMessage.emit(_('No outgoing changesets'))
            else:
                self.showMessage.emit(_('Outgoing aborted, ret %d') % ret)
        self.finishfunc = outputnodes
        cmdline = ['--repository', self.repo.root, 'outgoing', '--quiet',
                    '--template', '{node}\n']
        self.run(cmdline, ('force', 'branch', 'rev'))

    def unbundle(self):
        caption = _("Select bundle file")
        _FILE_FILTER = "%s" % _("Bundle files (*.hg)")
        bundlefile = QFileDialog.getOpenFileName(parent=self, caption=caption,
                                    directory=self.repo.root,
                                    filter=_FILE_FILTER)
        if bundlefile:
            # Select the "Local" scheme
            self.schemecombo.setCurrentIndex(0)
            # Set the pull source to the selected bundle file
            self.pathentry.setText(bundlefile)
            # Execute the incomming command, which will show the revisions in
            # the bundle, and let the user accept or reject them
            self.inclicked()

    @pyqtSlot(QString)
    def removeAlias(self, alias):
        alias = hglib.fromunicode(alias)
        fn = self.repo.join('hgrc')
        fn, cfg = hgrcutil.loadIniFile([fn], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to remove URL'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        if alias in cfg['paths']:
            del cfg['paths'][alias]
        self.repo.incrementBusyCount()
        try:
            wconfig.writefile(cfg, fn)
        except EnvironmentError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(str(e)), parent=self)
        self.repo.decrementBusyCount()


class PostPullDialog(QDialog):
    def __init__(self, repo, parent):
        super(PostPullDialog, self).__init__(parent)
        self.repo = repo
        layout = QVBoxLayout()
        self.setLayout(layout)
        self.setWindowTitle(_('Post Pull Behavior'))
        self.setWindowFlags(self.windowFlags() &
                            ~Qt.WindowContextHelpButtonHint)

        lbl = QLabel(_('Select post-pull operation for this repository'))
        layout.addWidget(lbl)

        self.none = QRadioButton(_('None - simply pull changesets'))
        self.update = QRadioButton(_('Update - pull, then try to update'))
        layout.addWidget(self.none)
        layout.addWidget(self.update)

        if 'fetch' in repo.extensions() or repo.postpull == 'fetch':
            if 'fetch' in repo.extensions():
                btntxt = _('Fetch - use fetch (auto merge pulled changes)')
            else:
                btntxt = _('Fetch - use fetch extension (fetch is not active!)')
            self.fetch = QRadioButton(btntxt)
            layout.addWidget(self.fetch)
        else:
            self.fetch = None
        if 'rebase' in repo.extensions() or repo.postpull == 'rebase':
            if 'rebase' in repo.extensions():
                btntxt = _('Rebase - rebase local commits above pulled changes')
            else:
                btntxt = _('Rebase - use rebase extension (rebase is not active!)')
            self.rebase = QRadioButton(btntxt)
            layout.addWidget(self.rebase)

        self.none.setChecked(True)
        if repo.postpull == 'update':
            self.update.setChecked(True)
        elif repo.postpull == 'fetch':
            self.fetch.setChecked(True)
        elif repo.postpull == 'rebase':
            self.rebase.setChecked(True)

        self.autoresolve_chk = QCheckBox(_('Automatically resolve merge conflicts '
                                           'where possible'))
        self.autoresolve_chk.setChecked(
            repo.ui.configbool('tortoisehg', 'autoresolve', False))
        layout.addWidget(self.autoresolve_chk)

        cfglabel = QLabel(_('<a href="config">Launch settings tool...</a>'))
        cfglabel.linkActivated.connect(self.linkactivated)
        layout.addWidget(cfglabel)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Save|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        self.bb = bb
        layout.addWidget(bb)

    def linkactivated(self, command):
        if command == 'config':
            from tortoisehg.hgqt.settings import SettingsDialog
            sd = SettingsDialog(configrepo=False, focus='tortoisehg.postpull',
                            parent=self, root=self.repo.root)
            sd.exec_()

    def getValue(self):
        if self.none.isChecked():
            return 'none'
        elif self.update.isChecked():
            return 'update'
        elif (self.fetch and self.fetch.isChecked()):
            return 'fetch'
        else:
            return 'rebase'

    def accept(self):
        path = self.repo.join('hgrc')
        fn, cfg = hgrcutil.loadIniFile([path], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save post pull operation'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        self.repo.incrementBusyCount()
        try:
            cfg.set('tortoisehg', 'postpull', self.getValue())
            cfg.set('tortoisehg', 'autoresolve',
                    self.autoresolve_chk.isChecked())
            wconfig.writefile(cfg, fn)
        except EnvironmentError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(str(e)), parent=self)
        self.repo.decrementBusyCount()
        super(PostPullDialog, self).accept()

    def reject(self):
        super(PostPullDialog, self).reject()

class SaveDialog(QDialog):
    def __init__(self, repo, alias, origurl, safeurl, parent):
        super(SaveDialog, self).__init__(parent)

        self.setWindowTitle(_('Save Path'))
        self.setWindowFlags(self.windowFlags() &
                            ~Qt.WindowContextHelpButtonHint)

        self.repo = repo
        self.origurl = origurl
        self.setLayout(QFormLayout(fieldGrowthPolicy=QFormLayout.ExpandingFieldsGrow))

        self.aliasentry = QLineEdit(hglib.tounicode(alias))
        self.aliasentry.selectAll()
        self.layout().addRow(_('Alias'), self.aliasentry)

        self.urllabel = QLabel(hglib.tounicode(safeurl))
        self.layout().addRow(_('URL'), self.urllabel)

        user, host, port, folder, passwd, scheme = parseurl(origurl)
        if (user or passwd) and scheme in ('http', 'https'):
            cleanurl = hglib.removeauth(origurl)
            def showurl(showclean):
                newurl = showclean and cleanurl or safeurl
                self.urllabel.setText(hglib.tounicode(newurl))
            self.cleanurl = cleanurl
            self.clearcb = QCheckBox(_('Remove authentication data from URL'))
            self.clearcb.setToolTip(
                _('User authentication data should be associated with the '
                  'hostname using the security dialog.'))
            self.clearcb.toggled.connect(showurl)
            self.clearcb.setChecked(True)
            self.layout().addRow(self.clearcb)
        else:
            self.clearcb = None

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Save|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Save).setAutoDefault(True)
        self.bb = bb
        self.layout().addRow(None, bb)

        QTimer.singleShot(0, lambda:self.aliasentry.setFocus())

    def accept(self):
        fn = self.repo.join('hgrc')
        fn, cfg = hgrcutil.loadIniFile([fn], self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save an URL'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return
        alias = hglib.fromunicode(self.aliasentry.text())
        if self.clearcb and self.clearcb.isChecked():
            path = self.cleanurl
        else:
            path = self.origurl
        if alias in cfg['paths']:
            if not qtlib.QuestionMsgBox(_('Confirm URL replace'),
                    _('%s already exists, replace URL?') % alias, parent=self):
                return
        cfg.set('paths', alias, path)
        self.repo.incrementBusyCount()
        try:
            wconfig.writefile(cfg, fn)
        except EnvironmentError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(str(e)), parent=self)
        self.repo.decrementBusyCount()
        super(SaveDialog, self).accept()

    def reject(self):
        super(SaveDialog, self).reject()

class SecureDialog(QDialog):
    def __init__(self, repo, origurl, parent):
        super(SecureDialog, self).__init__(parent)

        def genfingerprint():
            try:
                pem = ssl.get_server_certificate( (host, port) )
                der = ssl.PEM_cert_to_DER_cert(pem)
            except Exception, e:
                qtlib.WarningMsgBox(_('Certificate Query Error'),
                                    hglib.tounicode(str(e)), parent=self)
                return
            hash = util.sha1(der).hexdigest()
            pretty = ":".join([hash[x:x + 2] for x in xrange(0, len(hash), 2)])
            le.setText(pretty)

        user, host, port, folder, passwd, scheme = parseurl(origurl)
        if port is None:
            port = 443
        else:
            port = int(port)
        uhost = hglib.tounicode(host)
        self.setWindowTitle(_('Security: ') + uhost)
        self.setWindowFlags(self.windowFlags() & \
                            ~Qt.WindowContextHelpButtonHint)

        # if the already user has an [auth] configuration for this URL, use it
        cleanurl = hglib.removeauth(origurl)
        res = hglib.readauthforuri(repo.ui, cleanurl, user)
        if res:
            self.alias, auth = res
        else:
            self.alias, auth = host, {}
        self.repo = repo
        self.host = host
        if cleanurl.startswith('svn+https://'):
            self.schemes = 'svn+https'
        else:
            self.schemes = None

        self.setLayout(QVBoxLayout())
        self.layout().addWidget(QLabel(_('<b>Host:</b> %s') % uhost))

        securebox = QGroupBox(_('Secure HTTPS Connection'))
        self.layout().addWidget(securebox)
        vbox = QVBoxLayout()
        securebox.setLayout(vbox)
        self.layout().addWidget(securebox)

        self.cacertradio = QRadioButton(
            _('Verify with Certificate Authority certificates (best)'))
        self.fprintradio = QRadioButton(
            _('Verify with stored host fingerprint (good)'))
        self.insecureradio = QRadioButton(
            _('No host validation, but still encrypted (bad)'))
        hbox = QHBoxLayout()
        fprint = repo.ui.config('hostfingerprints', host, '')
        self.fprintentry = le = QLineEdit(fprint)
        self.fprintradio.toggled.connect(self.fprintentry.setEnabled)
        self.fprintentry.setEnabled(False)
        if hasattr(le, 'setPlaceholderText'): # Qt >= 4.7
            le.setPlaceholderText(_('### host certificate fingerprint ###'))
        hbox.addWidget(le)
        try:
            import ssl # Python 2.6 or backport for 2.5
            qb = QPushButton(_('Query'))
            qb.clicked.connect(genfingerprint)
            qb.setEnabled(False)
            self.fprintradio.toggled.connect(qb.setEnabled)
            hbox.addWidget(qb)
        except ImportError:
            pass
        vbox.addWidget(self.cacertradio)
        vbox.addWidget(self.fprintradio)
        vbox.addLayout(hbox)
        vbox.addWidget(self.insecureradio)

        self.cacertradio.setEnabled(bool(repo.ui.config('web', 'cacerts')))
        self.cacertradio.setChecked(True) # default
        if fprint:
            self.fprintradio.setChecked(True)
        elif repo.ui.config('insecurehosts', host):
            self.insecureradio.setChecked(True)

        authbox = QGroupBox(_('User Authentication'))
        form = QFormLayout()
        authbox.setLayout(form)
        self.layout().addWidget(authbox)

        self.userentry = QLineEdit(user or auth.get('username', ''))
        self.userentry.setToolTip(
_('''Optional. Username to authenticate with. If not given, and the remote
site requires basic or digest authentication, the user will be prompted for
it. Environment variables are expanded in the username letting you do
foo.username = $USER.'''))
        form.addRow(_('Username'), self.userentry)

        self.pwentry = QLineEdit(passwd or auth.get('password', ''))
        self.pwentry.setEchoMode(QLineEdit.Password)
        self.pwentry.setToolTip(
_('''Optional. Password to authenticate with. If not given, and the remote
site requires basic or digest authentication, the user will be prompted for
it.'''))
        form.addRow(_('Password'), self.pwentry)
        if 'mercurial_keyring' in repo.extensions():
            self.pwentry.clear()
            self.pwentry.setEnabled(False)
            self.pwentry.setToolTip(_('Mercurial keyring extension is enabled. '
                 'Passwords will be stored in a platform-native '
                 'secure method.'))

        self.keyentry = QLineEdit(auth.get('key', ''))
        self.keyentry.setToolTip(
_('''Optional. PEM encoded client certificate key file. Environment variables
are expanded in the filename.'''))
        form.addRow(_('User Certificate Key File'), self.keyentry)

        self.chainentry = QLineEdit(auth.get('cert', ''))
        self.chainentry.setToolTip(
_('''Optional. PEM encoded client certificate chain file. Environment variables
are expanded in the filename.'''))
        form.addRow(_('User Certificate Chain File'), self.chainentry)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Help|BB.Save|BB.Cancel)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        bb.helpRequested.connect(self.keyringHelp)
        self.bb = bb
        self.layout().addWidget(bb)

        self.userentry.selectAll()
        QTimer.singleShot(0, lambda:self.userentry.setFocus())

    def keyringHelp(self):
        qtlib.openhelpcontents('sync.html#security')

    def accept(self):
        path = hglib.user_rcpath()
        fn, cfg = hgrcutil.loadIniFile(path, self)
        if not hasattr(cfg, 'write'):
            qtlib.WarningMsgBox(_('Unable to save authentication'),
                   _('Iniparse must be installed.'), parent=self)
            return
        if fn is None:
            return

        def setorclear(section, item, value):
            if value:
                cfg.set(section, item, value)
            elif not value and item in cfg[section]:
                del cfg[section][item]

        if self.cacertradio.isChecked():
            fprint = None
            insecure = None
        elif self.fprintradio.isChecked():
            fprint = hglib.fromunicode(self.fprintentry.text())
            insecure = None
        else:
            fprint = None
            insecure = '1'
        setorclear('hostfingerprints', self.host, fprint)
        setorclear('insecurehosts', self.host, insecure)

        username = hglib.fromunicode(self.userentry.text())
        password = hglib.fromunicode(self.pwentry.text())
        key = hglib.fromunicode(self.keyentry.text())
        chain = hglib.fromunicode(self.chainentry.text())

        cfg.set('auth', self.alias+'.prefix', self.host)
        setorclear('auth', self.alias+'.username', username)
        setorclear('auth', self.alias+'.password', password)
        setorclear('auth', self.alias+'.key', key)
        setorclear('auth', self.alias+'.cert', chain)
        setorclear('auth', self.alias+'.schemes', self.schemes)

        self.repo.incrementBusyCount()
        try:
            wconfig.writefile(cfg, fn)
        except EnvironmentError, e:
            qtlib.WarningMsgBox(_('Unable to write configuration file'),
                                hglib.tounicode(str(e)), parent=self)
        self.repo.decrementBusyCount()
        super(SecureDialog, self).accept()

    def reject(self):
        super(SecureDialog, self).reject()


class PathsTree(QTreeView):
    removeAlias = pyqtSignal(QString)
    menuRequest = pyqtSignal(QPoint, QString, QString, bool)

    def __init__(self, parent, editable):
        QTreeView.__init__(self, parent)
        self.setSelectionMode(QTreeView.SingleSelection)
        self.editable = editable

    def contextMenuEvent(self, event):
        for index in self.selectedRows():
            alias = index.data(Qt.DisplayRole).toString()
            url = index.sibling(index.row(), 1).data(Qt.DisplayRole).toString()
            self.menuRequest.emit(event.globalPos(), url, alias, self.editable)
            return

    def keyPressEvent(self, event):
        if self.editable and event.matches(QKeySequence.Delete):
            self.deleteSelected()
        else:
            return super(PathsTree, self).keyPressEvent(event)

    def deleteSelected(self):
        for index in self.selectedRows():
            alias = index.data(Qt.DisplayRole).toString()
            r = qtlib.QuestionMsgBox(_('Confirm path delete'),
                    _('Delete %s from your repo configuration file?') % alias,
                    parent=self)
            if r:
                self.removeAlias.emit(alias)

    def selectedUrls(self):
        for index in self.selectedRows():
            yield index.sibling(index.row(), 1).data(Qt.DisplayRole).toString()

    def dragObject(self):
        urls = []
        for url in self.selectedUrls():
            u = QUrl()
            u.setPath(url)
            urls.append(u)
        if urls:
            d = QDrag(self)
            m = QMimeData()
            m.setUrls(urls)
            d.setMimeData(m)
            d.start(Qt.CopyAction)

    def mousePressEvent(self, event):
        self.pressPos = event.pos()
        self.pressTime = QTime.currentTime()
        return super(PathsTree, self).mousePressEvent(event)

    def mouseMoveEvent(self, event):
        d = event.pos() - self.pressPos
        if d.manhattanLength() < QApplication.startDragDistance():
            return QTreeView.mouseMoveEvent(self, event)
        elapsed = self.pressTime.msecsTo(QTime.currentTime())
        if elapsed < QApplication.startDragTime():
            return super(PathsTree, self).mouseMoveEvent(event)
        self.dragObject()
        return super(PathsTree, self).mouseMoveEvent(event)

    def selectedRows(self):
        return self.selectionModel().selectedRows()

class PathsModel(QAbstractTableModel):
    def __init__(self, pathlist, parent=None):
        QAbstractTableModel.__init__(self, parent)
        self.headers = (_('Alias'), _('URL'))
        self.rows = []
        for alias, path in pathlist:
            safepath = hglib.hidepassword(path)
            ualias = hglib.tounicode(alias)
            usafepath = hglib.tounicode(safepath)
            self.rows.append([ualias, usafepath, path])

    def rowCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.rows)

    def columnCount(self, parent):
        if parent.isValid():
            return 0 # no child
        return len(self.headers)

    def data(self, index, role):
        if not index.isValid():
            return QVariant()
        if role == Qt.DisplayRole:
            return QVariant(self.rows[index.row()][index.column()])
        return QVariant()

    def headerData(self, col, orientation, role):
        if role != Qt.DisplayRole or orientation != Qt.Horizontal:
            return QVariant()
        else:
            return QVariant(self.headers[col])

    def flags(self, index):
        flags = Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsDragEnabled
        return flags

    def realUrl(self, index):
        return self.rows[index.row()][2]



class OptionsDialog(QDialog):
    'Utility dialog for configuring uncommon options'
    def __init__(self, opts, parent):
        QDialog.__init__(self, parent)
        self.setWindowTitle(_('%s - sync options') % parent.repo.displayname)
        self.repo = parent.repo

        layout = QFormLayout()
        self.setLayout(layout)

        self.newbranchcb = QCheckBox(
            _('Allow push of a new branch (--new-branch)'))
        self.newbranchcb.setChecked(opts.get('new-branch', False))
        layout.addRow(self.newbranchcb, None)

        self.forcecb = QCheckBox(
            _('Force push or pull (override safety checks, --force)'))
        self.forcecb.setChecked(opts.get('force', False))
        layout.addRow(self.forcecb, None)

        self.subrepocb = QCheckBox(
            _('Recurse into subrepositories') + u' (--subrepos)')
        self.subrepocb.setChecked(opts.get('subrepos', False))
        layout.addRow(self.subrepocb, None)

        self.noproxycb = QCheckBox(
            _('Temporarily disable configured HTTP proxy'))
        self.noproxycb.setChecked(opts.get('noproxy', False))
        layout.addRow(self.noproxycb, None)
        proxy = self.repo.ui.config('http_proxy', 'host')
        self.noproxycb.setEnabled(bool(proxy))

        self.debugcb = QCheckBox(
            _('Emit debugging output (--debug)'))
        self.debugcb.setChecked(opts.get('debug', False))
        layout.addRow(self.debugcb, None)

        lbl = QLabel(_('Remote command:'))
        self.remotele = QLineEdit()
        if opts.get('remotecmd'):
            self.remotele.setText(hglib.tounicode(opts['remotecmd']))
        layout.addRow(lbl, self.remotele)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.bb = bb
        layout.addWidget(bb)

    def accept(self):
        outopts = {}
        for name, le in (('remotecmd', self.remotele),):
            outopts[name] = hglib.fromunicode(le.text()).strip()

        outopts['subrepos'] = self.subrepocb.isChecked()
        outopts['force'] = self.forcecb.isChecked()
        outopts['new-branch'] = self.newbranchcb.isChecked()
        outopts['noproxy'] = self.noproxycb.isChecked()
        outopts['debug'] = self.debugcb.isChecked()

        self.outopts = outopts
        QDialog.accept(self)


def run(ui, *pats, **opts):
    repo = thgrepo.repository(ui, path=paths.find_root())
    return SyncWidget(repo, None, **opts)
