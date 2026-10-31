# -*- coding: utf-8 -*-
"""
清理模块：安全删除
- 红档路径一律拒绝（白名单二次拦截，UI 锁死之外再加一道）
- 删除一律进回收站（send2trash；Windows 无 send2trash 时用 SHFileOperation）
- 每次清理写日志，可追溯
"""
import os
import json
import time
import tempfile

from rules import is_protected


def _log_dir():
    if os.name == "nt":
        base = os.path.expandvars("%APPDATA%")
        d = os.path.join(base, "DeepClean", "logs")
    else:
        d = os.path.join(os.path.expanduser("~"), ".deepclean", "logs")
    os.makedirs(d, exist_ok=True)
    return d


def _multi_string(paths):
    """SHFileOperation 用的双 \\0 结尾多字符串"""
    return "\x00".join(os.path.abspath(p) for p in paths) + "\x00\x00"


def _trash_win(paths):
    """Windows 原生回收站（SHFileOperation，FOF_ALLOWUNDO）"""
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCT(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND),
                    ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", wintypes.LPVOID),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 0x3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_SILENT = 0x4
    FOF_NOERRORUI = 0x400
    FOF_NOCONFIRMMKDIR = 0x200
    buf = _multi_string(paths)
    op = SHFILEOPSTRUCT()
    op.wFunc = FO_DELETE
    op.pFrom = buf
    op.fFlags = (FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT |
                 FOF_NOERRORUI | FOF_NOCONFIRMMKDIR)
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if res != 0:
        raise OSError(f"SHFileOperation failed: {res}")


def safe_delete(paths, total_size=0, progress_cb=None, chunk=200):
    """
    安全删除。返回 {"deleted": [...], "blocked": [...], "failed": [(path, err)]}
    blocked 为命中红档被拒绝的路径。
    total_size: 调用方已知的总字节数（扫描时算过），不再重复遍历。
    progress_cb(done_bytes, total_bytes, chunk_idx, chunk_total): 进度回调。
    Windows 下一律用批量 SHFileOperation（一次调几百个路径），
    比逐个 send2trash 快一个数量级；非 Windows 仍用 send2trash。
    """
    blocked = [p for p in paths if is_protected(p)]
    targets = [p for p in paths if p not in blocked]
    deleted, failed = [], []
    total = total_size
    done = 0.0
    per = (total / len(targets)) if (total and targets) else 0

    def _report(i, n):
        if progress_cb:
            try:
                progress_cb(min(total, done), total, i, n)
            except Exception:  # noqa: BLE001
                pass

    if targets:
        if os.name == "nt":
            n_chunks = (len(targets) + chunk - 1) // chunk
            for ci in range(n_chunks):
                part = targets[ci * chunk:(ci + 1) * chunk]
                try:
                    _trash_win(part)
                    deleted.extend(part)
                except Exception as e:  # noqa: BLE001
                    for p in part:
                        failed.append((p, str(e)))
                done += per * len(part)
                _report(ci + 1, n_chunks)
        else:
            try:
                from send2trash import send2trash
            except ImportError:
                for p in targets:
                    failed.append((p, "未安装 send2trash，无法安全删除"))
                targets = []
            for idx, p in enumerate(targets):
                try:
                    from send2trash import send2trash
                    send2trash(p)
                    deleted.append(p)
                except Exception as e:  # noqa: BLE001
                    failed.append((p, str(e)))
                done += per
                _report(idx + 1, len(targets))

    # 写日志
    try:
        log_path = os.path.join(
            _log_dir(), f"clean_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump({"time": time.strftime("%Y-%m-%d %H:%M:%S"),
                       "deleted": deleted, "blocked": blocked,
                       "failed": failed}, f, ensure_ascii=False, indent=2)
    except OSError:
        log_path = ""

    return {"deleted": deleted, "blocked": blocked,
            "failed": failed, "log": log_path}


def total_size(paths):
    """估算一批路径的总大小（文件直接取，目录递归，失败忽略）"""
    total = 0
    for p in paths:
        try:
            if os.path.isfile(p):
                total += os.path.getsize(p)
            elif os.path.isdir(p):
                for dp, _dn, fns in os.walk(p, onerror=lambda e: None):
                    for fn in fns:
                        try:
                            total += os.path.getsize(os.path.join(dp, fn))
                        except OSError:
                            pass
        except OSError:
            pass
    return total
