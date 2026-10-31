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
    "FileStorage/Cache": ("缓存", "safe", "小程序/公众号/视频号缓存，可放心清理"),
    "FileStorage/Temp": ("临时文件", "safe", "可放心清理"),
    "FileStorage/CustomEmotion": ("表情包缓存", "safe", "会自动重新下载"),
    "FileStorage/Video": ("聊天视频", "warn", "删了聊天里就看不了"),
    "FileStorage/Image": ("聊天图片", "warn", "删了聊天里就看不了"),
    "FileStorage/File": ("聊天文件", "warn", "删了聊天里打不开"),
    "FileStorage/MsgAttach": ("聊天附件(按联系人)", "warn", "删了对应聊天看不了附件"),
    "FileStorage/Voice": ("语音消息", "warn", "删了聊天里听不了"),
    "Msg": ("聊天数据库", "danger", "删了该账号所有聊天记录永久丢失！"),
    "db_storage": ("聊天数据库(4.x)", "danger", "删了该账号所有聊天记录永久丢失！"),
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
