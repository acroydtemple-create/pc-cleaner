# -*- coding: utf-8 -*-
"""
深度清理引擎（v0.2 高风险区）
- 微信专清：FileStorage 各分类 + 聊天数据库
- 软件卸载：读注册表已安装列表，调官方卸载
- 应用缓存：QQ/钉钉/Adobe/npm/pip 等
- 休眠文件：hiberfil.sys
"""
import os
import re
import glob
import shlex
import subprocess


def _ev(p):
    return os.path.expandvars(p)


def dir_size(path, cap_files=300000):
    """返回 (bytes, 文件数, 是否被截断)"""
    total, n, cut = 0, 0, False
    for dp, _dn, fns in os.walk(path, onerror=lambda e: None):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
            n += 1
            if n >= cap_files:
                cut = True
                return total, n, cut
    return total, n, cut


# ---------------- 微信 ----------------
# 已知子目录 -> (显示名, 级别, 说明)，级别: safe/warn/danger
WECHAT_KNOWN = {
    # ---- 3.x ----
    "FileStorage/Cache": ("缓存", "safe", "小程序/公众号/视频号缓存，可放心清理"),
    "FileStorage/Temp": ("临时文件", "safe", "可放心清理"),
    "FileStorage/CustomEmotion": ("表情包缓存", "safe", "会自动重新下载"),
    "FileStorage/Video": ("聊天视频", "warn", "删了聊天里就看不了"),
    "FileStorage/Image": ("聊天图片", "warn", "删了聊天里就看不了"),
    "FileStorage/File": ("聊天文件", "warn", "删了聊天里打不开"),
    "FileStorage/MsgAttach": ("聊天附件(按联系人)", "warn", "删了对应聊天看不了附件"),
    "FileStorage/Voice": ("语音消息", "warn", "删了聊天里听不了"),
    "Msg": ("聊天数据库", "danger", "删了该账号所有聊天记录永久丢失！"),
    # ---- 4.x (xwechat_files) ----
    "db_storage": ("聊天数据库(4.x)", "danger", "删了该账号所有聊天记录永久丢失！"),
    "msg": ("聊天图片视频文件", "warn", "聊天里的图片/视频/文件本体，删了聊天里看不了打不开了"),
    "cache": ("缓存", "safe", "朋友圈/视频号/小程序等缓存，删了会自动重新生成"),
    "temp": ("临时文件", "safe", "可放心清理"),
    "business": ("业务资源", "warn", "表情/收藏/朋友圈/小程序的资源文件，删了需重新加载"),
    "resource": ("资源文件", "warn", "微信界面与功能资源，删了可能要重下"),
    "config": ("账号配置", "warn", "微信本机设置，删了设置会重置、需重新登录配置"),
    "apm_record": ("性能统计日志", "safe", "性能监控记录的日志，可放心清理"),
    "Backup": ("聊天备份", "warn", "手机聊天记录备份文件，确认不需要再删"),
    "download": ("下载文件", "warn", "微信里下载的文件，先确认再删"),
}


def find_wechat_bases():
    """找微信数据根目录"""
    bases = []
    if os.name == "nt":
        docs = os.path.join(os.path.expanduser("~"), "Documents")
        for name in ("WeChat Files", "xwechat_files"):
            p = os.path.join(docs, name)
            if os.path.isdir(p):
                bases.append(p)
        # 用户手动指定的
        manual = _manual_wechat_dir()
        if manual and os.path.isdir(manual) and manual not in bases:
            bases.append(manual)
    return bases


def _manual_cfg():
    if os.name == "nt":
        d = os.path.join(_ev("%APPDATA%"), "DeepClean")
    else:
        d = os.path.join(os.path.expanduser("~"), ".deepclean")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "wechat_dir.txt")


def _manual_wechat_dir():
    try:
        with open(_manual_cfg(), encoding="utf-8") as f:
            p = f.read().strip()
            return p or None
    except OSError:
        return None


def save_manual_wechat_dir(p):
    with open(_manual_cfg(), "w", encoding="utf-8") as f:
        f.write(p)


def list_wxids(base):
    """base 下的账号目录（wxid_xxx 或含 FileStorage/Msg 的目录）"""
    out = []
    try:
        for n in sorted(os.listdir(base)):
            fp = os.path.join(base, n)
            if not os.path.isdir(fp):
                continue
            if (n.startswith("wxid_")
                    or os.path.isdir(os.path.join(fp, "FileStorage"))
                    or os.path.isdir(os.path.join(fp, "Msg"))
                    or os.path.isdir(os.path.join(fp, "db_storage"))):
                out.append(n)
    except OSError:
        pass
    return out


def scan_wechat(base, wxid, progress_cb=None):
    """扫描某账号下各子目录体积，返回 [{rel, path, label, level, desc, size, count}]"""
    root = os.path.join(base, wxid)
    # 先看 FileStorage 下一层，再看账号根下一层
    rels = []
    fs = os.path.join(root, "FileStorage")
    if os.path.isdir(fs):
        try:
            rels += ["FileStorage/" + n for n in sorted(os.listdir(fs))
                     if os.path.isdir(os.path.join(fs, n))]
        except OSError:
            pass
    try:
        rels += [n for n in sorted(os.listdir(root))
                 if os.path.isdir(os.path.join(root, n)) and n != "FileStorage"]
    except OSError:
        pass
    items = []
    for i, rel in enumerate(rels):
        p = os.path.join(root, rel.replace("/", os.sep))
        size, count, _cut = dir_size(p)
        if size == 0:
            continue
        label, level, desc = WECHAT_KNOWN.get(
            rel, (rel.split("/")[-1], "warn", "未知用途，请确认后再删"))
        items.append({"rel": rel, "path": p, "label": label, "level": level,
                      "desc": desc, "size": size, "count": count})
        if progress_cb:
            progress_cb(i + 1, len(rels), rel)
    items.sort(key=lambda x: -x["size"])
    return items


# ---------------- 应用缓存 ----------------
APP_CACHES = [
    ("QQ 聊天文件与缓存",
     ["%USERPROFILE%\\Documents\\Tencent Files"],
     "warn", "含 QQ 收到的文件，勾选前请确认"),
    ("钉钉缓存",
     ["%APPDATA%\\DingTalk"],
     "warn", "含聊天缓存，删了需重新加载"),
    ("Adobe 媒体缓存",
     ["%APPDATA%\\Adobe\\Common\\Media Cache Files"],
     "safe", "PR/AE 的预览缓存，会自动重建"),
    ("npm 缓存",
     ["%APPDATA%\\npm-cache"],
     "safe", "前端开发工具的下载缓存"),
    ("pip 缓存",
     ["%LOCALAPPDATA%\\pip\\Cache"],
     "safe", "Python 包的下载缓存"),
]


def scan_app_caches():
    """返回 [{name, paths, level, desc, size, count}]（只返回存在的）"""
    out = []
    for name, pats, level, desc in APP_CACHES:
        size, count = 0, 0
        real = []
        for pat in pats:
            for t in glob.glob(_ev(pat)):
                if os.path.isdir(t):
                    real.append(t)
                    s, c, _ = dir_size(t)
                    size += s
                    count += c
        if real:
            out.append({"name": name, "paths": real, "level": level,
                        "desc": desc, "size": size, "count": count})
    out.sort(key=lambda x: -x["size"])
    return out


# ---------------- 软件卸载 ----------------
def list_installed_apps():
    """读注册表，返回 [{name, version, publisher, size, uninstall, quiet, msi}]"""
    apps = []
    if os.name != "nt":
        return apps
    import winreg
    roots = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER,
         r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    seen = {}
    for hive, sub in roots:
        try:
            key = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        try:
            n = winreg.QueryInfoKey(key)[0]
            for i in range(n):
                try:
                    subname = winreg.EnumKey(key, i)
                except OSError:
                    continue
                try:
                    with winreg.OpenKey(key, subname) as sk:
                        def g(v):
                            try:
                                return winreg.QueryValueEx(sk, v)[0]
                            except OSError:
                                return None
                        disp = g("DisplayName")
                        if not disp or not str(disp).strip():
                            continue
                        if g("SystemComponent") == 1:
                            continue
                        if g("ParentKeyName"):  # 补丁/子组件
                            continue
                        un = g("QuietUninstallString") or g("UninstallString")
                        if not un or not str(un).strip():
                            continue
                        icon_src = g("DisplayIcon") or ""
                        try:
                            size = int(g("EstimatedSize") or 0) * 1024
                        except (TypeError, ValueError):
                            size = 0
                        kid = str(disp).strip().lower()
                        if kid in seen and seen[kid]["size"] >= size:
                            continue
                        seen[kid] = {
                            "name": str(disp).strip(),
                            "version": str(g("DisplayVersion") or "").strip(),
                            "publisher": str(g("Publisher") or "").strip(),
                            "size": size,
                            "uninstall": str(un).strip(),
                            "icon_src": str(icon_src).strip(),
                            "quiet": bool(g("QuietUninstallString")),
                            "msi": str(un).strip().lower().startswith("msiexec"),
                        }
                except OSError:
                    continue
        finally:
            try:
                winreg.CloseKey(key)
            except OSError:
                pass
    apps = sorted(seen.values(), key=lambda a: -a["size"])
    return apps


def _split_cmd(cmd):
    try:
        return shlex.split(cmd, posix=False)
    except ValueError:
        return [cmd]


def _hidden_kwargs():
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return {"startupinfo": si,
                "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


def uninstall_app(app, timeout=600):
    """调官方卸载。返回 (ok, msg)"""
    un = app["uninstall"]
    try:
        if app["msi"]:
            # MsiExec.exe /I{GUID} -> /X{GUID} /qn /norestart
            cmd = re.sub(r"(?i)/I\s*\{", "/X{", un)
            low = cmd.lower()
            if "/qn" not in low and "/quiet" not in low:
                cmd += " /qn"
            if "norestart" not in low:
                cmd += " /norestart"
            args = _split_cmd(cmd)
        else:
            args = _split_cmd(un)
        subprocess.run(args, timeout=timeout, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       **_hidden_kwargs())
        return True, "已执行卸载程序"
    except subprocess.TimeoutExpired:
        return False, "卸载超时"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------------- 休眠文件 ----------------
def is_admin():
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def hiber_status():
    info = {"exists": False, "size": 0, "is_admin": is_admin()}
    if os.name != "nt":
        return info
    p = os.path.join(_ev("%SystemDrive%"), "hiberfil.sys")
    if os.path.isfile(p):
        info["exists"] = True
        try:
            info["size"] = os.path.getsize(p)
        except OSError:
            pass
    return info


def disable_hibernate():
    """powercfg /hibernate off。返回 (ok, msg)"""
    try:
        r = subprocess.run(["powercfg", "/hibernate", "off"], timeout=60,
                           check=False, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, **_hidden_kwargs())
        return r.returncode == 0, "休眠已关闭" if r.returncode == 0 else "执行失败（可能需要管理员权限）"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


# ---------------- 软件图标 ----------------
def resolve_app_exe(app):
    """从 DisplayIcon / UninstallString 找出 exe 路径"""
    for cand in (app.get("icon_src") or "", app.get("uninstall") or ""):
        cand = cand.strip()
        if not cand:
            continue
        m = re.match(r'^\s*"([^"]+)"', cand)
        path = m.group(1) if m else cand.split(",")[0].strip().strip('"')
        if path.lower().endswith(".exe") and os.path.isfile(path):
            return path
    return None


def get_app_icon_bytes(exe_path, size=32):
    """Windows: 从 exe 提取图标，转 PNG bytes；失败返回 None"""
    if os.name != "nt" or not exe_path or not os.path.isfile(exe_path):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        shell32 = ctypes.windll.shell32
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        large = wintypes.HICON()
        small = wintypes.HICON()
        if shell32.ExtractIconExW(exe_path, 0, ctypes.byref(large),
                                  ctypes.byref(small), 1) == 0:
            return None
        hicon = large if large.value else small.value
        if not hicon:
            return None

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                        ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                        ("hbmColor", wintypes.HBITMAP)]

        class BITMAP(ctypes.Structure):
            _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                        ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                        ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                        ("bmBits", wintypes.LPVOID)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                        ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                        ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                        ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                        ("biClrImportant", wintypes.DWORD)]

        ii = ICONINFO()
        if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
            user32.DestroyIcon(hicon)
            return None
        try:
            if not ii.hbmColor:
                return None
            bmp = BITMAP()
            gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(bmp), ctypes.byref(bmp))
            w, h = bmp.bmWidth, bmp.bmHeight
            if w <= 0 or h <= 0 or w > 256 or h > 256:
                return None
            bi = BITMAPINFOHEADER()
            bi.biSize = ctypes.sizeof(bi)
            bi.biWidth = w
            bi.biHeight = -h  # top-down
            bi.biPlanes = 1
            bi.biBitCount = 32
            bi.biCompression = 0  # BI_RGB
            buf = (ctypes.c_ubyte * (w * h * 4))()
            hdc = user32.GetDC(None)
            try:
                if gdi32.GetDIBits(hdc, ii.hbmColor, 0, h, ctypes.byref(buf),
                                   ctypes.byref(bi), 0) == 0:
                    return None
            finally:
                user32.ReleaseDC(None, hdc)
            from PIL import Image
            import io
            img = Image.frombytes("RGBA", (w, h), bytes(buf), "raw", "BGRA")
            if img.getchannel("A").getextrema() == (0, 0):
                img.putalpha(255)  # 有些图标 alpha 全 0，直接不透明
            img = img.resize((size, size), Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, "PNG")
            return out.getvalue()
        finally:
            if ii.hbmColor:
                gdi32.DeleteObject(ii.hbmColor)
            if ii.hbmMask:
                gdi32.DeleteObject(ii.hbmMask)
            user32.DestroyIcon(hicon)
    except Exception:
        return None
