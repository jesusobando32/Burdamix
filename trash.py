"""Sends a file to the Windows Recycle Bin, so that deleting a song from the library can be undone.

SHFileOperationW with FOF_ALLOWUNDO moves the file to the bin. When the bin cannot take a file (too big, a drive without one)
Windows would delete it for good without a word; FOF_WANTNUKEWARNING makes it ask first instead, and a "no" comes back as an
aborted operation, which is reported as a failure. The file is checked to be really gone afterwards."""
import ctypes
import os
import sys

FO_DELETE = 0x0003
FOF_SILENT = 0x0004
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
MAX_PATH = 259


class TrashError(Exception):
    """The file could not be sent to the bin; the message is plain Spanish for the window."""


class _FileOp(ctypes.Structure):
    _pack_ = 1 if ctypes.sizeof(ctypes.c_void_p) == 4 else 0      # the header packs the 32-bit layout tightly
    _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", ctypes.c_uint), ("pFrom", ctypes.c_wchar_p), ("pTo", ctypes.c_wchar_p),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", ctypes.c_int), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", ctypes.c_wchar_p)]


def move_to_recycle_bin(path):
    if not isinstance(path, str) or not os.path.isabs(path) or path.startswith("\\\\?\\"):
        raise TrashError("No pude identificar el archivo.")
    path = os.path.normpath(path)                                          # the shell wants backslashes
    if not os.path.isfile(path):
        raise TrashError("El archivo ya no está en su sitio.")
    if sys.platform != "win32":
        raise TrashError("La Papelera de Reciclaje solo está disponible en Windows.")
    if len(path) > MAX_PATH:
        raise TrashError("La ruta del archivo es demasiado larga para la Papelera.")
    operation = _FileOp()
    operation.wFunc = FO_DELETE
    operation.pFrom = path + "\0"                                          # the list of files ends with two nulls
    operation.fFlags = FOF_ALLOWUNDO | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    code = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if code != 0 or operation.fAnyOperationsAborted:
        raise TrashError("Windows no pudo mandar el archivo a la Papelera (puede estar en uso).")
    if os.path.exists(path):
        raise TrashError("El archivo sigue en su sitio: puede estar en uso.")
