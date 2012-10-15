# setup.py
# A distutils setup script to install TortoiseHg in Windows and Posix
# environments.
#
# On Windows, this script is mostly used to build a stand-alone
# TortoiseHg package.  See installer\build.txt for details. The other
# use is to report the current version of the TortoiseHg source.


import time
import sys
import os
import shutil
import subprocess
import cgi
import tempfile
import re
from fnmatch import fnmatch
from distutils import log
from distutils.core import setup, Command
from distutils.command.build import build as _build_orig
from distutils.command.clean import clean as _clean_orig
from distutils.dep_util import newer, newer_group
from distutils.spawn import spawn, find_executable
from os.path import isdir, exists, join, walk, splitext
from i18n.msgfmt import Msgfmt

thgcopyright = 'Copyright (C) 2010 Steve Borho and others'
hgcopyright = 'Copyright (C) 2005-2010 Matt Mackall and others'

class build_mo(Command):

    description = "build translations (.mo files)"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        podir = 'i18n/tortoisehg'
        if not os.path.isdir(podir):
            self.warn("could not find %s/ directory" % podir)
            return

        join = os.path.join
        for po in os.listdir(podir):
            if not po.endswith('.po'):
                continue
            pofile = join(podir, po)
            modir = join('locale', po[:-3], 'LC_MESSAGES')
            mofile = join(modir, 'tortoisehg.mo')
            modata = Msgfmt(pofile).get()
            self.mkpath(modir)
            open(mofile, "wb").write(modata)

class update_pot(Command):

    description = "extract translatable strings to tortoisehg.pot"
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        if not find_executable('xgettext'):
            self.warn("could not find xgettext executable, tortoisehg.pot"
                      "won't be built")
            return

        dirlist = [
            '.',
            'contrib',
            'contrib/win32',
            'tortoisehg',
            'tortoisehg/hgqt',
            'tortoisehg/util',
            'tortoisehg/thgutil/iniparse',
            ]

        filelist = []
        for pathname in dirlist:
            if not os.path.exists(pathname):
                continue
            for filename in os.listdir(pathname):
                if filename.endswith('.py'):
                    filelist.append(os.path.join(pathname, filename))
        filelist.sort()

        potfile = 'tortoisehg.pot'

        cmd = [
            'xgettext',
            '--package-name', 'TortoiseHg',
            '--msgid-bugs-address', '<thg-devel@googlegroups.com>',
            '--copyright-holder', thgcopyright,
            '--from-code', 'ISO-8859-1',
            '--keyword=_:1,2c,2t',
            '--add-comments=i18n:',
            '-d', '.',
            '-o', potfile,
            ]
        cmd += filelist
        self.make_file(filelist, potfile, spawn, (cmd,))

class build_qt(Command):
    description = "build PyQt GUIs (.ui) and resources (.qrc)"
    user_options = [('force', 'f', 'forcibly compile everything'
                     ' (ignore file timestamps)'),
                    ('frozen', None, 'include resources for frozen exe')]
    boolean_options = ('force', 'frozen')

    def initialize_options(self):
        self.force = None
        self.frozen = False

    def finalize_options(self):
        self.set_undefined_options('build', ('force', 'force'))

    def compile_ui(self, ui_file, py_file=None):
        # Search for pyuic4 in python bin dir, then in the $Path.
        if py_file is None:
            py_file = splitext(ui_file)[0] + "_ui.py"
        if not(self.force or newer(ui_file, py_file)):
            return
        try:
            from PyQt4 import uic
            fp = open(py_file, 'w')
            uic.compileUi(ui_file, fp)
            fp.close()
            log.info('compiled %s into %s' % (ui_file, py_file))
        except Exception, e:
            self.warn('Unable to compile user interface %s: %s' % (py_file, e))
            if not exists(py_file) or not file(py_file).read():
                raise SystemExit(1)
            return

    def compile_rc(self, qrc_file, py_file=None):
        # Search for pyuic4 in python bin dir, then in the $Path.
        if py_file is None:
            py_file = splitext(qrc_file)[0] + "_rc.py"
        if not(self.force or newer(qrc_file, py_file)):
            return
        import PyQt4
        origpath = os.getenv('PATH')
        path = origpath.split(os.pathsep)
        pyqtfolder = os.path.dirname(PyQt4.__file__)
        path.append(os.path.join(pyqtfolder, 'bin'))
        os.putenv('PATH', os.pathsep.join(path))
        if os.system('pyrcc4 "%s" -o "%s"' % (qrc_file, py_file)) > 0:
            self.warn("Unable to generate python module %s for resource file %s"
                      % (py_file, qrc_file))
            if not exists(py_file) or not file(py_file).read():
                raise SystemExit(1)
        else:
            log.info('compiled %s into %s' % (qrc_file, py_file))
        os.putenv('PATH', origpath)

    def _generate_qrc(self, qrc_file, srcfiles, prefix):
        basedir = os.path.dirname(qrc_file)
        f = open(qrc_file, 'w')
        try:
            f.write('<!DOCTYPE RCC><RCC version="1.0">\n')
            f.write('  <qresource prefix="%s">\n' % cgi.escape(prefix))
            for e in srcfiles:
                relpath = e[len(basedir) + 1:]
                f.write('    <file>%s</file>\n'
                        % cgi.escape(relpath.replace(os.path.sep, '/')))
            f.write('  </qresource>\n')
            f.write('</RCC>\n')
        finally:
            f.close()

    def build_rc(self, py_file, basedir, prefix='/'):
        """Generate compiled resource including any files under basedir"""
        # For details, see http://doc.qt.nokia.com/latest/resources.html
        qrc_file = os.path.join(basedir, '%s.qrc' % os.path.basename(basedir))
        srcfiles = [os.path.join(root, e)
                    for root, _dirs, files in os.walk(basedir) for e in files]
        # NOTE: Here we cannot detect deleted files. In such case, we need
        # to remove .qrc manually.
        if not (self.force or newer_group(srcfiles, py_file)):
            return
        try:
            self._generate_qrc(qrc_file, srcfiles, prefix)
            self.compile_rc(qrc_file, py_file)
        finally:
            os.unlink(qrc_file)

    def _build_translations(self, basepath):
        """Build translations_rc.py which inclues qt_xx.qm"""
        from PyQt4.QtCore import QLibraryInfo
        trpath = unicode(QLibraryInfo.location(QLibraryInfo.TranslationsPath))
        d = tempfile.mkdtemp()
        try:
            for e in os.listdir(trpath):
                if re.match(r'qt_[a-z]{2}(_[A-Z]{2})?\.ts$', e):
                    r = os.system('lrelease "%s" -qm "%s"'
                                  % (os.path.join(trpath, e),
                                     os.path.join(d, e[:-3] + '.qm')))
                    if r > 0:
                        self.warn('Unable to generate Qt message file'
                                  ' from %s' % e)
            self.build_rc(os.path.join(basepath, 'translations_rc.py'),
                          d, '/translations')
        finally:
            shutil.rmtree(d)

    def run(self):
        self._wrapuic()
        basepath = join(os.path.dirname(__file__), 'tortoisehg', 'hgqt')
        self.build_rc(os.path.join(basepath, 'icons_rc.py'),
                      os.path.join(os.path.dirname(__file__), 'icons'),
                      '/icons')
        if self.frozen:
            self._build_translations(basepath)
        for dirpath, _, filenames in os.walk(basepath):
            for filename in filenames:
                if filename.endswith('.ui'):
                    self.compile_ui(join(dirpath, filename))
                elif filename.endswith('.qrc'):
                    self.compile_rc(join(dirpath, filename))

    _wrappeduic = False
    @classmethod
    def _wrapuic(cls):
        """wrap uic to use gettext's _() in place of tr()"""
        if cls._wrappeduic:
            return

        from PyQt4.uic.Compiler import compiler, qtproxies, indenter

        class _UICompiler(compiler.UICompiler):
            def createToplevelWidget(self, classname, widgetname):
                o = indenter.getIndenter()
                o.level = 0
                o.write('from tortoisehg.hgqt.i18n import _')
                return super(_UICompiler, self).createToplevelWidget(classname, widgetname)
        compiler.UICompiler = _UICompiler

        class _i18n_string(qtproxies.i18n_string):
            def __str__(self):
                return "_('%s')" % self.string.encode('string-escape')
        qtproxies.i18n_string = _i18n_string

        cls._wrappeduic = True

class clean_local(Command):
    pats = ['*.py[co]', '*_ui.py', '*_rc.py', '*.mo', '*.orig', '*.rej']
    excludedirs = ['.hg', 'build', 'dist']
    description = 'clean up generated files (%s)' % ', '.join(pats)
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        for e in self._walkpaths('.'):
            log.info("removing '%s'" % e)
            os.remove(e)

    def _walkpaths(self, path):
        for root, _dirs, files in os.walk(path):
            if any(root == join(path, e) or root.startswith(join(path, e, ''))
                   for e in self.excludedirs):
                continue
            for e in files:
                fpath = join(root, e)
                if any(fnmatch(fpath, p) for p in self.pats):
                    yield fpath

class build(_build_orig):
    sub_commands = [
        ('build_qt', None),
        ('build_mo', None),
        ] + _build_orig.sub_commands

class clean(_clean_orig):
    sub_commands = [
        ('clean_local', None),
        ] + _clean_orig.sub_commands

    def run(self):
        _clean_orig.run(self)
        for e in self.get_sub_commands():
            self.run_command(e)

cmdclass = {
        'build': build,
        'build_qt': build_qt ,
        'build_mo': build_mo ,
        'clean': clean,
        'clean_local': clean_local,
        'update_pot': update_pot ,
    }

def setup_windows(version):
    # Specific definitios for Windows NT-alike installations
    _scripts = []
    _data_files = []
    _packages = ['tortoisehg.hgqt', 'tortoisehg.util', 'tortoisehg']
    extra = {}
    hgextmods = []

    # py2exe needs to be installed to work
    try:
        import py2exe

        # Help py2exe to find win32com.shell
        try:
            import modulefinder
            import win32com
            for p in win32com.__path__[1:]: # Take the path to win32comext
                modulefinder.AddPackagePath("win32com", p)
            pn = "win32com.shell"
            __import__(pn)
            m = sys.modules[pn]
            for p in m.__path__[1:]:
                modulefinder.AddPackagePath(pn, p)
        except ImportError:
            pass

    except ImportError:
        if '--version' not in sys.argv:
            raise

    # Allow use of environment variables to specify the location of Mercurial
    import modulefinder
    path = os.getenv('MERCURIAL_PATH')
    if path:
        modulefinder.AddPackagePath('mercurial', path)
    path = os.getenv('HGEXT_PATH')
    if path:
        modulefinder.AddPackagePath('hgext', path)

    if 'py2exe' in sys.argv:
        import hgext
        hgextdir = os.path.dirname(hgext.__file__)
        hgextmods = set(["hgext." + os.path.splitext(f)[0]
                      for f in os.listdir(hgextdir)])
        _data_files = [(root, [os.path.join(root, file_) for file_ in files])
                            for root, dirs, files in os.walk('icons')]

    # for PyQt, see http://www.py2exe.org/index.cgi/Py2exeAndPyQt
    includes = ['sip']

    # Qt4 plugins, see http://stackoverflow.com/questions/2206406/
    def qt4_plugins(subdir, *dlls):
        import PyQt4
        pluginsdir = join(os.path.dirname(PyQt4.__file__), 'plugins')
        return (subdir, [join(pluginsdir, subdir, e) for e in dlls])
    _data_files.append(qt4_plugins('imageformats', 'qico4.dll', 'qsvg4.dll'))

    # Manually include other modules py2exe can't find by itself.
    if 'hgext.highlight' in hgextmods:
        includes += ['pygments.*', 'pygments.lexers.*', 'pygments.formatters.*',
                     'pygments.filters.*', 'pygments.styles.*']
    if 'hgext.patchbomb' in hgextmods:
        includes += ['email.*', 'email.mime.*']

    extra['options'] = {
       "py2exe" : {
           "skip_archive" : 0,

           # Don't pull in all this MFC stuff used by the makepy UI.
           "excludes" : "pywin,pywin.dialogs,pywin.dialogs.list"
                        ",setup,distutils",  # required only for in-place use
           "includes" : includes,
           "optimize" : 1
       }
    }
    shutil.copyfile('thg', 'thgw')
    extra['console'] = [
            {'script':'thg',
             'icon_resources':[(0,'icons/thg_logo.ico')],
             'description':'TortoiseHg GUI tools for Mercurial SCM',
             'copyright':thgcopyright,
             'product_version':version},
            {'script':'contrib/hg',
             'icon_resources':[(0,'icons/hg.ico')],
             'description':'Mercurial Distributed SCM',
             'copyright':hgcopyright,
             'product_version':version},
            {'script':'win32/docdiff.py',
             'icon_resources':[(0,'icons/TortoiseMerge.ico')],
             'copyright':thgcopyright,
             'product_version':version}
            ]
    extra['windows'] = [
            {'script':'thgw',
             'icon_resources':[(0,'icons/thg_logo.ico')],
             'description':'TortoiseHg GUI tools for Mercurial SCM',
             'copyright':thgcopyright,
             'product_version':version},
            {'script':'TortoiseHgOverlayServer.py',
             'icon_resources':[(0,'icons/thg_logo.ico')],
             'description':'TortoiseHg Overlay Icon Server',
             'copyright':thgcopyright,
             'product_version':version}
            ]

    return _scripts, _packages, _data_files, extra


def setup_posix():
    # Specific definitios for Posix installations
    _extra = {}
    _scripts = ['thg']
    _packages = ['tortoisehg', 'tortoisehg.hgqt', 'tortoisehg.util']
    _data_files = [(os.path.join('share/pixmaps/tortoisehg', root),
        [os.path.join(root, file_) for file_ in files])
        for root, dirs, files in os.walk('icons')]
    _data_files += [(os.path.join('share', root),
        [os.path.join(root, file_) for file_ in files])
        for root, dirs, files in os.walk('locale')]
    _data_files += [('/usr/share/caja-python/extensions/',
                     ['contrib/caja-thg.py'])]

    # Create a config.py.  Distributions will need to supply their own
    cfgfile = os.path.join('tortoisehg', 'util', 'config.py')
    if not os.path.exists(cfgfile) and not os.path.exists('.hg/requires'):
        f = open(cfgfile, "w")
        f.write('bin_path     = "/usr/bin"\n')
        f.write('license_path = "/usr/share/doc/tortoisehg/Copying.txt.gz"\n')
        f.write('locale_path  = "/usr/share/locale"\n')
        f.write('icon_path    = "/usr/share/pixmaps/tortoisehg/icons"\n')
        f.write('nofork       = True\n')
        f.close()

    return _scripts, _packages, _data_files, _extra

def runcmd(cmd, env):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=env)
    out, err = p.communicate()
    # If root is executing setup.py, but the repository is owned by
    # another user (as in "sudo python setup.py install") we will get
    # trust warnings since the .hg/hgrc file is untrusted. That is
    # fine, we don't want to load it anyway.
    err = [e for e in err.splitlines()
           if not e.startswith('Not trusting file')]
    if err:
        return ''
    return out

if __name__ == '__main__':
    version = ''

    if os.path.isdir('.hg'):
        from tortoisehg.util import version as _version
        branch, version = _version.liveversion()
        if version.endswith('+'):
            version += time.strftime('%Y%m%d')
    elif os.path.exists('.hg_archival.txt'):
        kw = dict([t.strip() for t in l.split(':', 1)]
                  for l in open('.hg_archival.txt'))
        if 'tag' in kw:
            version =  kw['tag']
        elif 'latesttag' in kw:
            version = '%(latesttag)s+%(latesttagdistance)s-%(node).12s' % kw
        else:
            version = kw.get('node', '')[:12]

    if version:
        f = open("tortoisehg/util/__version__.py", "w")
        f.write('# this file is autogenerated by setup.py\n')
        f.write('version = "%s"\n' % version)
        f.close()

    try:
        import tortoisehg.util.__version__
        version = tortoisehg.util.__version__.version
    except ImportError:
        version = 'unknown'

    if os.name == "nt":
        (scripts, packages, data_files, extra) = setup_windows(version)
        desc = 'Windows shell extension for Mercurial VCS'
        # Windows binary file versions for exe/dll files must have the
        # form W.X.Y.Z, where W,X,Y,Z are numbers in the range 0..65535
        from tortoisehg.util.version import package_version
        setupversion = package_version()
        productname = 'TortoiseHg'
    else:
        (scripts, packages, data_files, extra) = setup_posix()
        desc = 'TortoiseHg dialogs for Mercurial VCS'
        setupversion = version
        productname = 'tortoisehg'

    setup(name=productname,
            version=setupversion,
            author='Steve Borho',
            author_email='steve@borho.org',
            url='http://tortoisehg.org',
            description=desc,
            license='GNU GPL2',
            scripts=scripts,
            packages=packages,
            data_files=data_files,
            cmdclass=cmdclass,
            **extra
        )
