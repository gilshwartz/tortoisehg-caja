# customtools.py - Settings panel and configuration dialog for TortoiseHg custom tools
#
# This module implements 3 main classes:
#
# 1. A ToolsFrame which is meant to be shown on the settings dialog
# 2. A ToolList widget, part of the ToolsFrame, showing a list of
#    configured custom tools
# 3. A CustomToolConfigDialog, that can be used to add a new or
#    edit an existing custom tool
#
# The ToolsFrame and specially the ToolList must implement some methods
# which are common to all settings widgets.
#
# Copyright 2012 Angel Ezquerra <angel.ezquerra@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from mercurial import ui

from tortoisehg.hgqt.i18n import _
from tortoisehg.hgqt import qtlib
from tortoisehg.util import hglib

from PyQt4.QtCore import *
from PyQt4.QtGui import *


class ToolsFrame(QFrame):
    def __init__(self, ini, parent=None, **opts):
        QFrame.__init__(self, parent, **opts)
        self.widgets = []
        self.ini = ini
        self.tortoisehgtools, guidef = hglib.tortoisehgtools(self.ini)
        self.setValue(self.tortoisehgtools)

        # The frame has a header and 3 columns:
        # - The header shows a combo with the list of locations
        # - The columns show:
        #     - The current location tool list and its associated buttons
        #     - The add to list button
        #     - The "available tools" list and its associated buttons
        topvbox = QVBoxLayout()
        self.setLayout(topvbox)

        topvbox.addWidget(QLabel(_('Select a GUI location to edit:')))

        self.locationcombo = QComboBox(self,
            toolTip='Select the toolbar or menu to change')

        def selectlocation(index):
            location = self.locationcombo.itemText(index)
            for widget in self.widgets:
                if widget.location == location:
                    widget.removeInvalid(self.value())
                    widget.show()
                else:
                    widget.hide()
        self.locationcombo.currentIndexChanged.connect(selectlocation)
        topvbox.addWidget(self.locationcombo)

        hbox = QHBoxLayout()
        topvbox.addLayout(hbox)
        vbox = QVBoxLayout()

        self.globaltoollist = ToolListBox(self.ini, minimumwidth=100,
                                          parent=self)
        self.globaltoollist.doubleClicked.connect(self.editToolItem)

        vbox.addWidget(QLabel(_('Tools shown on selected location')))
        for location in hglib.tortoisehgtoollocations:
            self.locationcombo.addItem(location)
            toollist = ToolListBox(self.ini, location=location,
                minimumwidth=100, parent=self)
            toollist.doubleClicked.connect(self.editToolFromName)
            vbox.addWidget(toollist)
            toollist.hide()
            self.widgets.append(toollist)

        deletefromlistbutton = QPushButton(_('Delete from list'), self)
        deletefromlistbutton.clicked.connect(
            lambda: self.forwardToCurrentToolList('deleteTool', remove=False))
        vbox.addWidget(deletefromlistbutton)
        hbox.addLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel('')) # to align all lists
        addtolistbutton = QPushButton('<< ' + _('Add to list') + ' <<', self)
        addtolistbutton.clicked.connect(self.addToList)
        addseparatorbutton = QPushButton('<< ' + _('Add separator'), self)
        addseparatorbutton.clicked.connect(
            lambda: self.forwardToCurrentToolList('addSeparator'))

        vbox.addWidget(addtolistbutton)
        vbox.addWidget(addseparatorbutton)
        vbox.addStretch()
        hbox.addLayout(vbox)

        vbox = QVBoxLayout()
        vbox.addWidget(QLabel(_('List of all tools')))
        vbox.addWidget(self.globaltoollist)
        newbutton = QPushButton(_('New Tool ...'), self)
        newbutton.clicked.connect(self.newTool)
        editbutton = QPushButton(_('Edit Tool ...'), self)
        editbutton.clicked.connect(lambda: self.editTool(row=None))
        deletebutton = QPushButton(_('Delete Tool'), self)
        deletebutton.clicked.connect(self.deleteCurrentTool)

        vbox.addWidget(newbutton)
        vbox.addWidget(editbutton)
        vbox.addWidget(deletebutton)
        hbox.addLayout(vbox)

        # Ensure that the first location list is shown
        selectlocation(0)

    def getCurrentToolList(self):
        index = self.locationcombo.currentIndex()
        location = self.locationcombo.itemText(index)
        for widget in self.widgets:
            if widget.location == location:
                return widget
        return None

    def addToList(self):
        gtl = self.globaltoollist
        row = gtl.currentIndex().row()
        if row < 0:
            row = 0
        item = gtl.item(row)
        if item is None:
            return
        toolname = item.text()
        self.forwardToCurrentToolList('addOrInsertItem', toolname)

    def forwardToCurrentToolList(self, funcname, *args, **opts):
        w = self.getCurrentToolList()
        if w is not None:
            getattr(w, funcname)(*args, **opts)
        return None

    def newTool(self):
        td = CustomToolConfigDialog(self)
        res = td.exec_()
        if res:
            toolname, toolconfig = td.value()
            self.globaltoollist.addOrInsertItem(toolname)
            self.tortoisehgtools[toolname] = toolconfig

    def editTool(self, row=None):
        gtl = self.globaltoollist
        if row is None:
            row = gtl.currentIndex().row()
        if row < 0:
            return self.newTool()
        else:
            item = gtl.item(row)
            toolname = item.text()
            td = CustomToolConfigDialog(
                self, toolname=toolname,
                toolconfig=self.tortoisehgtools[str(toolname)])
            res = td.exec_()
            if res:
                toolname, toolconfig = td.value()
                gtl.takeItem(row)
                gtl.insertItem(row, toolname)
                gtl.setCurrentRow(row)
                self.tortoisehgtools[toolname] = toolconfig

    def editToolItem(self, item):
        self.editTool(item.row())

    def editToolFromName(self, name):
        # [TODO] connect to toollist doubleClick (not global)
        gtl = self.globaltoollist
        if name == gtl.SEPARATOR:
            return
        guidef = gtl.values()
        for row, toolname in enumerate(guidef):
            if toolname == name:
                self.editTool(row)
                return

    def deleteCurrentTool(self):
        row = self.globaltoollist.currentIndex().row()
        if row >= 0:
            item = self.globaltoollist.item(row)
            itemtext = str(item.text())
            self.globaltoollist.deleteTool(row=row)

            self.deleteTool(itemtext)
            self.forwardToCurrentToolList('removeInvalid', self.value())

    def deleteTool(self, name):
        try:
            del self.tortoisehgtools[name]
        except KeyError:
            pass

    def applyChanges(self, ini):
        # widget.value() returns the _NEW_ values
        # widget.curvalue returns the _ORIGINAL_ values (yes, this is a bit
        # misleading! "cur" means "current" as in currently valid)
        def updateIniValue(section, key, newvalue):
            section = hglib.fromunicode(section)
            key = hglib.fromunicode(key)
            try:
                del ini[section][key]
            except KeyError:
                pass
            if newvalue is not None:
                ini.set(section, key, newvalue)

        emitChanged = False
        if not self.isDirty():
            return emitChanged

        emitChanged = True
        # 1. Save the new tool configurations
        #
        # In order to keep the tool order we must delete all existing
        # custom tool configurations, and then set all the configuration
        # settings anew:
        section = 'tortoisehg-tools'
        fieldnames = ('command', 'label', 'tooltip',
                      'icon', 'location', 'enable', 'showoutput',)
        for name in self.curvalue:
            for field in fieldnames:
                try:
                    keyname = '%s.%s' % (name, field)
                    del ini[section][keyname]
                except KeyError:
                    pass

        tools = self.value()
        for uname in tools:
            name = hglib.fromunicode(uname)
            if name[0] in '|-':
                continue
            for field in sorted(tools[name]):
                keyname = '%s.%s' % (name, field)
                value = tools[name][field]
                if not value is '':
                    ini.set(section, keyname, value)

        # 2. Save the new guidefs
        for n, toollistwidget in enumerate(self.widgets):
            toollocation = self.locationcombo.itemText(n)
            if not toollistwidget.isDirty():
                continue
            emitChanged = True
            toollist = toollistwidget.value()

            updateIniValue('tortoisehg', toollocation, ' '.join(toollist))

        return emitChanged

    ## common APIs for all edit widgets
    def setValue(self, curvalue):
        self.curvalue = dict(curvalue)

    def value(self):
        return self.tortoisehgtools

    def isDirty(self):
        for toollistwidget in self.widgets:
            if toollistwidget.isDirty():
                return True
        if self.globaltoollist.isDirty():
            return True
        return self.tortoisehgtools != self.curvalue

    def refresh(self):
        self.tortoisehgtools, guidef = hglib.tortoisehgtools(self.ini)
        self.setValue(self.tortoisehgtools)
        self.globaltoollist.refresh()
        for w in self.widgets:
            w.refresh()


class ToolListBox(QListWidget):
    SEPARATOR = '------'
    def __init__(self, ini, parent=None, location=None, minimumwidth=None,
                 **opts):
        QListWidget.__init__(self, parent, **opts)
        self.opts = opts
        self.curvalue = None
        self.ini = ini
        self.location = location

        if minimumwidth:
            self.setMinimumWidth(minimumwidth)

        self.refresh()

        # Enable drag and drop to reorder the tools
        self.setDragEnabled(True)
        self.setDragDropMode(self.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)

    def _guidef2toollist(self, guidef):
        toollist = []
        for name in guidef:
            if name == '|':
                name = self.SEPARATOR
                # avoid putting multiple separators together
                if [name] == toollist[-1:]:
                    continue
            toollist.append(name)
        return toollist

    def _toollist2guidef(self, toollist):
        guidef = []
        for uname in toollist:
            if uname == self.SEPARATOR:
                name = '|'
                # avoid putting multiple separators together
                if [name] == toollist[-1:]:
                    continue
            else:
                name = hglib.fromunicode(uname)
            guidef.append(name)
        return guidef

    def addOrInsertItem(self, text):
        row = self.currentIndex().row()
        if row < 0:
            self.addItem(text)
            self.setCurrentRow(self.count()-1)
        else:
            self.insertItem(row+1, text)
            self.setCurrentRow(row+1)

    def deleteTool(self, row=None, remove=False):
        if row is None:
            row = self.currentIndex().row()
        if row >= 0:
            self.takeItem(row)

    def addSeparator(self):
        self.addOrInsertItem(self.SEPARATOR)

    def values(self):
        out = []
        for row in range(self.count()):
            out.append(self.item(row).text())
        return out

    ## common APIs for all edit widgets
    def setValue(self, curvalue):
        self.curvalue = curvalue

    def value(self):
        return self._toollist2guidef(self.values())

    def isDirty(self):
        return self.value() != self.curvalue

    def refresh(self):
        toolsdefs, guidef = hglib.tortoisehgtools(self.ini,
            selectedlocation=self.location)
        self.toollist = self._guidef2toollist(guidef)
        self.setValue(guidef)
        self.clear()
        self.addItems(self.toollist)

    def removeInvalid(self, validtools):
        validguidef = []
        for toolname in self.value():
            if toolname[0] not in '|-':
                if toolname not in validtools:
                    continue
            validguidef.append(toolname)
        self.setValue(validguidef)
        self.clear()
        self.addItems(self._guidef2toollist(validguidef))

class CustomToolConfigDialog(QDialog):
    'Dialog for editing the a custom tool configuration'

    _enablemappings = {'All items': 'istrue',
                        'Working Directory': 'iswd',
                        'All revisions': 'isrev',
                        'All contexts': 'isctx',
                        'Fixed revisions': 'fixed',
                        'Applied patches': 'applied',
                        'qgoto': 'qgoto'}

    def __init__(self, parent=None, toolname=None, toolconfig={}):
        QDialog.__init__(self, parent)

        self.setWindowIcon(qtlib.geticon('tools-spanner-hammer'))
        self.setWindowTitle('Configure Custom Tool')
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)

        self.hbox = QHBoxLayout()
        vbox = QVBoxLayout()

        command = toolconfig.get('command', '')
        label = toolconfig.get('label', '')
        tooltip = toolconfig.get('tooltip', '')
        ico = toolconfig.get('icon', '')
        enable = toolconfig.get('enable', 'all')
        showoutput = str(toolconfig.get('showoutput', False))

        self.name = self._addConfigItem(vbox, _('Tool name'),
            QLineEdit(toolname), _('The tool name. It cannot contain spaces.'))
            # Execute a mercurial command. These _MUST_ start with "hg"
        self.command = self._addConfigItem(vbox, _('Command'),
            QLineEdit(command), _('The command that will be executed.\n'
            'To execute a mercurial command use "hg" (rather than "hg.exe") '
            'as the executable command.\n'
            'You can use {ROOT} as an alias of the current repository root and\n'
            '{REV} as an alias of the selected revision.'))
        self.label = self._addConfigItem(vbox, _('Tool label'),
            QLineEdit(label),
            _('The tool label, which is what will be shown '
            'on the repowidget context menu.\n'
            'If no label is set, the tool name will be used as the tool label.\n'
            'If no tooltip is set, the label will be used as the tooltip as well.'))
        self.tooltip = self._addConfigItem(vbox, _('Tooltip'),
            QLineEdit(tooltip),
            _('The tooltip that will be shown on the tool button.\n'
            'This is only shown when the tool button is shown on\n'
            'the workbench toolbar.'))
        self.icon = self._addConfigItem(vbox, _('Icon'),
            QLineEdit(ico),
            _('The tool icon.\n'
            'You can use any built-in TortoiseHg icon\n'
            'by setting this value to a valid TortoiseHg icon name\n'
            '(e.g. clone, add, remove, sync, thg-logo, hg-update, etc).\n'
            'You can also set this value to the absolute path to\n'
            'any icon on your file system.'))

        combo = self._genCombo(self._enablemappings.keys(),
            self._enable2label(enable), 'All items')
        self.enable = self._addConfigItem(vbox, _('On repowidget, show for'),
            combo,  _('For which kinds of revisions the tool will be enabled\n'
            'It is only taken into account when the tool is shown on the\n'
            'selected revision context menu.'))

        combo = self._genCombo(('True', 'False'), showoutput)
        self.showoutput = self._addConfigItem(vbox, _('Show Output Log'),
            combo, _('When enabled, automatically show the Output Log when the '
            'command is run.\nDefault: False.'))

        self.hbox.addLayout(vbox)
        vbox = QVBoxLayout()
        self.okbutton = QPushButton(_('OK'))
        self.okbutton.clicked.connect(self.okClicked)
        vbox.addWidget(self.okbutton)
        self.cancelbutton = QPushButton(_('Cancel'))
        self.cancelbutton.clicked.connect(self.reject)
        vbox.addWidget(self.cancelbutton)
        vbox.addStretch()
        self.hbox.addLayout(vbox)
        self.setLayout(self.hbox)

    def value(self):
        toolname = str(self.name.text()).strip()
        toolconfig = {
            'label': str(self.label.text()),
            'command': str(self.command.text()),
            'tooltip': str(self.tooltip.text()),
            'icon': str(self.icon.text()),
            'enable': self._enablemappings[str(self.enable.currentText())],
            'showoutput': str(self.showoutput.currentText()),
        }
        return toolname, toolconfig

    def _genCombo(self, items, selecteditem=None, defaultitem=None):
        index = 0
        if selecteditem:
            try:
                index = items.index(selecteditem)
            except:
                if defaultitem:
                    try:
                        index = items.index(defaultitem)
                    except:
                        pass
        combo = QComboBox()
        combo.addItems(items)
        if index:
            combo.setCurrentIndex(index)
        return combo

    def _addConfigItem(self, parent, label, configwidget, tooltip=None):
        if tooltip:
            configwidget.setToolTip(tooltip)
        hbox = QHBoxLayout()
        hbox.addWidget(QLabel(label))
        hbox.addWidget(configwidget)
        parent.addLayout(hbox)
        return configwidget

    def _enable2label(self, label):
        return self._dictvalue2key(self._enablemappings, label)

    def _dictvalue2key(self, dictionary, value):
        for key in dictionary:
            if value == dictionary[key]:
                return key
        return None

    def okClicked(self):
        errormsg = self.validateForm()
        if errormsg:
            qtlib.WarningMsgBox(_('Missing information'), errormsg)
            return
        return self.accept()

    def validateForm(self):
        name, config = self.value()
        if not name:
            return _('You must set a tool name.')
        if name.find(' ') >= 0:
            return _('The tool name cannot have any spaces in it.')
        if not config['command']:
            return _('You must set a command to run.')
        return '' # No error
