# graft.py - Graft dialog for TortoiseHg
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

import os

from mercurial import util, merge as mergemod

from tortoisehg.util import hglib
from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib, cmdui, resolve, commit, thgrepo
from tortoisehg.hgqt import csinfo, cslist

BB = QDialogButtonBox

class GraftDialog(QDialog):
    showMessage = pyqtSignal(QString)

    def __init__(self, repo, parent, **opts):
        super(GraftDialog, self).__init__(parent)
        self.setWindowIcon(qtlib.geticon('hg-transplant'))
        f = self.windowFlags()
        self.setWindowFlags(f & ~Qt.WindowContextHelpButtonHint)
        self.repo = repo
        self._graftstatefile = self.repo.join('graftstate')
        self.opts = opts
        self.aborted = False
        self.valid = True

        destrev = opts.get('dest', '.')
        def cleanrevlist(revlist):
            return [self.repo[rev].rev() for rev in revlist]
        self.sourcelist = cleanrevlist(opts.get('source', ['.']))
        currgraftrevs = self.graftstate()
        if currgraftrevs:
            currgraftrevs = cleanrevlist(currgraftrevs)
            if self.sourcelist != currgraftrevs:
                res = qtlib.CustomPrompt(_('Interrupted graft operation found'),
                    _('An interrupted graft operation has been found.\n\n'
                      'You cannot perform a different graft operation unless '
                      'you abort the interrupted graft operation first.'),
                    self,
                    (_('Continue or abort interrupted graft operation?'),
                     _('Cancel')), 1, 2).run()
                if res != 0:
                    # Cancel
                    self.valid = False
                    return
                # Continue creating the dialog, but use the graft source
                # of the existing, interrupted graft as the source, rather than
                # the one that was passed as an option to the dialog constructor
                self.sourcelist = currgraftrevs

        box = QVBoxLayout()
        box.setSpacing(8)
        box.setContentsMargins(*(6,)*4)
        self.setLayout(box)

        if len(self.sourcelist) > 1:
            listlabel = qtlib.LabeledSeparator(
                _('Graft %d changesets on top of changeset %s') \
                % (len(self.sourcelist), destrev))
            self.layout().addWidget(listlabel)
            self.cslist = cslist.ChangesetList(self.repo)
            self.cslist.update(self.sourcelist)
            self.layout().addWidget(self.cslist)

        style = csinfo.panelstyle(selectable=True)
        self.srcb = srcb = QGroupBox()
        srcb.setLayout(QVBoxLayout())
        srcb.layout().setContentsMargins(*(2,)*4)

        self.source = csinfo.create(self.repo, None, style, withupdate=True)
        self._updateSource(0)
        srcb.layout().addWidget(self.source)
        self.layout().addWidget(srcb)

        destb = QGroupBox( _('To graft destination'))
        destb.setLayout(QVBoxLayout())
        destb.layout().setContentsMargins(*(2,)*4)
        dest = csinfo.create(self.repo, destrev, style, withupdate=True)
        destb.layout().addWidget(dest)
        self.destcsinfo = dest
        self.layout().addWidget(destb)

        sep = qtlib.LabeledSeparator(_('Options'))
        self.layout().addWidget(sep)

        self.autoresolvechk = QCheckBox(_('Automatically resolve merge conflicts '
                                           'where possible'))
        self.autoresolvechk.setChecked(
            repo.ui.configbool('tortoisehg', 'autoresolve', False))
        self.layout().addWidget(self.autoresolvechk)

        self.cmd = cmdui.Widget(True, True, self)
        self.cmd.commandFinished.connect(self.commandFinished)
        self.showMessage.connect(self.cmd.stbar.showMessage)
        self.cmd.stbar.linkActivated.connect(self.linkActivated)
        self.layout().addWidget(self.cmd, 2)

        bbox = QDialogButtonBox()
        self.cancelbtn = bbox.addButton(QDialogButtonBox.Cancel)
        self.cancelbtn.clicked.connect(self.reject)
        self.graftbtn = bbox.addButton(_('Graft'),
                                            QDialogButtonBox.ActionRole)
        self.graftbtn.clicked.connect(self.graft)
        self.abortbtn = bbox.addButton(_('Abort'),
                                            QDialogButtonBox.ActionRole)
        self.abortbtn.clicked.connect(self.abort)
        self.layout().addWidget(bbox)
        self.bbox = bbox

        if self.checkResolve():
            self.abortbtn.setEnabled(True)
        else:
            self.showMessage.emit(_('Checking...'))
            self.abortbtn.setEnabled(False)
            self.graftbtn.setEnabled(False)
            QTimer.singleShot(0, self.checkStatus)

        self.setMinimumWidth(480)
        self.setMaximumHeight(800)
        self.resize(0, 340)
        self.setWindowTitle(_('Graft - %s') % self.repo.displayname)

    def _updateSourceTitle(self, idx):
        numrevs = len(self.sourcelist)
        if numrevs <= 1:
            title = _('Graft changeset')
        else:
            title = _('Graft changeset #%d of %d') % (idx + 1, numrevs)
        self.srcb.setTitle(title)

    def _updateSource(self, idx):
        self._updateSourceTitle(idx)
        self.source.update(self.repo[self.sourcelist[idx]])

    def checkStatus(self):
        repo = self.repo
        class CheckThread(QThread):
            def __init__(self, parent):
                QThread.__init__(self, parent)
                self.dirty = False

            def run(self):
                wctx = repo[None]
                if len(wctx.parents()) > 1:
                    self.dirty = True
                elif wctx.dirty():
                    self.dirty = True
                else:
                    for r, p, status in thgrepo.recursiveMergeStatus(repo):
                        if status == 'u':
                            self.dirty = True
                            break
        def completed():
            self.th.wait()
            if self.th.dirty:
                self.graftbtn.setEnabled(False)
                txt = _('Before graft, you must <a href="commit">'
                        '<b>commit</b></a> or <a href="discard">'
                        '<b>discard</b></a> changes.')
            else:
                self.graftbtn.setEnabled(True)
                txt = _('You may continue or start the graft')
            self.showMessage.emit(txt)
        self.th = CheckThread(self)
        self.th.finished.connect(completed)
        self.th.start()

    def graft(self):
        self.graftbtn.setEnabled(False)
        self.cancelbtn.setShown(False)
        cmdline = ['graft', '--repository', self.repo.root]
        cmdline += ['--config', 'ui.merge=internal:' +
                    (self.autoresolvechk.isChecked() and 'merge' or 'fail')]
        if os.path.exists(self._graftstatefile):
            cmdline += ['--continue']
        else:
            for source in self.sourcelist:
                cmdline += [str(source)]
        self.repo.incrementBusyCount()
        self.cmd.run(cmdline)

    def abort(self):
        self.abortbtn.setDisabled(True)
        if os.path.exists(self._graftstatefile):
            # Remove the existing graftstate file!
            os.remove(self._graftstatefile)
        cmdline = ['update', '--repository', self.repo.root, '--clean', '--rev', 'p1()']
        self.repo.incrementBusyCount()
        self.aborted = True
        self.cmd.run(cmdline)

    def graftstate(self):
        graftstatefile = self.repo.join('graftstate')
        if os.path.exists(graftstatefile):
            f = open(graftstatefile, 'r')
            info = f.readlines()
            f.close()
            if len(info):
                revlist = [rev.strip() for rev in info]
                revlist = [rev for rev in revlist if rev != '']
                if revlist:
                    return revlist
        return None

    def commandFinished(self, ret):
        self.repo.decrementBusyCount()
        if  self.aborted or self.checkResolve() is False:
            msg = _('Graft is complete')
            if self.aborted:
                msg = _('Graft aborted')
            elif ret == 255:
                msg = _('Graft failed')
                self.cmd.setShowOutput(True)  # contains hint
            else:
                self._updateSource(len(self.sourcelist) - 1)
            self.showMessage.emit(msg)
            self.graftbtn.setEnabled(True)
            self.graftbtn.setText(_('Close'))
            self.graftbtn.clicked.disconnect(self.graft)
            self.graftbtn.clicked.connect(self.accept)

    def checkResolve(self):
        for root, path, status in thgrepo.recursiveMergeStatus(self.repo):
            if status == 'u':
                txt = _('Graft generated merge <b>conflicts</b> that must '
                        'be <a href="resolve"><b>resolved</b></a>')
                self.graftbtn.setEnabled(False)
                break
        else:
            self.graftbtn.setEnabled(True)
            txt = _('You may continue the graft')
        self.showMessage.emit(txt)

        currgraftrevs = self.graftstate()
        if currgraftrevs:
            def findrev(rev, revlist):
                rev = self.repo[rev].rev()
                for n, r in enumerate(revlist):
                    r = self.repo[r].rev()
                    if rev == r:
                        return n
                return None
            idx = findrev(currgraftrevs[0], self.sourcelist)
            if idx is not None:
                self._updateSource(idx)
            self.abortbtn.setEnabled(True)
            self.graftbtn.setText('Continue')
            return True
        else:
            self.abortbtn.setEnabled(False)
            return False

    def linkActivated(self, cmd):
        if cmd == 'resolve':
            dlg = resolve.ResolveDialog(self.repo, self)
            dlg.exec_()
            self.checkResolve()
        elif cmd == 'commit':
            dlg = commit.CommitDialog(self.repo, [], {}, self)
            dlg.finished.connect(dlg.deleteLater)
            dlg.exec_()
            self.destcsinfo.update(self.repo['.'])
            self.checkStatus()
        elif cmd == 'discard':
            labels = [(QMessageBox.Yes, _('&Discard')),
                      (QMessageBox.No, _('Cancel'))]
            if not qtlib.QuestionMsgBox(_('Confirm Discard'),
                     _('Discard outstanding changes to working directory?'),
                     labels=labels, parent=self):
                return
            def finished(ret):
                self.repo.decrementBusyCount()
                if ret == 0:
                    self.checkStatus()
            cmdline = ['update', '--clean', '--repository', self.repo.root,
                       '--rev', '.']
            self.runner = cmdui.Runner(True, self)
            self.runner.commandFinished.connect(finished)
            self.repo.incrementBusyCount()
            self.runner.run(cmdline)

    def reject(self):
        if os.path.exists(self._graftstatefile):
            main = _('Exiting with an unfinished graft is not recommended.')
            text = _('Consider aborting the graft first.')
            labels = ((QMessageBox.Yes, _('&Exit')),
                      (QMessageBox.No, _('Cancel')))
            if not qtlib.QuestionMsgBox(_('Confirm Exit'), main, text,
                                        labels=labels, parent=self):
                return
        super(GraftDialog, self).reject()

def run(ui, *revs, **opts):
    from tortoisehg.util import paths
    repo = thgrepo.repository(ui, path=paths.find_root())

    revs = list(revs)
    revs.extend(opts['rev'])

    if os.path.exists(repo.join('graftstate')):
        qtlib.InfoMsgBox(_('Graft already in progress'),
                          _('Resuming graft already in progress'))
    elif not revs:
        qtlib.ErrorMsgBox(_('Abort'),
                          _('You must provide revisions to graft'))
        import sys; sys.exit()
    return GraftDialog(repo, None, source=revs)
