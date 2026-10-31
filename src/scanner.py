# -*- coding: utf-8 -*-
"""
全盘扫描引擎
- 枚举驱动器（含容量）
- 递归统计：按文件类型分类 / 每个目录的递归体积 / Top 大文件 / Top 大目录
- 收集图片与视频清单（供预览页使用）
跨平台：Windows 为主，Linux/macOS 可跑（用于开发测试）。
"""
import os
import sys
import heapq
import time

# ---------------- 文件类型分类 ----------------
CATEGORIES = {
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
             ".heic", ".heif", ".svg", ".ico", ".psd", ".dng"},
    "视频": {".mp4", ".avi", ".mkv", ".mov", ".wmv", ".flv", ".webm", ".m4v",
             ".mpg", ".mpeg", ".ts", ".3gp", ".rmvb", ".vob"},
    "音频": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".ape"},
    "文档": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
             ".txt", ".md", ".csv", ".rtf", ".epub", ".mobi"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz"},
    "安装包": {".exe", ".msi", ".dmg", ".pkg", ".apk", ".iso", ".img"},
    "代码": {".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".go", ".rs",
             ".html", ".css", ".json", ".xml", ".yml", ".yaml", ".sh", ".bat"},
}
EXT_TO_CAT = {}
for _cat, _exts in CATEGORIES.items():
    for _e in _exts:
        EXT_TO_CAT[_e] = _cat


# 扫描时直接跳过的目录（名，小写比对）
SKIP_DIR_NAMES = {
    "system volume information", "$recycle.bin", "$recycled", "recycler",
    "config.msi", "$windows.~bt", "$windows.~ws",
    # WinSxS：几十万个系统组件小文件，扫它又慢又没意义，直接跳过
    "winsxs",
}


class ScanCancelled(Exception):
    pass


def list_drives():
    """返回驱动器列表：[{path, label, total, used, free}]"""
    drives = []
    try:
        import psutil
        for p in psutil.disk_partitions(all=False):
            if os.name == "nt":
                if "cdrom" in (p.opts or ""):
                    continue
                if not p.fstype:
                    continue
            mp = p.mountpoint
            try:
                u = psutil.disk_usage(mp)
            except (OSError, PermissionError):
                continue
            label = ""
            if os.name == "nt":
                try:
                    import ctypes
                    buf = ctypes.create_unicode_buffer(256)
                    ctypes.windll.kernel32.GetVolumeInformationW(
                        ctypes.c_wchar_p(mp), buf, 256,
                        None, None, None, None, 0)
                    label = buf.value
                except Exception:
                    label = ""
            drives.append({
                "path": mp if mp.endswith(os.sep) else mp + os.sep,
                "label": label,
                "total": u.total, "used": u.used, "free": u.free,
            })
    except ImportError:
        pass
    if not drives:
        if os.name == "nt":
            import string
            for ch in string.ascii_uppercase:
                d = ch + ":\\"
                if os.path.isdir(d):
                    drives.append({"path": d, "label": "", "total": 0,
                                   "used": 0, "free": 0})
        else:
            drives.append({"path": "/", "label": "", "total": 0,
                           "used": 0, "free": 0})
    return drives


def _new_frame(path):
    return {"path": path, "it": None, "files": 0, "child_sum": 0}


def scan_drive(root, progress_cb=None, cancel=None, top_n_files=200):
    """
    递归扫描 root。progress_cb(dirs_done, current_path)。
    cancel 为 threading.Event（或返回 bool 的 callable），置位时抛 ScanCancelled。
    返回 dict: categories / dir_totals / top_dirs / top_files / stats
    """
    def _cancelled():
        if cancel is None:
            return False
        return cancel.is_set() if hasattr(cancel, "is_set") else bool(cancel())

    cat_size = {c: 0 for c in list(CATEGORIES) + ["其他"]}
    cat_count = {c: 0 for c in list(CATEGORIES) + ["其他"]}
    dir_totals = {}
    file_heap = []          # (-size, path) 最小堆，保留 top_n
    dirs_done = 0
    files_done = 0
    t0 = time.time()
    last_cb = 0

    def push_file(size, path):
        if len(file_heap) < top_n_files:
            heapq.heappush(file_heap, (size, path))
        elif size > file_heap[0][0]:
            heapq.heapreplace(file_heap, (size, path))

    stack = [_new_frame(root)]
    while stack:
        f = stack[-1]
        if f["it"] is None:
            try:
                f["it"] = os.scandir(f["path"])
            except OSError:
                stack.pop()
                dir_totals[f["path"]] = 0
                if stack:
                    pass
                continue
        try:
            entry = next(f["it"])
        except StopIteration:
            total = f["files"] + f["child_sum"]
            dir_totals[f["path"]] = total
            try:
                f["it"].close()
            except Exception:
                pass
            stack.pop()
            if stack:
                stack[-1]["child_sum"] += total
            dirs_done += 1
            if progress_cb and (dirs_done - last_cb >= 200 or _cancelled()):
                last_cb = dirs_done
                progress_cb(dirs_done, f["path"])
            if _cancelled():
                raise ScanCancelled()
            continue
        except OSError:
            continue

        try:
            if entry.is_dir(follow_symlinks=False):
                if entry.name.lower() in SKIP_DIR_NAMES:
                    continue
                stack.append(_new_frame(entry.path))
            elif entry.is_file(follow_symlinks=False):
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                sz = st.st_size
                f["files"] += sz
                files_done += 1
                ext = os.path.splitext(entry.name)[1].lower()
                cat = EXT_TO_CAT.get(ext, "其他")
                cat_size[cat] += sz
                cat_count[cat] += 1
                push_file(sz, entry.path)
        except OSError:
            continue

    top_files = sorted(file_heap, key=lambda x: -x[0])
    top_dirs = heapq.nlargest(40, dir_totals.items(), key=lambda x: x[1])
    # 根目录直属子目录体积（用于"这个盘里啥最大"）
    children = []
    for d, s in dir_totals.items():
        parent = os.path.dirname(d.rstrip(os.sep))
        if os.path.abspath(parent) == os.path.abspath(root.rstrip(os.sep)):
            children.append((d, s))
    children.sort(key=lambda x: -x[1])

    return {
        "root": root,
        "categories": [{"name": c, "size": cat_size[c], "count": cat_count[c]}
                       for c in cat_size],
        "dir_totals": dir_totals,
        "top_dirs": [{"path": p, "size": s} for p, s in top_dirs[:30]],
        "top_children": [{"path": p, "size": s} for p, s in children[:30]],
        "top_files": [{"path": p, "size": s} for s, p in top_files[:100]],
        "stats": {"dirs": dirs_done, "files": files_done,
                  "seconds": round(time.time() - t0, 1)},
    }


def fmt_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
