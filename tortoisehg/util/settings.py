# settings.py - TortoiseHg dialog settings library
#
# Copyright 2007 TK Soh <teekaysoh@gmail.com>
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import os
import cPickle
from mercurial import util

class SimpleMRUList(object):
    def __init__(self, size=10, reflist=[], compact=True):
        self._size = size
        self._list = reflist
        if compact:
            self.compact()

    def __iter__(self):
        for elem in self._list:
            yield elem

    def add(self, val):
        if val in self._list:
            self._list.remove(val)
        self._list.insert(0, val)
        self.flush()

    def get_size(self):
        return self._size

    def set_size(self, size):
        self._size = size
        self.flush()

    def flush(self):
        while len(self._list) > self._size:
            del self._list[-1]

    def compact(self):
        ''' remove duplicate in list '''
        newlist = []
        for v in self._list:
            if v not in newlist:
                newlist.append(v)
        self._list[:] = newlist


class Settings(object):
    def __init__(self, appname, path=None):
        self._appname = appname
        self._data = {}
        self._path = path and path or self._get_path(appname)
        self._audit()
        self.read()

    def get_value(self, key, default=None, create=False):
        if key in self._data:
            return self._data[key]
        elif create:
            self._data[key] = default
        return default

    def set_value(self, key, value):
        self._data[key] = value

    def mrul(self, key, size=10):
        ''' wrapper method to create a most-recently-used (MRU) list '''
        ls = self.get_value(key, [], True)
        ml = SimpleMRUList(size=size, reflist=ls)
        return ml

    def get_keys(self):
        return self._data.keys()

    def get_appname(self):
        return self._appname

    def read(self):
        self._data.clear()
        if os.path.exists(self._path):
            try:
                f = file(self._path, 'rb')
                self._data = cPickle.loads(f.read())
                f.close()
            except Exception:
                pass

    def write(self):
        self._write(self._path, self._data)

    def _write(self, appname, data):
        s = cPickle.dumps(data)
        f = util.atomictempfile(appname, 'wb', None)
        f.write(s)
        try:
            f.close()
        except OSError:
            pass # silently ignore these errors

    def _get_path(self, appname):
        if os.name == 'nt':
            try:
                import pywintypes
                try:
                    from win32com.shell import shell, shellcon
                    appdir = shell.SHGetSpecialFolderPath(0, shellcon.CSIDL_APPDATA)
                except pywintypes.com_error:
                    appdir = os.environ['APPDATA']
            except ImportError:
                appdir = os.environ['APPDATA']
            return os.path.join(appdir, 'TortoiseHg', appname)
        else:
            home = os.path.expanduser('~')
            return os.path.join(home, '.tortoisehg', appname)

    def _audit(self):
        if os.path.exists(os.path.dirname(self._path)):
            return
        try:
            os.makedirs(os.path.dirname(self._path))
        except OSError:
            pass # silently ignore these errors
