# -*- coding: utf-8 -*-
"""
三档清理规则
- 绿（可放心清理）：系统临时文件、各类缓存、更新残留 —— 删了不影响使用
- 黄（人工确认）：下载目录旧文件、重复文件、大体积文件、旧安装包 —— 列出来让人看
- 红（禁止触碰）：系统关键目录 —— UI 直接锁死，清理模块二次拦截
"""
import os
import glob
import time
import hashlib
import fnmatch
from collections import defaultdict


def _ev(path):
    """展开 %VAR% 环境变量；不存在的变量保持原样"""
    return os.path.expandvars(path)


# ---------------- 红档：禁止触碰 ----------------
def protected_prefixes():
    prefs = []
    if os.name == "nt":
        sysroot = _ev("%SystemRoot%")
        prefs += [
            sysroot,
            _ev("%ProgramFiles%"),
            _ev("%ProgramFiles(x86)%"),
            _ev("%ProgramData%"),
            _ev("%SystemDrive%\\$Recycle.Bin"),
            os.path.join(sysroot, "System32"),
            os.path.join(sysroot, "SysWOW64"),
        ]
        # 每个盘符的系统保留目录
        import string
        for ch in string.ascii_uppercase:
            d = ch + ":\\"
            if os.path.isdir(d):
                prefs.append(os.path.join(d, "System Volume Information"))
                prefs.append(os.path.join(d, "$Recycle.Bin"))
        # 关键系统文件
        for f in ("pagefile.sys", "hiberfil.sys", "swapfile.sys"):
            prefs.append(os.path.join(_ev("%SystemDrive%\\"), f))
    else:
        prefs += ["/bin", "/sbin", "/usr", "/etc", "/boot", "/proc",
                  "/sys", "/dev", "/lib", "/lib64", "/var/lib"]
    return [os.path.normcase(os.path.normpath(p)) for p in prefs if p]


_PROTECTED = None


def _protected_cache():
    global _PROTECTED
    if _PROTECTED is None:
        _PROTECTED = protected_prefixes()
    return _PROTECTED


def is_protected(path):
    """路径是否在红档保护范围内"""
    if not path:
        return True
    np = os.path.normcase(os.path.normpath(os.path.abspath(path)))
    for pref in _protected_cache():
        if np == pref or np.startswith(pref + os.sep):
            return True
    # Windows 下用户目录之外的根目录文件也保守处理
    return False


def classify_path(path):
    """返回 'red' / 'other'（unknown 一律按黄档人工确认处理）"""
    return "red" if is_protected(path) else "other"


# ---------------- 绿档：可放心清理 ----------------
# 每项：(显示名, [路径模板…])，模板支持 %VAR% 与 glob 通配符
GREEN_RULES = [
    ("系统临时文件", ["%SystemRoot%\\Temp", "%TEMP%", "%TMP%"]),
    ("Windows 更新下载缓存", ["%SystemRoot%\\SoftwareDistribution\\Download"]),
    ("预读缓存", ["%SystemRoot%\\Prefetch"]),
    ("系统日志", ["%SystemRoot%\\Logs", "%SystemRoot%\\Minidump"]),
    ("缩略图缓存", ["%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\thumbcache_*.db"]),
    ("图标缓存", ["%LOCALAPPDATA%\\IconCache.db",
                "%LOCALAPPDATA%\\Microsoft\\Windows\\Explorer\\iconcache_*.db"]),
    ("Chrome 缓存", ["%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Cache",
                    "%LOCALAPPDATA%\\Google\\Chrome\\User Data\\Default\\Code Cache"]),
    ("Edge 缓存", ["%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Cache",
                  "%LOCALAPPDATA%\\Microsoft\\Edge\\User Data\\Default\\Code Cache"]),
    ("Firefox 缓存", ["%APPDATA%\\Mozilla\\Firefox\\Profiles\\*\\cache2"]),
    ("DirectX 着色器缓存", ["%LOCALAPPDATA%\\D3DSCache"]),
    ("崩溃转储文件", ["%LOCALAPPDATA%\\CrashDumps"]),
    ("旧版 Windows 残留", ["%SystemDrive%\\$Windows.~BT", "%SystemDrive%\\Windows.old"]),
]


def _iter_rule_files(patterns):
    seen = set()
    for pat in patterns:
        expanded = _ev(pat)
        # 含通配符 -> glob；否则直接判定
        targets = glob.glob(expanded) if any(c in expanded for c in "*?[") else [expanded]
        for t in targets:
            t = os.path.normpath(t)
            if t in seen or is_protected(t):
                continue
            seen.add(t)
            if os.path.isfile(t):
                yield t
            elif os.path.isdir(t):
                for dirpath, _dirnames, filenames in os.walk(t, onerror=lambda e: None):
                    for fn in filenames:
                        yield os.path.join(dirpath, fn)


def scan_green(max_files_per_rule=3000):
    """扫描绿档，返回 [{name, size, count, files:[...]}]"""
    results = []
    for name, patterns in GREEN_RULES:
        size, count, files = 0, 0, []
        for fp in _iter_rule_files(patterns):
            try:
                sz = os.path.getsize(fp)
            except OSError:
                continue
            size += sz
            count += 1
            if len(files) < max_files_per_rule:
                files.append(fp)
        if count:
            results.append({"name": name, "size": size, "count": count,
                            "files": files, "tier": "green"})
    results.sort(key=lambda r: -r["size"])
    return results


# ---------------- 黄档：人工确认 ----------------
def scan_downloads(max_age_days=90, big_size=200 * 1024 * 1024, cap=2000):
    """下载目录：超过 max_age_days 未动 或 大于 big_size 的文件"""
    dl = _ev("%USERPROFILE%\\Downloads") if os.name == "nt" else os.path.expanduser("~/Downloads")
    if not os.path.isdir(dl):
        return []
    now = time.time()
    items = []
    for dirpath, _dn, fns in os.walk(dl, onerror=lambda e: None):
        for fn in fns:
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            age_days = (now - st.st_mtime) / 86400
            if age_days >= max_age_days or st.st_size >= big_size:
                items.append({"path": fp, "size": st.st_size,
                              "mtime": st.st_mtime, "age_days": round(age_days)})
                if len(items) >= cap:
                    return sorted(items, key=lambda x: -x["size"])
    return sorted(items, key=lambda x: -x["size"])


def scan_old_installers(max_age_days=180, cap=500):
    """下载目录里放了很久的安装包"""
    dl = _ev("%USERPROFILE%\\Downloads") if os.name == "nt" else os.path.expanduser("~/Downloads")
    if not os.path.isdir(dl):
        return []
    now = time.time()
    exts = {".exe", ".msi", ".dmg", ".pkg", ".apk", ".iso"}
    items = []
    for dirpath, _dn, fns in os.walk(dl, onerror=lambda e: None):
        for fn in fns:
            if os.path.splitext(fn)[1].lower() not in exts:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            if (now - st.st_mtime) / 86400 >= max_age_days:
                items.append({"path": fp, "size": st.st_size, "mtime": st.st_mtime})
                if len(items) >= cap:
                    return sorted(items, key=lambda x: -x["size"])
    return sorted(items, key=lambda x: -x["size"])


def _quick_hash(path, chunk=1024 * 1024):
    h = hashlib.md5()
    with open(path, "rb") as f:
        h.update(f.read(chunk))
    return h.hexdigest()


def find_duplicates(roots, min_size=2 * 1024 * 1024, max_files=200000):
    """
    找重复文件：先按体积聚类，再对同体积的取前 1MB 做 md5。
    返回 [{"size":, "files":[...]}]（每组 2+ 个文件）
    """
    by_size = defaultdict(list)
    walked = 0
    for root in roots:
        if not root or not os.path.isdir(root) or is_protected(root):
            continue
        for dirpath, _dn, fns in os.walk(root, onerror=lambda e: None):
            if is_protected(dirpath):
                _dn[:] = []
                continue
            for fn in fns:
                fp = os.path.join(dirpath, fn)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                if sz >= min_size:
                    by_size[sz].append(fp)
                walked += 1
                if walked >= max_files:
                    break
            if walked >= max_files:
                break
    groups = []
    for sz, files in by_size.items():
        if len(files) < 2:
            continue
        by_hash = defaultdict(list)
        for fp in files:
            try:
                by_hash[_quick_hash(fp)].append(fp)
            except OSError:
                continue
        for files2 in by_hash.values():
            if len(files2) >= 2:
                groups.append({"size": sz, "files": sorted(files2)})
    groups.sort(key=lambda g: -(g["size"] * (len(g["files"]) - 1)))
    return groups[:200]


def user_roots():
    """用户数据根目录（重复文件/大文件扫描范围）"""
    roots = []
    if os.name == "nt":
        roots.append(_ev("%USERPROFILE%"))
        import string
        for ch in string.ascii_uppercase:
            d = ch + ":\\"
            if os.path.isdir(d) and os.path.normcase(d) != os.path.normcase(_ev("%SystemDrive%\\")):
                roots.append(d)
    else:
        roots.append(os.path.expanduser("~"))
    return [r for r in roots if os.path.isdir(r)]


def red_summary():
    """红档说明（展示用，不扫描内容）"""
    items = [
        ("Windows 系统目录", "系统运行核心，删除会导致无法开机"),
        ("Program Files / ProgramData", "已安装软件，删了软件就坏了"),
        ("页面文件 / 休眠文件", "系统虚拟内存，动它会蓝屏"),
        ("$Recycle.Bin / System Volume Information", "回收站与系统还原点"),
    ]
    if os.name != "nt":
        items = [("/bin /sbin /usr /etc /boot", "系统关键目录，删除会导致系统崩溃")]
    return items
