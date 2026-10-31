# -*- coding: utf-8 -*-
"""
启动项管理
- 来源：注册表 Run（HKLM/HKCU）+ 启动文件夹（用户/公共）
- 禁用/删除一律先备份，可恢复
"""
import os
import json
import shutil
import time


def _base():
    if os.name == "nt":
        d = os.path.join(os.path.expandvars("%APPDATA%"), "DeepClean", "startup")
    else:
        d = os.path.join(os.path.expanduser("~"), ".deepclean", "startup")
    os.makedirs(d, exist_ok=True)
    return d


def _backup_file():
    return os.path.join(_base(), "backup.json")


def _lnk_backup_dir():
    d = os.path.join(_base(), "lnk")
    os.makedirs(d, exist_ok=True)
    return d


def _load_backup():
    try:
        with open(_backup_file(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def _save_backup(items):
    with open(_backup_file(), "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def _reg_run_keys():
    if os.name != "nt":
        return []
    import winreg
    return [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKLM"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run", "HKCU"),
    ]


def _startup_folders():
    if os.name != "nt":
        return []
    return [
        (os.path.join(os.path.expandvars("%APPDATA%"),
                      r"Microsoft\Windows\Start Menu\Programs\Startup"), "用户"),
        (os.path.join(os.path.expandvars("%PROGRAMDATA%"),
                      r"Microsoft\Windows\Start Menu\Programs\Startup"), "公共"),
    ]


def list_startup_entries():
    """返回 [{id, name, command, location, kind}]，kind: reg/lnk"""
    entries = []
    if os.name == "nt":
        import winreg
        for hive, key_path, tag in _reg_run_keys():
            try:
                with winreg.OpenKey(hive, key_path) as k:
                    n = winreg.QueryInfoKey(k)[0]
                    for i in range(n):
                        try:
                            name, cmd, _t = winreg.EnumValue(k, i)
                        except OSError:
                            continue
                        entries.append({
                            "id": f"reg:{tag}:{name}",
                            "name": name,
                            "command": str(cmd),
                            "location": f"注册表 {tag}",
                            "kind": "reg",
                        })
            except OSError:
                pass
        for folder, tag in _startup_folders():
            if not os.path.isdir(folder):
                continue
            try:
                for fn in sorted(os.listdir(folder)):
                    if fn.lower().endswith(".lnk"):
                        entries.append({
                            "id": f"lnk:{tag}:{fn}",
                            "name": os.path.splitext(fn)[0],
                            "command": os.path.join(folder, fn),
                            "location": f"启动文件夹（{tag}）",
                            "kind": "lnk",
                        })
            except OSError:
                pass
    # 已禁用的（备份中 status=disabled）
    disabled = [b for b in _load_backup() if b.get("status") == "disabled"]
    return entries, disabled


def _reg_delete(hive, key_path, name):
    import winreg
    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.DeleteValue(k, name)


def _reg_set(hive, key_path, name, cmd):
    import winreg
    with winreg.OpenKey(hive, key_path, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, cmd)


def _find_reg_entry(entry_id):
    # id: reg:TAG:name
    _p, tag, name = entry_id.split(":", 2)
    for hive, key_path, t in _reg_run_keys():
        if t == tag:
            return hive, key_path, name
    return None, None, None


def disable_entry(entry):
    """禁用，备份可恢复。返回 (ok, msg)"""
    try:
        backup = _load_backup()
        if entry["kind"] == "reg":
            hive, key_path, name = _find_reg_entry(entry["id"])
            import winreg
            with winreg.OpenKey(hive, key_path) as k:
                cmd, _t = winreg.QueryValueEx(k, name)
            backup.append({"id": entry["id"], "name": name,
                           "command": str(cmd), "kind": "reg",
                           "hive_tag": key_path, "status": "disabled",
                           "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            _save_backup(backup)
            _reg_delete(hive, key_path, name)
        else:
            src = entry["command"]
            dst = os.path.join(_lnk_backup_dir(),
                               os.path.basename(src))
            shutil.move(src, dst)
            backup.append({"id": entry["id"], "name": entry["name"],
                           "command": dst, "kind": "lnk",
                           "orig": src, "status": "disabled",
                           "time": time.strftime("%Y-%m-%d %H:%M:%S")})
            _save_backup(backup)
        return True, "已禁用"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def enable_entry(backup_item):
    """从备份恢复。返回 (ok, msg)"""
    try:
        if backup_item["kind"] == "reg":
            _p, tag, name = backup_item["id"].split(":", 2)
            hive, key_path, _n = None, None, None
            for h, kp, t in _reg_run_keys():
                if t == tag:
                    hive, key_path = h, kp
            _reg_set(hive, key_path, name, backup_item["command"])
        else:
            shutil.move(backup_item["command"], backup_item["orig"])
        backup = [b for b in _load_backup() if b["id"] != backup_item["id"]]
        _save_backup(backup)
        return True, "已恢复启用"
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def delete_entry(entry):
    """删除启动项（备份中标记为 deleted，可手动找回备份文件）"""
    ok, msg = disable_entry(entry)
    if not ok:
        return ok, msg
    backup = _load_backup()
    for b in backup:
        if b["id"] == entry["id"]:
            b["status"] = "deleted"
    _save_backup(backup)
    return True, "已删除（备份保留在 DeepClean/startup）"
