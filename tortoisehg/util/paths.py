# paths.py - TortoiseHg path utilities
#
# Copyright 2009 Steve Borho <steve@borho.org>
#
# This software may be used and distributed according to the terms of the
# GNU General Public License version 2, incorporated herein by reference.

try:
    from config import icon_path, bin_path, license_path, locale_path
except ImportError:
    icon_path, bin_path, license_path, locale_path = None, None, None, None

import os, sys

def find_root(path=None):
    p = path or os.getcwd()
    while not os.path.isdir(os.path.join(p, ".hg")):
        oldp = p
        p = os.path.dirname(p)
        if p == oldp:
            return None
        if not os.access(p, os.R_OK):
            return None
    return p

def get_tortoise_icon(icon):
    "Find a tortoisehg icon"
    icopath = os.path.join(get_icon_path(), icon)
    if os.path.isfile(icopath):
        return icopath
    else:
        print 'icon not found', icon
        return None

def get_icon_path():
    global icon_path
    return icon_path or os.path.join(get_prog_root(), 'icons')

def get_license_path():
    global license_path
    return license_path or os.path.join(get_prog_root(), 'COPYING.txt')

def get_locale_path():
    global locale_path
    return locale_path or os.path.join(get_prog_root(), 'locale')

if os.name == 'nt':
    import _winreg
    import win32net
    import win32api
    import win32file

    def find_in_path(pgmname):
        "return first executable found in search path"
        global bin_path
        ospath = os.environ['PATH'].split(os.pathsep)
        ospath.insert(0, bin_path or get_prog_root())
        pathext = os.environ.get('PATHEXT', '.COM;.EXE;.BAT;.CMD')
        pathext = pathext.lower().split(os.pathsep)
        for path in ospath:
            ppath = os.path.join(path, pgmname)
            for ext in pathext:
                if os.path.exists(ppath + ext):
                    return ppath + ext
        return None

    def get_prog_root():
        if getattr(sys, 'frozen', False):
            try:
                return _winreg.QueryValue(_winreg.HKEY_LOCAL_MACHINE,
                                          r"Software\TortoiseHg")
            except:
                pass
        return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))

    def is_on_fixed_drive(path):
        if hasattr(os.path, 'splitunc'):
            unc, rest = os.path.splitunc(path)
            if unc:
                # All UNC paths (\\host\mount) are considered not-fixed
                return False
        drive, remain = os.path.splitdrive(path)
        if drive:
            return win32file.GetDriveType(drive) == win32file.DRIVE_FIXED
        else:
            return False

    USE_OK  = 0     # network drive status

    def netdrive_status(drive):
        """
        return True if a network drive is accessible (connected, ...),
        or False if <drive> is not a network drive
        """
        if hasattr(os.path, 'splitunc'):
            unc, rest = os.path.splitunc(drive)
            if unc: # All UNC paths (\\host\mount) are considered nonlocal
                return True
        letter = os.path.splitdrive(drive)[0].upper()
        _drives, total, _ = win32net.NetUseEnum(None, 1, 0)
        for drv in _drives:
            if drv['local'] == letter:
                info = win32net.NetUseGetInfo(None, letter, 1)
                return info['status'] == USE_OK
        return False

else: # Not Windows

    def find_in_path(pgmname):
        """ return first executable found in search path """
        global bin_path
        ospath = os.environ['PATH'].split(os.pathsep)
        ospath.insert(0, bin_path or get_prog_root())
        for path in ospath:
            ppath = os.path.join(path, pgmname)
            if os.access(ppath, os.X_OK):
                return ppath
        return None

    def get_prog_root():
        path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        return path

    def netdrive_status(drive):
        """
        return True if a network drive is accessible (connected, ...),
        or False if <drive> is not a network drive
        """
        return False

    def is_on_fixed_drive(path):
        return True

