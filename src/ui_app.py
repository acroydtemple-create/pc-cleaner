# -*- coding: utf-8 -*-
"""主界面 v0.1.2：品牌化 redesign
- 品牌色取自 logo（青蓝），卡片式布局，信息层级收紧
- 后台线程跑耗时任务，主线程只摆 widget，界面不卡
"""
import os
import sys
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, filedialog

import customtkinter as ctk
from PIL import Image

import scanner
import rules
import cleaner
import deepclean
from version import __version__, APP_NAME

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ---------------- 品牌 token ----------------
BRAND = "#1fa3c9"
BRAND_HOVER = "#1688ab"
C_GREEN = "#2fbf71"
C_YELLOW = "#e8a13a"
C_RED = "#e5605e"
CARD_BG = ("#eef1f5", "#22262e")
MUTED = ("gray40", "gray60")


def _font(size=13, weight="normal"):
    return ctk.CTkFont(size=size, weight=weight)


def resource_path(rel):
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, rel)
    here = os.path.dirname(os.path.abspath(__file__))  # src/
    return os.path.join(os.path.dirname(here), rel)


def _short(path, n=58):
    if len(path) <= n:
        return path
    return path[: n // 2 - 2] + "…" + path[-(n // 2 - 2):]


def _card(master, **kw):
    kw.setdefault("fg_color", CARD_BG)
    kw.setdefault("corner_radius", 14)
    return ctk.CTkFrame(master, **kw)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{__version__}")
        self.geometry("1240x800")
        self.minsize(1060, 660)
        try:
            self.iconbitmap(resource_path("assets/icon.ico"))
        except Exception:
            pass

        self.q = queue.Queue()
        self.drives = []
        self.drive_cards = []
        self.selected_drive = None
        self.scan_result = None
        self.green_data = []
        self.yellow_data = {"downloads": [], "installers": [], "dups": []}
        self.green_vars = []
        self.yellow_vars = []
        self._busy = False
        self._scan_cancel = None
        self._last_prog_ui = 0
        self._logo_ref = None
        self.wechat_base = None
        self.wechat_wxid = None
        self.wechat_items = []
        self.wechat_vars = []
        self.appcache_vars = []
        self.apps = []
        self.app_vars = []
        self.hiber = {"exists": False, "size": 0, "is_admin": False}
        self._app_icon_refs = []

        self._build_sidebar()
        self._build_main()
        self.refresh_drives()
        self.after(120, self._poll_queue)

    # ================= 侧边栏 =================
    def _build_sidebar(self):
        sb = _card(self, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew", padx=(10, 6), pady=10)
        sb.grid_propagate(False)
        sb.configure(width=248)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 品牌头
        head = ctk.CTkFrame(sb, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(16, 6))
        try:
            logo = Image.open(resource_path("assets/logo.png"))
            self._logo_ref = ctk.CTkImage(light_image=logo, dark_image=logo,
                                          size=(46, 46))
            ctk.CTkLabel(head, image=self._logo_ref, text="").pack(side="left")
        except Exception:
            ctk.CTkLabel(head, text="🧹", font=_font(30)).pack(side="left")
        tt = ctk.CTkFrame(head, fg_color="transparent")
        tt.pack(side="left", padx=10)
        ctk.CTkLabel(tt, text=APP_NAME, font=_font(17, "bold"),
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(tt, text=f"DeepClean v{__version__}", font=_font(11),
                     text_color=MUTED, anchor="w").pack(anchor="w")

        ctk.CTkLabel(sb, text="磁盘", font=_font(12, "bold"),
                     text_color=MUTED, anchor="w").pack(fill="x", padx=16, pady=(10, 4))
        self.drive_box = ctk.CTkScrollableFrame(sb, fg_color="transparent", height=210)
        self.drive_box.pack(fill="x", padx=8, pady=0)

        ctk.CTkLabel(sb, text="操作", font=_font(12, "bold"),
                     text_color=MUTED, anchor="w").pack(fill="x", padx=16, pady=(10, 4))
        self._side_btn(sb, "🔍  开始扫描", self.start_scan, primary=True)
        self._side_btn(sb, "⏹  停止扫描", self.stop_scan)
        self._side_btn(sb, "🧪  扫描垃圾", self.start_junk_scan)
        ctk.CTkFrame(sb, height=1, fg_color=("gray80", "gray28")).pack(
            fill="x", padx=16, pady=10)
        self._side_btn(sb, "⚡  一键清理绿档", self.clean_green,
                       fg=C_GREEN, hover="#24915a")
        self._side_btn(sb, "🗑  清理所选", self.clean_selected)

        ctk.CTkLabel(sb, text="删除一律进回收站，可还原\n扫盘为只读，不动你的文件",
                     font=_font(11), text_color=MUTED,
                     justify="center").pack(side="bottom", pady=14)

    def _side_btn(self, parent, text, cmd, primary=False, fg=None, hover=None):
        b = ctk.CTkButton(
            parent, text=text, command=cmd, height=38,
            corner_radius=10, font=_font(13, "bold" if primary else "normal"),
            fg_color=fg or (BRAND if primary else ("gray82", "gray26")),
            hover_color=hover or (BRAND_HOVER if primary else ("gray76", "gray32")),
            text_color="white" if (primary or fg) else ("black", "white"))
        b.pack(fill="x", padx=14, pady=4)
        return b

    # ================= 主区 =================
    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 10), pady=10)
        main.grid_rowconfigure(1, weight=1)
        main.grid_columnconfigure(0, weight=1)

        # 顶部品牌细条
        ctk.CTkFrame(main, height=3, fg_color=BRAND,
                     corner_radius=2).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.tabs = ctk.CTkTabview(main, corner_radius=14,
                                   fg_color=CARD_BG)
        self.tabs.grid(row=1, column=0, sticky="nsew")
        for name in ("空间分析", "垃圾清理", "深度清理"):
            self.tabs.add(name)
        self._build_tab_space(self.tabs.tab("空间分析"))
        self._build_tab_junk(self.tabs.tab("垃圾清理"))
        self._build_tab_deep(self.tabs.tab("深度清理"))

        # 状态条
        bar = _card(self, corner_radius=10)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew",
                 padx=10, pady=(0, 10))
        self.status_label = ctk.CTkLabel(bar, text="就绪 — 选择磁盘，开始扫描",
                                         anchor="w", font=_font(12))
        self.status_label.pack(side="left", padx=14, pady=8)
        self.prog = ctk.CTkProgressBar(bar, width=200, height=8,
                                       progress_color=BRAND)
        self.prog.pack(side="right", padx=14)
        self.prog.set(0)

    # ================= 磁盘卡片 =================
    def refresh_drives(self):
        for w in self.drive_box.winfo_children():
            w.destroy()
        self.drive_cards.clear()
        self.drives = scanner.list_drives()
        for d in self.drives:
            card = _card(self.drive_box, border_width=2,
                         border_color=CARD_BG, corner_radius=12)
            card.pack(fill="x", pady=4, padx=2)
            pct = (d["used"] / d["total"]) if d["total"] else 0
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=12, pady=(10, 2))
            name = f"{d['path']}  {d['label']}".strip()
            ctk.CTkLabel(top, text=name, font=_font(13, "bold"),
                         anchor="w").pack(side="left")
            ctk.CTkLabel(top, text=f"{pct:.0%}", font=_font(12),
                         text_color=MUTED).pack(side="right")
            pb = ctk.CTkProgressBar(card, height=7, progress_color=BRAND)
            pb.pack(fill="x", padx=12, pady=6)
            pb.set(pct)
            ctk.CTkLabel(card,
                         text=f"已用 {scanner.fmt_size(d['used'])} / 共 {scanner.fmt_size(d['total'])}",
                         font=_font(11), text_color=MUTED,
                         anchor="w").pack(fill="x", padx=12, pady=(0, 10))
            card.bind("<Button-1>", lambda e, d=d: self.select_drive(d))
            for child in card.winfo_children():
                child.bind("<Button-1>", lambda e, d=d: self.select_drive(d))
                for cc in child.winfo_children():
                    cc.bind("<Button-1>", lambda e, d=d: self.select_drive(d))
            d["_card"] = card
            self.drive_cards.append((d, card))
        if self.drives and not self.selected_drive:
            self.select_drive(self.drives[0])

    def select_drive(self, d):
        self.selected_drive = d
        for dd, card in self.drive_cards:
            card.configure(border_color=BRAND if dd is d else CARD_BG)
        self._set_space_info()

    # ================= 空间分析 =================
    def _build_tab_space(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        self.space_info = ctk.CTkLabel(tab, text="", font=_font(12),
                                       text_color=MUTED, anchor="w")
        self.space_info.pack(fill="x", padx=12, pady=(4, 2))

        self.space_empty = _card(tab)
        self.space_empty.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(self.space_empty, text="👈",
                     font=_font(44)).pack(pady=(60, 8))
        ctk.CTkLabel(self.space_empty, text="先在左侧选择磁盘，点击「开始扫描」",
                     font=_font(14)).pack()
        ctk.CTkLabel(self.space_empty, text="扫描是只读的，不会修改你的任何文件",
                     font=_font(12), text_color=MUTED).pack(pady=6)

        self.space_body = ctk.CTkFrame(tab, fg_color="transparent")
        # stats 卡片行
        self.stat_cards = ctk.CTkFrame(self.space_body, fg_color="transparent")
        self.stat_cards.pack(fill="x", padx=10, pady=6)
        self.stat_vals = []
        for _ in range(4):
            c = _card(self.stat_cards)
            c.pack(side="left", fill="x", expand=True, padx=4)
            v = ctk.CTkLabel(c, text="—", font=_font(20, "bold"), anchor="w")
            v.pack(anchor="w", padx=14, pady=(10, 0))
            l = ctk.CTkLabel(c, text="", font=_font(11), text_color=MUTED, anchor="w")
            l.pack(anchor="w", padx=14, pady=(0, 10))
            self.stat_vals.append((v, l))

        self.cat_card = _card(self.space_body)
        self.cat_card.pack(fill="x", padx=10, pady=6)
        ctk.CTkLabel(self.cat_card, text="空间构成", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 4))
        self.cat_rows = ctk.CTkFrame(self.cat_card, fg_color="transparent")
        self.cat_rows.pack(fill="x", padx=14, pady=(0, 10))

        row = ctk.CTkFrame(self.space_body, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=10, pady=6)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        row.grid_rowconfigure(0, weight=1)
        self.dir_card = _card(row)
        self.dir_card.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        ctk.CTkLabel(self.dir_card, text="占用最大的文件夹", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 4))
        self.dir_box = ctk.CTkScrollableFrame(self.dir_card, fg_color="transparent")
        self.dir_box.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        self.file_card = _card(row)
        self.file_card.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        ctk.CTkLabel(self.file_card, text="体积最大的文件", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 4))
        self.file_box = ctk.CTkScrollableFrame(self.file_card, fg_color="transparent")
        self.file_box.pack(fill="both", expand=True, padx=6, pady=(0, 8))

    def _set_space_info(self):
        d = self.selected_drive
        if not d:
            return
        self.space_info.configure(
            text=f"当前磁盘：{d['path']} {d['label']}　剩余 {scanner.fmt_size(d['free'])} 可用")

    def _clear_box(self, box):
        for w in box.winfo_children():
            w.destroy()

    def _fill_space(self, res):
        self.space_empty.pack_forget()
        self.space_body.pack(fill="both", expand=True)
        cats = {c["name"]: c for c in res["categories"]}
        stats = [
            (scanner.fmt_size(self.selected_drive["used"] if self.selected_drive else 0), "磁盘已用"),
            (f"{res['stats']['files']:,}", "扫描文件数"),
            (scanner.fmt_size(cats.get("图片", {}).get("size", 0)), "图片占用"),
            (scanner.fmt_size(cats.get("视频", {}).get("size", 0)), "视频占用"),
        ]
        for (v, l), (val, lab) in zip(self.stat_vals, stats):
            v.configure(text=val)
            l.configure(text=lab)

        self._clear_box(self.cat_rows)
        total = sum(c["size"] for c in res["categories"]) or 1
        for c in sorted(res["categories"], key=lambda x: -x["size"]):
            if not c["size"]:
                continue
            r = ctk.CTkFrame(self.cat_rows, fg_color="transparent")
            r.pack(fill="x", pady=3)
            r.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(r, text=c["name"], width=64, anchor="w",
                         font=_font(12)).grid(row=0, column=0, sticky="w")
            pb = ctk.CTkProgressBar(r, height=9, progress_color=BRAND)
            pb.grid(row=0, column=1, sticky="ew", padx=8)
            pb.set(c["size"] / total)
            ctk.CTkLabel(r, text=f"{scanner.fmt_size(c['size'])} · {c['size']/total:.0%}",
                         width=170, anchor="e", font=_font(12),
                         text_color=MUTED).grid(row=0, column=2, sticky="e")

        self._clear_box(self.dir_box)
        for d in res["top_children"][:20]:
            r = ctk.CTkFrame(self.dir_box, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text="📁 " + _short(d["path"], 46), anchor="w",
                         font=_font(12)).pack(side="left")
            ctk.CTkLabel(r, text=scanner.fmt_size(d["size"]), width=80,
                         anchor="e", font=_font(12, "bold")).pack(side="right")
        self._clear_box(self.file_box)
        for fl in res["top_files"][:30]:
            r = ctk.CTkFrame(self.file_box, fg_color="transparent")
            r.pack(fill="x", pady=2)
            ctk.CTkLabel(r, text="📄 " + _short(fl["path"], 46), anchor="w",
                         font=_font(12)).pack(side="left")
            ctk.CTkLabel(r, text=scanner.fmt_size(fl["size"]), width=80,
                         anchor="e", font=_font(12, "bold")).pack(side="right")

    # ================= 垃圾清理 =================
    def _build_tab_junk(self, tab):
        self.junk_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.junk_scroll.pack(fill="both", expand=True, padx=10, pady=8)
        self._junk_hint("点左侧「扫描垃圾」开始分析\n🟢 可放心清理　🟡 请人工确认　🔴 系统关键，已锁定")

    def _junk_hint(self, text):
        self._clear_box(self.junk_scroll)
        c = _card(self.junk_scroll)
        c.pack(fill="x", padx=4, pady=30)
        ctk.CTkLabel(c, text=text, justify="center",
                     font=_font(13)).pack(padx=20, pady=30)

    def _tier_card(self, color, title, desc, right):
        card = _card(self.junk_scroll, border_width=1, border_color=color)
        card.pack(fill="x", padx=4, pady=8)
        h = ctk.CTkFrame(card, fg_color="transparent")
        h.pack(fill="x", padx=14, pady=(12, 4))
        dot = ctk.CTkFrame(h, width=10, height=10, fg_color=color, corner_radius=5)
        dot.pack(side="left", padx=(0, 8))
        dot.pack_propagate(False)
        ctk.CTkLabel(h, text=title, font=_font(14, "bold")).pack(side="left")
        ctk.CTkLabel(h, text=right, font=_font(12, "bold"),
                     text_color=color).pack(side="right")
        ctk.CTkLabel(card, text=desc, font=_font(11), text_color=MUTED,
                     anchor="w").pack(fill="x", padx=32, pady=(0, 6))
        body = ctk.CTkFrame(card, fg_color="transparent")
        body.pack(fill="x", padx=8, pady=(0, 10))
        return body

    def _fill_junk(self):
        self._clear_box(self.junk_scroll)
        self.green_vars.clear()
        self.yellow_vars.clear()

        gsize = sum(r["size"] for r in self.green_data)
        g = self._tier_card(C_GREEN, "可放心清理", "系统临时文件、各类缓存，删了不影响使用",
                            f"可释放 {scanner.fmt_size(gsize)}" if gsize else "暂无")
        if not self.green_data:
            ctk.CTkLabel(g, text="很干净，没发现可清理项 👏",
                         text_color=MUTED).pack(padx=24, pady=6)
        for rule in self.green_data:
            var = tk.BooleanVar(value=True)
            self.green_vars.append((var, rule))
            r = ctk.CTkFrame(g, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=3)
            ctk.CTkCheckBox(r, text="", variable=var, width=26,
                            fg_color=BRAND).pack(side="left")
            ctk.CTkLabel(r, text=f"{rule['name']}（{rule['count']} 项）",
                         font=_font(12), anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(r, text=scanner.fmt_size(rule["size"]), width=80,
                         anchor="e", font=_font(12, "bold")).pack(side="left")
            ctk.CTkButton(r, text="查看", width=52, height=26, corner_radius=8,
                          fg_color="transparent", border_width=1,
                          border_color=MUTED, text_color=MUTED,
                          command=lambda rule=rule: self._view_files(
                              rule["name"], rule["files"])).pack(side="right", padx=(8, 0))

        yd = self.yellow_data
        ycount = len(yd["downloads"]) + len(yd["installers"]) + len(yd["dups"])
        y = self._tier_card(C_YELLOW, "人工确认", "请逐项看过再删，删错了可去回收站找回",
                            f"{ycount} 项待确认" if ycount else "暂无")
        self._add_yellow_group(y, "下载目录长期未动 / 大文件", yd["downloads"])
        self._add_yellow_group(y, "下载目录里的旧安装包", yd["installers"])
        dups = yd["dups"]
        if dups:
            ctk.CTkLabel(y, text="重复文件", font=_font(12, "bold"),
                         anchor="w").pack(fill="x", padx=24, pady=(8, 2))
            for grp in dups[:60]:
                var = tk.BooleanVar(value=False)
                _keep, *rest = grp["files"]
                save = grp["size"] * (len(grp["files"]) - 1)
                self.yellow_vars.append((var, rest, save))
                r = ctk.CTkFrame(y, fg_color="transparent")
                r.pack(fill="x", padx=12, pady=2)
                ctk.CTkCheckBox(r, text="", variable=var, width=26,
                                fg_color=BRAND).pack(side="left")
                ctk.CTkLabel(r, text=f"重复 ×{len(grp['files'])}，删多余可省 {scanner.fmt_size(save)}",
                             font=_font(12), anchor="w").pack(side="left", fill="x", expand=True)
                ctk.CTkButton(r, text="查看", width=52, height=26, corner_radius=8,
                              fg_color="transparent", border_width=1,
                              border_color=MUTED, text_color=MUTED,
                              command=lambda grp=grp: self._view_files(
                                  "重复文件组", grp["files"])).pack(side="right")
            if len(dups) > 60:
                ctk.CTkLabel(y, text=f"…还有 {len(dups)-60} 组",
                             text_color=MUTED, font=_font(11)).pack(padx=24)
        if not ycount:
            ctk.CTkLabel(y, text="没有需要确认的项 👏",
                         text_color=MUTED).pack(padx=24, pady=6)

        rbox = self._tier_card(C_RED, "系统关键", "已锁定，程序里根本选不中", "禁止清理")
        for name, desc in rules.red_summary():
            ctk.CTkLabel(rbox, text=f"🔒 {name}", font=_font(12, "bold"),
                         anchor="w").pack(fill="x", padx=24, pady=(4, 0))
            ctk.CTkLabel(rbox, text=f"　　{desc}", font=_font(11),
                         text_color=MUTED, anchor="w").pack(fill="x", padx=24)

    def _add_yellow_group(self, parent, title, items):
        if not items:
            return
        ctk.CTkLabel(parent, text=title, font=_font(12, "bold"),
                     anchor="w").pack(fill="x", padx=24, pady=(8, 2))
        for it in items[:200]:
            var = tk.BooleanVar(value=False)
            self.yellow_vars.append((var, [it["path"]], it.get("size", 0)))
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            ctk.CTkCheckBox(r, text="", variable=var, width=26,
                            fg_color=BRAND).pack(side="left")
            ctk.CTkLabel(r, text="📄 " + _short(it["path"], 52), anchor="w",
                         font=_font(12)).pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(r, text=scanner.fmt_size(it["size"]), width=80,
                         anchor="e", font=_font(12, "bold")).pack(side="right")
        if len(items) > 200:
            ctk.CTkLabel(parent, text=f"…还有 {len(items)-200} 项",
                         text_color=MUTED, font=_font(11)).pack(padx=24)

    def _view_files(self, title, files):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("660x500")
        box = ctk.CTkScrollableFrame(top, label_text=f"{title}（共 {len(files)} 项）")
        box.pack(fill="both", expand=True, padx=12, pady=12)
        for fp in files[:2000]:
            ctk.CTkLabel(box, text=fp, anchor="w",
                         font=_font(11)).pack(fill="x", padx=4)
        if len(files) > 2000:
            ctk.CTkLabel(box, text=f"…还有 {len(files)-2000} 项",
                         text_color=MUTED).pack()

    # ================= 深度清理 =================
    def _build_tab_deep(self, tab):
        self.deep_scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        self.deep_scroll.pack(fill="both", expand=True, padx=10, pady=8)

        warn = _card(self.deep_scroll, border_width=1, border_color=C_RED)
        warn.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(warn, text="⚠️ 高风险区", font=_font(14, "bold"),
                     text_color=C_RED, anchor="w").pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(warn, text="以下项目删错了可能找不回来：全部默认不勾选，动手前请逐项确认。\n清理微信前请先退出微信电脑版。",
                     font=_font(12), text_color=MUTED, anchor="w",
                     justify="left").pack(fill="x", padx=14, pady=(0, 10))
        ctk.CTkButton(warn, text="🔥 开始深度扫描", height=38, corner_radius=10,
                      font=_font(13, "bold"), fg_color=C_RED, hover_color="#b23a3a",
                      command=self.start_deep_scan).pack(padx=14, pady=(0, 12))

        # 微信专清
        self.wx_card = _card(self.deep_scroll)
        self.wx_card.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(self.wx_card, text="微信专清", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 2))
        self.wx_sel_row = ctk.CTkFrame(self.wx_card, fg_color="transparent")
        self.wx_sel_row.pack(fill="x", padx=14, pady=4)
        self.wx_body = ctk.CTkFrame(self.wx_card, fg_color="transparent")
        self.wx_body.pack(fill="x", padx=8, pady=(0, 10))
        ctk.CTkLabel(self.wx_body, text="点上方「开始深度扫描」",
                     text_color=MUTED, font=_font(12)).pack(padx=14, pady=8)

        # 软件卸载
        self.app_card = _card(self.deep_scroll)
        self.app_card.pack(fill="x", padx=4, pady=8)
        h = ctk.CTkFrame(self.app_card, fg_color="transparent")
        h.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(h, text="软件卸载", font=_font(14, "bold")).pack(side="left")
        ctk.CTkButton(h, text="扫描已安装软件", width=130, height=30, corner_radius=8,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self.start_appscan).pack(side="right")
        self.app_body = ctk.CTkFrame(self.app_card, fg_color="transparent")
        self.app_body.pack(fill="x", padx=8, pady=(0, 6))
        ctk.CTkLabel(self.app_body, text="按体积排序，勾选后调用官方卸载程序",
                     text_color=MUTED, font=_font(12)).pack(padx=14, pady=8)
        self.uninstall_btn = ctk.CTkButton(self.app_card, text="🗑 卸载所选软件",
                                           height=36, corner_radius=10,
                                           font=_font(13, "bold"),
                                           fg_color=C_RED, hover_color="#b23a3a",
                                           command=self.uninstall_selected)
        self.uninstall_btn.pack(fill="x", padx=14, pady=(0, 12))

        # 应用缓存
        self.cache_card = _card(self.deep_scroll)
        self.cache_card.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(self.cache_card, text="应用缓存", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 2))
        ctk.CTkLabel(self.cache_card, text="QQ / 钉钉 / Adobe 等，深度扫描时自动统计",
                     font=_font(11), text_color=MUTED,
                     anchor="w").pack(anchor="w", padx=14)
        self.cache_body = ctk.CTkFrame(self.cache_card, fg_color="transparent")
        self.cache_body.pack(fill="x", padx=8, pady=(0, 10))

        # 系统级
        self.sys_card = _card(self.deep_scroll)
        self.sys_card.pack(fill="x", padx=4, pady=8)
        ctk.CTkLabel(self.sys_card, text="系统级", font=_font(14, "bold"),
                     anchor="w").pack(anchor="w", padx=14, pady=(10, 2))
        self.sys_body = ctk.CTkFrame(self.sys_card, fg_color="transparent")
        self.sys_body.pack(fill="x", padx=8, pady=(0, 10))
        self.deep_clean_btn = ctk.CTkButton(
            self.deep_scroll, text="🔥 执行深度清理（删所选微信/缓存项）",
            height=42, corner_radius=10, font=_font(14, "bold"),
            fg_color=C_RED, hover_color="#b23a3a",
            command=self.deep_clean_selected)
        self.deep_clean_btn.pack(fill="x", padx=4, pady=12)

    def _wx_browse(self):
        d = filedialog.askdirectory(title="选择微信数据目录（如 WeChat Files）")
        if d:
            deepclean.save_manual_wechat_dir(d)
            self.wechat_base = None  # 强制重新定位
            self.wechat_wxid = None
            self.start_deep_scan()

    def _wx_rescan(self):
        base, wxid = self.wechat_base, self.wechat_wxid
        if not base or not wxid or self._busy:
            return
        self._set_busy(True, "正在扫描微信…")

        def work():
            try:
                items = deepclean.scan_wechat(
                    base, wxid,
                    progress_cb=lambda i, n, r: self.q.put(("deep_prog", f"微信 {i}/{n}")))
                self.q.put(("wx_done", (base, wxid, items)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("junk_err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _on_wx_base(self, choice):
        self.wechat_base = choice
        wxids = deepclean.list_wxids(choice)
        self.wechat_wxid = wxids[0] if wxids else None
        self._refresh_wx_selectors()
        self._wx_rescan()

    def _on_wx_wxid(self, choice):
        self.wechat_wxid = choice
        self._wx_rescan()

    def _refresh_wx_selectors(self):
        for w in self.wx_sel_row.winfo_children():
            w.destroy()
        bases = deepclean.find_wechat_bases()
        if not bases:
            ctk.CTkLabel(self.wx_sel_row,
                         text="没找到微信数据目录，可手动指定：",
                         font=_font(12), text_color=MUTED).pack(side="left")
            ctk.CTkButton(self.wx_sel_row, text="手动指定", width=90, height=28,
                          command=self._wx_browse).pack(side="left", padx=8)
            return
        if self.wechat_base not in bases:
            self.wechat_base = bases[0]
        ctk.CTkLabel(self.wx_sel_row, text="目录", font=_font(12),
                     text_color=MUTED).pack(side="left")
        ctk.CTkOptionMenu(self.wx_sel_row, values=bases,
                          command=self._on_wx_base,
                          width=200).pack(side="left", padx=6)
        # 同步显示当前值
        for w in self.wx_sel_row.winfo_children():
            if isinstance(w, ctk.CTkOptionMenu):
                w.set(self.wechat_base)
        wxids = deepclean.list_wxids(self.wechat_base)
        if self.wechat_wxid not in wxids:
            self.wechat_wxid = wxids[0] if wxids else None
        if wxids:
            ctk.CTkLabel(self.wx_sel_row, text="账号", font=_font(12),
                         text_color=MUTED).pack(side="left", padx=(10, 0))
            om = ctk.CTkOptionMenu(self.wx_sel_row, values=wxids,
                                   command=self._on_wx_wxid, width=180)
            om.pack(side="left", padx=6)
            om.set(self.wechat_wxid)
        ctk.CTkButton(self.wx_sel_row, text="手动指定", width=80, height=28,
                      fg_color="transparent", border_width=1, border_color=MUTED,
                      text_color=MUTED, command=self._wx_browse).pack(side="left", padx=8)
        ctk.CTkButton(self.wx_sel_row, text="重新扫描", width=80, height=28,
                      fg_color=BRAND, hover_color=BRAND_HOVER,
                      command=self._wx_rescan).pack(side="left")

    def _fill_wx(self, items):
        self._clear_box(self.wx_body)
        self.wechat_vars.clear()
        if not items:
            ctk.CTkLabel(self.wx_body, text="该账号下没有可清理项",
                         text_color=MUTED, font=_font(12)).pack(padx=14, pady=8)
            return
        for it in items:
            var = tk.BooleanVar(value=False)
            self.wechat_vars.append((var, [it["path"]], it["size"]))
            r = ctk.CTkFrame(self.wx_body, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=3)
            ctk.CTkCheckBox(r, text="", variable=var, width=26,
                            fg_color=C_RED if it["level"] == "danger" else BRAND).pack(side="left")
            col = C_RED if it["level"] == "danger" else None
            t = ctk.CTkFrame(r, fg_color="transparent")
            t.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(t, text=f"{it['label']}（{it['count']:,} 项）",
                         font=_font(12, "bold" if it["level"] == "danger" else "normal"),
                         text_color=col, anchor="w").pack(anchor="w")
            ctk.CTkLabel(t, text=it["desc"], font=_font(11),
                         text_color=MUTED, anchor="w").pack(anchor="w")
            ctk.CTkLabel(r, text=scanner.fmt_size(it["size"]), width=90,
                         anchor="e", font=_font(12, "bold"),
                         text_color=col).pack(side="right")

    def _fill_caches(self, caches):
        self._clear_box(self.cache_body)
        self.appcache_vars.clear()
        if not caches:
            ctk.CTkLabel(self.cache_body, text="没发现可清理的应用缓存",
                         text_color=MUTED, font=_font(12)).pack(padx=14, pady=8)
            return
        for c in caches:
            var = tk.BooleanVar(value=False)
            self.appcache_vars.append((var, c["paths"], c["size"]))
            r = ctk.CTkFrame(self.cache_body, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=3)
            ctk.CTkCheckBox(r, text="", variable=var, width=26,
                            fg_color=BRAND).pack(side="left")
            t = ctk.CTkFrame(r, fg_color="transparent")
            t.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(t, text=c["name"], font=_font(12),
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(t, text=c["desc"], font=_font(11),
                         text_color=MUTED, anchor="w").pack(anchor="w")
            ctk.CTkLabel(r, text=scanner.fmt_size(c["size"]), width=90,
                         anchor="e", font=_font(12, "bold")).pack(side="right")

    def _fill_sys(self):
        self._clear_box(self.sys_body)
        h = self.hiber
        r = ctk.CTkFrame(self.sys_body, fg_color="transparent")
        r.pack(fill="x", padx=12, pady=6)
        t = ctk.CTkFrame(r, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True)
        if h["exists"]:
            ctk.CTkLabel(t, text="休眠文件 hiberfil.sys", font=_font(12, "bold"),
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(t, text="关闭休眠可彻底删除它，约 " + scanner.fmt_size(h["size"]),
                         font=_font(11), text_color=MUTED, anchor="w").pack(anchor="w")
            btn = ctk.CTkButton(r, text="关闭休眠并删除", width=130, height=32,
                                corner_radius=8, fg_color=C_RED, hover_color="#b23a3a",
                                command=self._disable_hiber)
            if not h["is_admin"]:
                btn.configure(state="disabled")
                ctk.CTkLabel(t, text="⚠️ 需要右键「以管理员身份运行」本软件",
                             font=_font(11), text_color=C_YELLOW,
                             anchor="w").pack(anchor="w")
            btn.pack(side="right")
        else:
            ctk.CTkLabel(t, text="休眠已关闭，没有 hiberfil.sys 👌",
                         font=_font(12), text_color=MUTED, anchor="w").pack(anchor="w")

    def start_deep_scan(self):
        if self._busy:
            return
        self._set_busy(True, "正在深度扫描…")
        self.tabs.set("深度清理")

        def work():
            try:
                bases = deepclean.find_wechat_bases()
                base = self.wechat_base if self.wechat_base in bases else (bases[0] if bases else None)
                wxid, wx_items = None, []
                if base:
                    wxids = deepclean.list_wxids(base)
                    wxid = self.wechat_wxid if self.wechat_wxid in wxids else (wxids[0] if wxids else None)
                    if wxid:
                        wx_items = deepclean.scan_wechat(
                            base, wxid,
                            progress_cb=lambda i, n, r: self.q.put(("deep_prog", f"微信 {i}/{n}")))
                self.q.put(("deep_prog", "正在统计应用缓存…"))
                caches = deepclean.scan_app_caches()
                hiber = deepclean.hiber_status()
                self.q.put(("deep_done", (bases, base, wxid, wx_items, caches, hiber)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("junk_err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def start_appscan(self):
        if self._busy:
            return
        self._set_busy(True, "正在读取已安装软件…")

        def work():
            try:
                apps = deepclean.list_installed_apps()
                for a in apps[:150]:
                    exe = deepclean.resolve_app_exe(a)
                    a["icon"] = deepclean.get_app_icon_bytes(exe) if exe else None
                self.q.put(("apps_done", apps))
            except Exception as e:  # noqa: BLE001
                self.q.put(("junk_err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _fill_apps(self, apps):
        self._clear_box(self.app_body)
        self.apps = apps
        self.app_vars.clear()
        self._app_icon_refs.clear()
        if not apps:
            ctk.CTkLabel(self.app_body, text="没读到已安装软件（可能需要管理员权限）",
                         text_color=MUTED, font=_font(12)).pack(padx=14, pady=8)
            return
        ctk.CTkLabel(self.app_body, text=f"共 {len(apps)} 个，按体积排序",
                     text_color=MUTED, font=_font(11)).pack(padx=14, pady=(4, 2), anchor="w")
        for a in apps[:150]:
            var = tk.BooleanVar(value=False)
            self.app_vars.append((var, a))
            r = ctk.CTkFrame(self.app_body, fg_color="transparent")
            r.pack(fill="x", padx=12, pady=2)
            icon_bytes = a.get("icon")
            if icon_bytes:
                try:
                    import io as _io
                    pil = Image.open(_io.BytesIO(icon_bytes))
                    ctk_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                           size=(30, 30))
                    self._app_icon_refs.append(ctk_img)
                    ctk.CTkLabel(r, image=ctk_img, text="").pack(
                        side="left", padx=(0, 6))
                except Exception:  # noqa: BLE001
                    pass
            ctk.CTkCheckBox(r, text="", variable=var, width=26,
                            fg_color=C_RED).pack(side="left")
            t = ctk.CTkFrame(r, fg_color="transparent")
            t.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(t, text=a["name"], font=_font(12), anchor="w").pack(anchor="w")
            sub = "  ".join(x for x in (a["version"], a["publisher"]) if x)
            if sub:
                ctk.CTkLabel(t, text=_short(sub, 60), font=_font(11),
                             text_color=MUTED, anchor="w").pack(anchor="w")
            sz = scanner.fmt_size(a["size"]) if a["size"] else "未知大小"
            ctk.CTkLabel(r, text=sz, width=90, anchor="e",
                         font=_font(12, "bold")).pack(side="right")
        if len(apps) > 150:
            ctk.CTkLabel(self.app_body, text=f"…还有 {len(apps)-150} 个",
                         text_color=MUTED, font=_font(11)).pack(padx=14)

    def uninstall_selected(self):
        if self._busy:
            return
        sel = [a for var, a in self.app_vars if var.get()]
        if not sel:
            messagebox.showinfo("提示", "还没勾选任何软件")
            return
        names = "\n".join("• " + a["name"] for a in sel[:15])
        if len(sel) > 15:
            names += f"\n…等共 {len(sel)} 个"
        ok = messagebox.askyesno(
            "卸载软件",
            f"将调用各软件官方卸载程序，逐个卸载以下软件：\n{names}\n\n"
            "部分软件会弹出卸载向导，请按提示完成。确定继续吗？",
            icon="warning")
        if not ok:
            return
        self._set_busy(True, "正在卸载…")

        def work():
            results = []
            for i, a in enumerate(sel):
                self.q.put(("deep_prog", f"卸载中 {i+1}/{len(sel)}：{a['name']}"))
                ok2, msg = deepclean.uninstall_app(a)
                results.append((a["name"], ok2, msg))
            self.q.put(("uninstall_done", results))

        threading.Thread(target=work, daemon=True).start()

    def _disable_hiber(self):
        if self._busy:
            return
        ok = messagebox.askyesno(
            "关闭休眠",
            "将执行 powercfg /hibernate off，删除 hiberfil.sys。\n"
            "之后电脑将无法休眠（睡眠不受影响）。确定吗？",
            icon="warning")
        if not ok:
            return
        self._set_busy(True, "正在关闭休眠…")

        def work():
            ok2, msg = deepclean.disable_hibernate()
            self.q.put(("hiber_done", (ok2, msg)))

        threading.Thread(target=work, daemon=True).start()

    def deep_clean_selected(self):
        if self._busy:
            return
        paths, size = [], 0
        for var, plist, sz in self.wechat_vars:
            if var.get():
                paths.extend(plist)
                size += sz
        for var, plist, sz in self.appcache_vars:
            if var.get():
                paths.extend(plist)
                size += sz
        seen, out = set(), []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        if not out:
            messagebox.showinfo("提示", "还没勾选任何深度清理项")
            return
        ok = messagebox.askyesno(
            "深度清理确认",
            f"⚠️ 即将把 {len(out)} 项（约 {scanner.fmt_size(size)}）移入回收站。\n"
            "其中可能包含微信聊天文件，删除后聊天里将无法查看。\n\n"
            "确定继续吗？",
            icon="warning")
        if not ok:
            return
        self._set_busy(True, "正在深度清理…")

        def work():
            def prog(done_b, total_b, i, n):
                self.q.put(("clean_prog", (done_b, total_b, i, n)))
            result = cleaner.safe_delete(out, total_size=size, progress_cb=prog)
            self.q.put(("clean_done", result))

        threading.Thread(target=work, daemon=True).start()

    # ================= 后台任务 =================
    def _set_busy(self, busy, text=""):
        self._busy = busy
        if busy:
            self.prog.start()
            self.status_label.configure(text=text)
        else:
            self.prog.stop()
            self.prog.set(0)
            self.status_label.configure(text=text or "就绪 — 选择磁盘，开始扫描")

    def start_scan(self):
        if self._busy or not self.selected_drive:
            return
        root = self.selected_drive["path"]
        self._set_busy(True, f"正在扫描 {root} …")
        self.tabs.set("空间分析")
        cancel = threading.Event()
        self._scan_cancel = cancel

        def work():
            try:
                res = scanner.scan_drive(
                    root,
                    progress_cb=lambda n, p: self.q.put(("scan_prog", n, p)),
                    cancel=cancel)
                self.q.put(("scan_done", res))
            except scanner.ScanCancelled:
                self.q.put(("scan_cancel", None))

        threading.Thread(target=work, daemon=True).start()

    def stop_scan(self):
        if self._scan_cancel:
            self._scan_cancel.set()
            self.status_label.configure(text="正在停止扫描…")

    def start_junk_scan(self):
        if self._busy:
            return
        self._set_busy(True, "正在分析垃圾…")
        self.tabs.set("垃圾清理")

        def work():
            try:
                green = rules.scan_green()
                self.q.put(("junk_prog", "绿档扫描完成"))
                downloads = rules.scan_downloads()
                self.q.put(("junk_prog", "下载目录扫描完成"))
                installers = rules.scan_old_installers()
                self.q.put(("junk_prog", "旧安装包扫描完成"))
                dups = rules.find_duplicates(rules.user_roots())
                self.q.put(("junk_done", (green, downloads, installers, dups)))
            except Exception as e:  # noqa: BLE001
                self.q.put(("junk_err", str(e)))

        threading.Thread(target=work, daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "scan_prog":
                    _n, p = msg[1], msg[2]
                    now = time.time()
                    if now - self._last_prog_ui > 0.3:
                        self._last_prog_ui = now
                        self.status_label.configure(text=f"扫描中：{_short(p)}")
                elif kind == "scan_done":
                    self._scan_cancel = None
                    res = msg[1]
                    self.scan_result = res
                    st = res["stats"]
                    self._set_busy(False,
                                   f"扫描完成：{st['files']:,} 个文件 / {st['dirs']:,} 个目录，用时 {st['seconds']}s")
                    self._fill_space(res)
                    self._set_space_info()
                    messagebox.showinfo("扫描完成",
                                        f"共 {st['files']:,} 个文件，{st['dirs']:,} 个目录，"
                                        f"用时 {st['seconds']} 秒")
                elif kind == "scan_cancel":
                    self._scan_cancel = None
                    self._set_busy(False, "扫描已取消")
                elif kind == "junk_prog":
                    self.status_label.configure(text=msg[1] + "…")
                elif kind == "junk_done":
                    green, downloads, installers, dups = msg[1]
                    self.green_data = green
                    self.yellow_data = {"downloads": downloads,
                                        "installers": installers, "dups": dups}
                    self._set_busy(False, "垃圾分析完成")
                    self._fill_junk()
                elif kind == "junk_err":
                    self._set_busy(False, "分析出错")
                    messagebox.showerror("出错了", msg[1])
                elif kind == "deep_prog":
                    self.status_label.configure(text=msg[1] + "…")
                elif kind == "deep_done":
                    bases, base, wxid, wx_items, caches, hiber = msg[1]
                    self.wechat_base, self.wechat_wxid = base, wxid
                    self.wechat_items = wx_items
                    self.hiber = hiber
                    self._set_busy(False, "深度扫描完成")
                    self._refresh_wx_selectors()
                    self._fill_wx(wx_items)
                    self._fill_caches(caches)
                    self._fill_sys()
                elif kind == "wx_done":
                    base, wxid, items = msg[1]
                    self.wechat_base, self.wechat_wxid = base, wxid
                    self.wechat_items = items
                    self._set_busy(False, "微信扫描完成")
                    self._fill_wx(items)
                elif kind == "apps_done":
                    self._set_busy(False, "已安装软件读取完成")
                    self._fill_apps(msg[1])
                elif kind == "uninstall_done":
                    results = msg[1]
                    self._set_busy(False, "卸载完成")
                    ok_n = sum(1 for _n, ok, _m in results if ok)
                    detail = "\n".join(
                        f"{'✓' if ok else '✗'} {n}" for n, ok, _m in results[:20])
                    messagebox.showinfo("卸载完成",
                                        f"成功执行：{ok_n}/{len(results)}\n{detail}")
                    self.start_appscan()
                elif kind == "hiber_done":
                    ok, info = msg[1]
                    self.hiber = deepclean.hiber_status()
                    self._set_busy(False, "休眠已关闭" if ok else "操作失败")
                    self._fill_sys()
                    messagebox.showinfo("休眠", info)
                elif kind == "clean_prog":
                    done_b, total_b, i, n = msg[1]
                    if total_b:
                        self.prog.configure(mode="determinate")
                        self.prog.set(max(0.0, min(1.0, done_b / total_b)))
                        self.status_label.configure(
                            text=f"正在清理 {i}/{n}…已清理约 "
                                 f"{scanner.fmt_size(done_b)} / {scanner.fmt_size(total_b)}")
                    else:
                        self.status_label.configure(text=f"正在清理 {i}/{n}…")
                elif kind == "clean_done":
                    result = msg[1]
                    self.prog.configure(mode="indeterminate")
                    self._set_busy(False, "清理完成")
                    n_del = len(result["deleted"])
                    n_block = len(result["blocked"])
                    n_fail = len(result["failed"])
                    messagebox.showinfo(
                        "清理完成",
                        f"已移到回收站：{n_del} 项\n"
                        f"被保护拦截：{n_block} 项\n"
                        f"失败：{n_fail} 项\n"
                        f"日志：{result['log'] or '写入失败'}")
                    self.start_junk_scan()
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    # ================= 清理 =================
    def _collect_checked(self):
        paths, size = [], 0
        for var, rule in self.green_vars:
            if var.get():
                paths.extend(rule["files"])
                size += rule["size"]
        for var, plist, sz in self.yellow_vars:
            if var.get():
                paths.extend(plist)
                size += sz
        seen, out = set(), []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out, size

    def clean_green(self):
        if self._busy:
            return
        if not self.green_data:
            messagebox.showinfo("提示", "还没有扫描结果，先点「扫描垃圾」")
            return
        paths, size = [], 0
        for _var, rule in self.green_vars:
            paths.extend(rule["files"])
            size += rule["size"]
        self._do_clean(paths, "一键清理绿档", size)

    def clean_selected(self):
        if self._busy:
            return
        paths, size = self._collect_checked()
        if not paths:
            messagebox.showinfo("提示", "还没勾选任何可清理项")
            return
        self._do_clean(paths, "清理所选", size)

    def _do_clean(self, paths, title, total_size=0):
        # total_size 用扫描时的已知值，不再全盘重算（之前这里是慢的元凶之一）
        ok = messagebox.askyesno(
            title,
            f"即将把 {len(paths):,} 项（约 {scanner.fmt_size(total_size)}）移入回收站。\n"
            "回收站可还原，但仍请确认。\n\n确定继续吗？")
        if not ok:
            return
        self._set_busy(True, "正在清理…")

        def work():
            def prog(done_b, total_b, i, n):
                self.q.put(("clean_prog", (done_b, total_b, i, n)))
            result = cleaner.safe_delete(paths, total_size=total_size,
                                         progress_cb=prog)
            self.q.put(("clean_done", result))

        threading.Thread(target=work, daemon=True).start()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
