# pathedit.py
#
# Copyright 2010 Adrian Buehlmann <adrian@cadifra.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2 or any later version.

from PyQt4.QtCore import *
from PyQt4.QtGui import *

from tortoisehg.hgqt.i18n import _


class PathEditDialog(QDialog):

    def __init__(self, parent, alias, url_):
        super(PathEditDialog, self).__init__(parent)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        layout = QVBoxLayout()

        self.setLayout(layout)
        self.setWindowTitle(_("Edit Repository URL"))

        form = QFormLayout()
        layout.addLayout(form)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.edit = QLineEdit(url_)
        form.addRow(alias, self.edit)

        BB = QDialogButtonBox
        bb = QDialogButtonBox(BB.Ok|BB.Cancel)
        layout.addWidget(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(BB.Ok).setDefault(True)

        self.setMinimumWidth(400)
        h = self.sizeHint().height() + 6
        self.setMaximumHeight(h)
        self.setMinimumHeight(h)

    def accept(self):
        QDialog.accept(self)

    def reject(self):
        QDialog.reject(self)

    def url(self):
        return str(self.edit.text())
