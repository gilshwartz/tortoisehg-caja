# lexers.py - select Qsci lexer for a filename and contents
#
# Copyright 2010 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

import re

from PyQt4 import Qsci
from PyQt4.QtGui import *

from tortoisehg.hgqt import qtlib

class _LexerSelector(object):
    _lexer = None
    def match(self, filename, filedata):
        return False

    def lexer(self, parent):
        """
        Return a configured instance of the lexer
        """
        return self.cfg_lexer(self._lexer(parent))

    def cfg_lexer(self, lexer):
        font = qtlib.getfont('fontlog').font()
        lexer.setFont(font, -1)
        return lexer

class _FilenameLexerSelector(_LexerSelector):
    """
    Base class for lexer selector based on file name matching
    """
    extensions = ()
    def match(self, filename, filedata):
        filename = filename.lower()
        for ext in self.extensions:
            if filename.endswith(ext):
                return True
        return False

class _ScriptLexerSelector(_FilenameLexerSelector):
    """
    Base class for lexer selector based on content pattern matching
    """
    regex = None
    headersize = 3
    def match(self, filename, filedata):
        if super(_ScriptLexerSelector, self).match(filename, filedata):
            return True
        if self.regex and filedata:
            for line in filedata.splitlines()[:self.headersize]:
                if len(line)<1000 and self.regex.match(line):
                    return True
        return False

class PythonLexerSelector(_ScriptLexerSelector):
    extensions = ('.py', '.pyw')
    _lexer = Qsci.QsciLexerPython
    regex = re.compile(r'^#[!].*python')

class BashLexerSelector(_ScriptLexerSelector):
    extensions = ('.sh', '.bash')
    _lexer = Qsci.QsciLexerBash
    regex = re.compile(r'^#[!].*sh')

class PerlLexerSelector(_ScriptLexerSelector):
    extensions = ('.pl', '.perl')
    _lexer = Qsci.QsciLexerPerl
    regex = re.compile(r'^#[!].*perl')

class RubyLexerSelector(_ScriptLexerSelector):
    extensions = ('.rb', '.ruby')
    _lexer = Qsci.QsciLexerRuby
    regex = re.compile(r'^#[!].*ruby')

class LuaLexerSelector(_ScriptLexerSelector):
    extensions = ('.lua', )
    _lexer = Qsci.QsciLexerLua
    regex = None

class CppLexerSelector(_FilenameLexerSelector):
    extensions = ('.c', '.cpp', '.cxx', '.h', '.hpp', '.hxx')
    _lexer = Qsci.QsciLexerCPP

class CSSLexerSelector(_FilenameLexerSelector):
    extensions = ('.css',)
    _lexer = Qsci.QsciLexerCSS

class XMLLexerSelector(_FilenameLexerSelector):
    extensions = ('.xhtml', '.xml', '.csproj', 'app.config', 'web.config')
    _lexer = Qsci.QsciLexerXML

class HTMLLexerSelector(_FilenameLexerSelector):
    extensions = ('.htm', '.html')
    _lexer = Qsci.QsciLexerHTML

class VerilogLexerSelector(_FilenameLexerSelector):
    extensions = ('.v', '.vh')
    _lexer = Qsci.QsciLexerVerilog

class VHDLLexerSelector(_FilenameLexerSelector):
    extensions = ('.vhd', '.vhdl')
    _lexer = Qsci.QsciLexerVHDL

class BatchLexerSelector(_FilenameLexerSelector):
    extensions = ('.cmd', '.bat')
    _lexer = Qsci.QsciLexerBatch

class MakeLexerSelector(_FilenameLexerSelector):
    extensions = ('.mk', 'makefile')
    _lexer = Qsci.QsciLexerMakefile

class SQLLexerSelector(_FilenameLexerSelector):
    extensions = ('.sql',)
    _lexer = Qsci.QsciLexerSQL

class JSLexerSelector(_FilenameLexerSelector):
    extensions = ('.js',)
    _lexer = Qsci.QsciLexerJavaScript

class JavaLexerSelector(_FilenameLexerSelector):
    extensions = ('.java',)
    _lexer = Qsci.QsciLexerJava

class TeXLexerSelector(_FilenameLexerSelector):
    extensions = ('.tex', '.latex',)
    _lexer = Qsci.QsciLexerTeX

class CSharpLexerSelector(_FilenameLexerSelector):
    extensions = ('.cs')
    _lexer = Qsci.QsciLexerCSharp

class DiffLexerSelector(_ScriptLexerSelector):
    extensions = ()
    _lexer = Qsci.QsciLexerDiff
    regex = re.compile(r'^@@ [-]\d+,\d+ [+]\d+,\d+ @@$')
    def cfg_lexer(self, lexer):
        #lexer.setDefaultPaper(QtGui.QColor(cfg.getDiffBGColor()))
        #lexer.setColor(QtGui.QColor(cfg.getDiffFGColor()), -1)
        for label, i in (('diff.inserted', 6),
                         ('diff.deleted', 5),
                         ('diff.hunk', 4)):
            effect = qtlib.geteffect(label)
            for e in effect.split(';'):
                if e.startswith('color:'):
                    lexer.setColor(QColor(e[7:]), i)
                if e.startswith('background-color:'):
                    lexer.setEolFill(True, i)
                    lexer.setPaper(QColor(e[18:]), i)
        font = qtlib.getfont('fontdiff').font()
        lexer.setFont(font, -1)
        return lexer


lexers = []
for clsname, cls in globals().items():
    if clsname.startswith('_'):
        continue
    if isinstance(cls, type) and issubclass(cls, _LexerSelector):
        #print clsname
        lexers.append(cls())

def get_diff_lexer(parent):
    return DiffLexerSelector().lexer(parent)

def get_lexer(filename, filedata, parent):
    for lselector in lexers:
        if lselector.match(filename, filedata):
            return lselector.lexer(parent)
    return None
