# i18n.py - internationalization support for TortoiseHg
#
# Copyright 2010 Yuki KODAMA <endflow.net@gmail.com>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

from tortoisehg.util.i18n import _ as _gettext
from tortoisehg.util.i18n import ngettext as _ngettext
from tortoisehg.util.i18n import agettext

def _(message, context=''):
    return unicode(_gettext(message, context), 'utf-8')

def ngettext(singular, plural, n):
    return unicode(_ngettext(singular, plural, n), 'utf-8')

class localgettext(object):
    def _(self, message, context=''):
        return agettext(message, context='')

class keepgettext(object):
    def _(self, message, context=''):
        return {'id': message, 'str': _(message, context)}
