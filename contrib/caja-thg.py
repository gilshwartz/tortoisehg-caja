# TortoiseHg plugin for Caja
#
# Copyright 2007 Steve Borho
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import gtk
import gobject
import caja
import matevfs
import os
import sys

thg_main     = 'thg'
idstr_prefix = 'HgCaja2'

if gtk.gtk_version < (2, 14, 0):
    # at least on 2.12.12, gtk widgets can be confused by control
    # char markups (like "&#x1;"), so use cgi.escape instead
    from cgi import escape as markup_escape_text
else:
    from gobject import markup_escape_text

try:
    from mercurial import demandimport
except ImportError:
    # workaround to use user's local python libs
    userlib = os.path.expanduser('~/lib/python')
    if os.path.exists(userlib) and userlib not in sys.path:
        sys.path.append(userlib)
    from mercurial import demandimport
demandimport.enable()

import subprocess
import urllib

from mercurial import hg, ui, match, util, error
from mercurial.node import short

def _thg_path():
    # check if caja-thg.py is a symlink first
    pfile = __file__
    if pfile.endswith('.pyc'):
        pfile = pfile[:-1]
    path = os.path.dirname(os.path.dirname(os.path.realpath(pfile)))
    thgpath = os.path.normpath(path)
    testpath = os.path.join(thgpath, 'tortoisehg')
    if os.path.isdir(testpath) and thgpath not in sys.path:
        sys.path.insert(0, thgpath)
_thg_path()

from tortoisehg.util import paths, debugthg, cachethg

if debugthg.debug('N'):
    debugf = debugthg.debugf
else:
    debugf = debugthg.debugf_No

# avoid breaking other Python caja extensions
demandimport.disable()

nofilecmds = 'about serve synch repoconfig userconfig merge unmerge'.split()

class HgExtensionDefault:

    def __init__(self):
        self.scanStack = []
        self.allvfs = {}
        self.inv_dirs = set()

        from tortoisehg.util import menuthg
        self.hgtk = paths.find_in_path(thg_main)
        self.menu = menuthg.menuThg()
        self.notify = os.path.expanduser('~/.tortoisehg/notify')
        try:
            f = open(self.notify, 'w')
            f.close()
            ds_uri = matevfs.get_uri_from_local_path(self.notify)
            self.gmon = matevfs.monitor_add(ds_uri,
                      matevfs.MONITOR_FILE, self.notified)
        except (matevfs.NotSupportedError, IOError), e:
            debugf('no notification because of %s', e)
            self.notify = ''

    def icon(self, iname):
        return paths.get_tortoise_icon(iname)

    def get_path_for_vfs_file(self, vfs_file, store=True):
        if vfs_file.get_uri_scheme() != 'file':
            return None
        path = urllib.unquote(vfs_file.get_uri()[7:])
        if vfs_file.is_gone():
            self.allvfs.pop(path, '')
            return None
        if store:
            self.allvfs[path] = vfs_file
        return path

    def get_vfs(self, path):
        vfs = self.allvfs.get(path, None)
        if vfs and vfs.is_gone():
            del self.allvfs[path]
            return None
        return vfs

    def get_repo_for_path(self, path):
        '''
        Find mercurial repository for vfs_file
        Returns hg.repo
        '''
        p = paths.find_root(path)
        if not p:
            return None
        try:
            return hg.repository(ui.ui(), path=p)
        except error.RepoError:
            return None
        except StandardError, e:
            debugf(e)
            return None

    def run_dialog(self, menuitem, hgtkcmd, cwd = None):
        '''
        hgtkcmd - hgtk subcommand
        '''
        if cwd: #bg
            self.files = []
        else:
            cwd = self.cwd
        repo = self.get_repo_for_path(cwd)

        cmdopts = [sys.executable, self.hgtk, hgtkcmd]

        if hgtkcmd not in nofilecmds and self.files:
            pipe = subprocess.PIPE
            cmdopts += ['--listfile', '-']
        else:
            pipe = None

        proc = subprocess.Popen(cmdopts, cwd=cwd, stdin=pipe, shell=False)
        if pipe:
            proc.stdin.write('\n'.join(self.files))
            proc.stdin.close()

    def buildMenu(self, vfs_files, bg):
        '''Build menu'''
        self.pos = 0
        self.files = []
        files = []
        for vfs_file in vfs_files:
            f = self.get_path_for_vfs_file(vfs_file)
            if f:
                files.append(f)
        if not files:
            return
        if bg or len(files) == 1 and vfs_files[0].is_directory():
            cwd = files[0]
            files = []
        else:
            cwd = os.path.dirname(files[0])
        repo = self.get_repo_for_path(cwd)
        if repo:
            menus = self.menu.get_commands(repo, cwd, files)
            self.files = files
        else:
            menus = self.menu.get_norepo_commands(cwd, files)
        self.cwd = cwd
        return self._buildMenu(menus)

    def _buildMenu(self, menus):
        '''Build one level of a menu'''
        items = []
        if self.files:
            passcwd = None
        else: #bg
            passcwd = self.cwd
        for menu_info in menus:
            idstr = '%s::%02d%s' % (idstr_prefix ,self.pos, menu_info.hgcmd)
            self.pos += 1
            if menu_info.isSep():
                # can not insert a separator till now
                pass
            elif menu_info.isSubmenu():
                if hasattr(caja, 'Menu'):
                    item = caja.MenuItem(idstr, menu_info.menutext,
                            menu_info.helptext)
                    submenu = caja.Menu()
                    item.set_submenu(submenu)
                    for subitem in self._buildMenu(menu_info.get_menus()):
                        submenu.append_item(subitem)
                    items.append(item)
                else: #submenu not suported
                    for subitem in self._buildMenu(menu_info.get_menus()):
                        items.append(subitem)
            else:
                if menu_info.state:
                    item = caja.MenuItem(idstr,
                                 menu_info.menutext,
                                 menu_info.helptext,
                                 self.icon(menu_info.icon))
                    item.connect('activate', self.run_dialog, menu_info.hgcmd,
                            passcwd)
                    items.append(item)
        return items

    def get_background_items(self, window, vfs_file):
        '''Build context menu for current directory'''
        if vfs_file and self.menu:
            return self.buildMenu([vfs_file], True)
        else:
            self.files = []

    def get_file_items(self, window, vfs_files):
        '''Build context menu for selected files/directories'''
        if vfs_files and self.menu:
            return self.buildMenu(vfs_files, False)

    def get_columns(self):
        return caja.Column(idstr_prefix + "::80hg_status",
                               "hg_status",
                               "Hg Status",
                               "Version control status"),

    def _get_file_status(self, localpath, repo=None):
        cachestate = cachethg.get_state(localpath, repo)
        cache2state = {cachethg.UNCHANGED:   ('default',   'clean'),
                       cachethg.ADDED:       ('new',       'added'),
                       cachethg.MODIFIED:    ('important', 'modified'),
                       cachethg.UNKNOWN:     (None,        'unrevisioned'),
                       cachethg.IGNORED:     ('noread',    'ignored'),
                       cachethg.NOT_IN_REPO: (None,        'unrevisioned'),
                       cachethg.ROOT:        ('generic',   'root'),
                       cachethg.UNRESOLVED:  ('danger',    'unresolved')}
        emblem, status = cache2state.get(cachestate, (None, '?'))
        return emblem, status

    def notified(self, mon_uri=None, event_uri=None, event=None):
        debugf('notified from hgtk, %s', event, level='n')
        f = open(self.notify, 'a+')
        files = None
        try:
            files = [line[:-1] for line in f if line]
            if files:
                f.truncate(0)
        finally:
            f.close()
        if not files:
            return
        root = os.path.commonprefix(files)
        root = paths.find_root(root)
        if root:
            self.invalidate(files, root)

    def invalidate(self, paths, root = ''):
        started = bool(self.inv_dirs)
        if cachethg.cache_pdir == root and root not in self.inv_dirs:
            cachethg.overlay_cache.clear()
        self.inv_dirs.update([os.path.dirname(root), '/', ''])
        for path in paths:
            path = os.path.join(root, path)
            while path not in self.inv_dirs:
                self.inv_dirs.add(path)
                path = os.path.dirname(path)
                if cachethg.cache_pdir == path:
                    cachethg.overlay_cache.clear()
        if started:
            return
        if len(paths) > 1:
            self._invalidate_dirs()
        else:
            #group invalidation of directories
            gobject.timeout_add(200, self._invalidate_dirs)

    def _invalidate_dirs(self):
        for path in self.inv_dirs:
            vfs = self.get_vfs(path)
            if vfs:
                vfs.invalidate_extension_info()
        self.inv_dirs.clear()

    # property page borrowed from http://www.gnome.org/~gpoo/hg/caja-hg/
    def __add_row(self, row, label_item, label_value):
        label = gtk.Label(label_item)
        label.set_use_markup(True)
        label.set_alignment(1, 0)
        self.table.attach(label, 0, 1, row, row + 1, gtk.FILL, gtk.FILL, 0, 0)
        label.show()

        label = gtk.Label(label_value)
        label.set_use_markup(True)
        label.set_alignment(0, 1)
        label.show()
        self.table.attach(label, 1, 2, row, row + 1, gtk.FILL, 0, 0, 0)

    def get_property_pages(self, vfs_files):
        if len(vfs_files) != 1:
            return
        file = vfs_files[0]
        path = self.get_path_for_vfs_file(file)
        if path is None or file.is_directory():
            return
        repo = self.get_repo_for_path(path)
        if repo is None:
            return
        localpath = path[len(repo.root)+1:]
        emblem, status = self._get_file_status(path, repo)

        # Get the information from Mercurial
        ctx = repo['.']
        try:
            fctx = ctx.filectx(localpath)
            rev = fctx.filelog().linkrev(fctx.filerev())
        except:
            rev = ctx.rev()
        ctx = repo.changectx(rev)
        node = short(ctx.node())
        date = util.datestr(ctx.date(), '%Y-%m-%d %H:%M:%S %1%2')
        parents = '\n'.join([short(p.node()) for p in ctx.parents()])
        description = ctx.description()
        user = ctx.user()
        user = markup_escape_text(user)
        tags = ', '.join(ctx.tags())
        branch = ctx.branch()

        self.property_label = gtk.Label('Mercurial')

        self.table = gtk.Table(7, 2, False)
        self.table.set_border_width(5)
        self.table.set_row_spacings(5)
        self.table.set_col_spacings(5)

        self.__add_row(0, '<b>Status</b>:', status)
        self.__add_row(1, '<b>Last-Commit-Revision</b>:', str(rev))
        self.__add_row(2, '<b>Last-Commit-Description</b>:', description)
        self.__add_row(3, '<b>Last-Commit-Date</b>:', date)
        self.__add_row(4, '<b>Last-Commit-User</b>:', user)
        if tags:
            self.__add_row(5, '<b>Tags</b>:', tags)
        if branch != 'default':
            self.__add_row(6, '<b>Branch</b>:', branch)

        self.table.show()
        return caja.PropertyPage("MercurialPropertyPage::status",
                                     self.property_label, self.table),

class HgExtensionIcons(HgExtensionDefault):

    def update_file_info(self, file):
        '''Queue file for emblem and hg status update'''
        self.scanStack.append(file)
        if len(self.scanStack) == 1:
            gobject.idle_add(self.fileinfo_on_idle)

    def fileinfo_on_idle(self):
        '''Update emblem and hg status for files when there is time'''
        if not self.scanStack:
            return False
        try:
            vfs_file = self.scanStack.pop()
            path = self.get_path_for_vfs_file(vfs_file, False)
            if not path:
                return True
            oldvfs = self.get_vfs(path)
            if oldvfs and oldvfs != vfs_file:
                #file has changed on disc (not invalidated)
                self.get_path_for_vfs_file(vfs_file) #save new vfs
                self.invalidate([os.path.dirname(path)])
            emblem, status = self._get_file_status(path)
            if emblem is not None:
                vfs_file.add_emblem(emblem)
            vfs_file.add_string_attribute('hg_status', status)
        except StandardError, e:
            debugf(e)
        return True

if ui.ui().configbool("tortoisehg", "overlayicons", default = True):
    class HgExtension(HgExtensionIcons, caja.MenuProvider, caja.ColumnProvider, caja.PropertyPageProvider, caja.InfoProvider):
        pass
else:
    class HgExtension(HgExtensionDefault, caja.MenuProvider, caja.ColumnProvider, caja.PropertyPageProvider):
        pass
