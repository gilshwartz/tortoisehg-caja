# license.py - license dialog for TortoiseHg
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2007 Steve Borho <steve@borho.org>
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
# Copyright 2010 Johan Samyn <johan.samyn@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.
"""
TortoiseHg License dialog - PyQt4 version
"""


from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib
from tortoisehg.util import paths


class LicenseDialog(QDialog):
    """Dialog for showing the TortoiseHg license"""
    def __init__(self, parent=None):
        super(LicenseDialog, self).__init__(parent)

        self.setWindowIcon(qtlib.geticon('thg_logo'))
        self.setWindowTitle(_('License'))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(700, 400)

        self.lic_txt = QPlainTextEdit()
        self.lic_txt.setFont(QFont('Monospace'))
        self.lic_txt.setTextInteractionFlags(
                Qt.TextSelectableByKeyboard|Qt.TextSelectableByMouse)
        try:
            lic = open(paths.get_license_path(), 'rb').read()
            self.lic_txt.setPlainText(lic)
        except (IOError):
            pass

        self.hspacer = QSpacerItem(40, 20,
                QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.close_btn = QPushButton(_('&Close'))
        self.close_btn.clicked.connect(self.close)

        self.hbox = QHBoxLayout()
        self.hbox.addItem(self.hspacer)
        self.hbox.addWidget(self.close_btn)
        self.vbox = QVBoxLayout()
        self.vbox.setSpacing(6)
        self.vbox.addWidget(self.lic_txt)
        self.vbox.addLayout(self.hbox)

        self.setLayout(self.vbox)
        self._readsettings()
        self.setModal(True)

    def closeEvent(self, event):
        self._writesettings()
        super(LicenseDialog, self).closeEvent(event)

    def _readsettings(self):
        s = QSettings()
        self.restoreGeometry(s.value('license/geom').toByteArray())

    def _writesettings(self):
        s = QSettings()
        s.setValue('license/geom', self.saveGeometry())


def run(ui, *args, **opts):
    return LicenseDialog()
