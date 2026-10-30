"""API secrets in Windows Credential Manager, never in project JSON."""
import ctypes as ct
import hashlib
from pathlib import Path
from ctypes import wintypes as wt


class Credential(ct.Structure):
    _fields_ = [('Flags', wt.DWORD), ('Type', wt.DWORD), ('TargetName', wt.LPWSTR),
                ('Comment', wt.LPWSTR), ('LastWritten', wt.FILETIME),
                ('CredentialBlobSize', wt.DWORD), ('CredentialBlob', ct.POINTER(ct.c_ubyte)),
                ('Persist', wt.DWORD), ('AttributeCount', wt.DWORD),
                ('Attributes', ct.c_void_p), ('TargetAlias', wt.LPWSTR), ('UserName', wt.LPWSTR)]


def api():
    dll = ct.WinDLL('advapi32', use_last_error=True)
    dll.CredWriteW.argtypes = [ct.POINTER(Credential), wt.DWORD]
    dll.CredWriteW.restype = wt.BOOL
    dll.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ct.POINTER(ct.POINTER(Credential))]
    dll.CredReadW.restype = wt.BOOL
    dll.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
    dll.CredDeleteW.restype = wt.BOOL
    dll.CredFree.argtypes = [ct.c_void_p]
    dll.CredFree.restype = None
    return dll


def target(provider):
    if provider not in ('gpt', 'gemini'):
        raise ValueError('Unknown online provider')
    installation = str(Path(__file__).resolve().parents[2]).casefold()
    namespace = hashlib.sha256(installation.encode('utf-8')).hexdigest()[:16]
    return f'Mio/Online/{namespace}/{provider}'


def save_key(provider, secret):
    data = secret.strip().encode('utf-8')
    if not data or len(data) > 2500:
        raise ValueError('Enter a nonempty API key shorter than 2500 bytes')
    buffer = (ct.c_ubyte * len(data)).from_buffer_copy(data)
    value = Credential(Type=1, TargetName=target(provider), CredentialBlobSize=len(data),
                       CredentialBlob=buffer, Persist=2, UserName='Mio')
    if not api().CredWriteW(ct.byref(value), 0):
        raise OSError('Windows could not save the API key')


def read_key(provider):
    dll = api()
    value = ct.POINTER(Credential)()
    if not dll.CredReadW(target(provider), 1, 0, ct.byref(value)):
        if ct.get_last_error() == 1168:
            return ''
        raise OSError('Windows could not read the API key')
    try:
        return ct.string_at(value.contents.CredentialBlob,
                            value.contents.CredentialBlobSize).decode('utf-8')
    finally:
        dll.CredFree(value)


def delete_key(provider):
    if not api().CredDeleteW(target(provider), 1, 0) and ct.get_last_error() != 1168:
        raise OSError('Windows could not remove the API key')
