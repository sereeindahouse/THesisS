"""Current-Windows-user DPAPI storage; never writes a plaintext API key.

The user requested retaining their existing key across local server restarts.
Private encrypted blobs belong in ignored runtime/, never in the repository.
"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile


class CredentialStoreError(RuntimeError):
    pass


def _crypt(data, *, decrypt=False):
    if os.name != 'nt':
        raise CredentialStoreError('Windows DPAPI is unavailable')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    source, target = Blob(len(data), buffer), Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    function = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.POINTER(Blob),
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    # UI_FORBIDDEN; omit LOCAL_MACHINE so another Windows user cannot decrypt it.
    ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise CredentialStoreError('Windows credential protection failed')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


class WindowsCredentialStore:
    def __init__(self, path):
        self.path = Path(path)

    def save(self, config):
        raw = json.dumps(config, separators=(',', ':')).encode('utf-8')
        encrypted = _crypt(raw)
        if config['api_key'].encode() in encrypted:
            raise CredentialStoreError('Credential protection failed')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.credential-', delete=False) as out:
                name = out.name
                out.write(encrypted)
                out.flush()
                os.fsync(out.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def load(self):
        if not self.path.exists():
            return None
        if self.path.is_symlink() or self.path.stat().st_size > 16384:
            raise CredentialStoreError('Invalid encrypted credential file')
        try:
            value = json.loads(_crypt(self.path.read_bytes(), decrypt=True))
            if (not isinstance(value, dict) or value.get('free_tier_confirmed') is not True
                    or value.get('data_terms_confirmed') is not True
                    or value.get('continuous_use') is not True
                    or not isinstance(value.get('api_key'), str)):
                raise ValueError()
            return value
        except (ValueError, UnicodeError, OSError):
            raise CredentialStoreError('Cannot restore protected credential') from None

    def clear(self):
        self.path.unlink(missing_ok=True)
