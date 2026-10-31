# -*- coding: utf-8 -*-
"""主界面：customtkinter 深色中文 UI"""
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk
from PIL import Image

import scanner
import rules
import cleaner
import previewer
from version import __version__, APP_NAME

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")


def _short(path, n=58):
    if len(path) <= n:
        return path
    return path[: n // 2 - 2] + "…" + path[-(n // 2 - 2):]


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP_NAME} v{__version__}")
        self.geometry("1220x780")
        self.minsize(1020, 640)

        self.q = queue.Queue()
        self.drives = []
        self.selected_drive = None
        self.scan_result = None
        self.green_data = []
        self.yellow_data = {"downloads": [], "installers": [], "dups": []}
        self.green_vars = []     # [(BooleanVar, rule)]
        self.yellow_vars = []    # [(BooleanVar, [paths])]
        self.img_items = []      # 扫描到的图片清单
        self.vid_items = []
        self._img_widgets = []
        self._vid_widgets = []
        self._img_cursor = 0
        self._vid_cursor = 0
        self._busy = False

        self._build_sidebar()
        self._build_main()
        self._build_status()
        self.refresh_drives()
        self.after(120, self._poll_queue)

    # ---------------- 布局 ----------------
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=230, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(sb, text="🧹 " + APP_NAME,
                     font=ctk.CTkFont(size=18, weight="bold")).pack(pady=(18, 4))
        ctk.CTkLabel(sb, text=f"v{__version__} · 让清理看得见",
                     font=ctk.CTkFont(size=12), text_color="gray").pack(pady=(0, 12))

        ctk.CTkLabel(sb, text="磁盘", font=ctk.CTkFont(size=13, weight="bold"),
                     anchor="w").pack(fill="x", padx=16)
        self.drive_box = ctk.CTkScrollableFrame(sb, height=190)
        self.drive_box.pack(fill="x", padx=12, pady=(4, 10))

        for txt, cmd in [
            ("🔄 刷新磁盘", self.refresh_drives),
            ("🔍 开始扫盘", self.start_scan),
            ("🧪 扫描垃圾", self.start_junk_scan),
        ]:
            ctk.CTkButton(sb, text=txt, command=cmd).pack(fill="x", padx=16, pady=4)

        ctk.CTkLabel(sb, text="").pack(pady=4)
        self.clean_btn = ctk.CTkButton(sb, text="⚡ 一键清理绿档",
                                       fg_color="#1f7a3a", hover_color="#16602c",
                                       command=self.clean_green)
        self.clean_btn.pack(fill="x", padx=16, pady=4)
        ctk.CTkButton(sb, text="🗑 清理所选", command=self.clean_selected).pack(
            fill="x", padx=16, pady=4)

        ctk.CTkLabel(sb, text="删除一律进回收站\n可随时还原",
                     font=ctk.CTkFont(size=11), text_color="gray",
                     justify="center").pack(side="bottom", pady=16)

    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 8), pady=8)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)

        self.tabs = ctk.CTkTabview(main)
        self.tabs.grid(row=0, column=0, sticky="nsew")
        for name in ("空间分析", "垃圾清理", "图片浏览", "视频浏览"):
            self.tabs.add(name)
        self._build_tab_space(self.tabs.tab("空间分析"))
        self._build_tab_junk(self.tabs.tab("垃圾清理"))
        self._build_tab_images(self.tabs.tab("图片浏览"))
        self._build_tab_videos(self.tabs.tab("视频浏览"))

    def _build_status(self):
        bar = ctk.CTkFrame(self, height=34, corner_radius=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.status_label = ctk.CTkLabel(bar, text="就绪", anchor="w",
                                         font=ctk.CTkFont(size=12))
        self.status_label.pack(side="left", padx=12)
        self.prog = ctk.CTkProgressBar(bar, width=220)
        self.prog.pack(side="right", padx=12, pady=8)
        self.prog.set(0)

    # ---------------- 磁盘 ----------------
    def refresh_drives(self):
        for w in self.drive_box.winfo_children():
            w.destroy()
        self.drives = scanner.list_drives()
        for d in self.drives:
            pct = (d["used"] / d["total"]) if d["total"] else 0
            txt = f"{d['path']} {d['label']}\n{scanner.fmt_size(d['used'])} / {scanner.fmt_size(d['total'])}"
            b = ctk.CTkButton(self.drive_box, text=txt,
                              anchor="w", height=52,
                              fg_color="transparent", text_color=("black", "white"),
                              hover_color=("gray75", "gray25"),
                              command=lambda d=d: self.select_drive(d))
            b.pack(fill="x", pady=2)
            pb = ctk.CTkProgressBar(self.drive_box, height=6)
            pb.pack(fill="x", padx=8, pady=(0, 4))
            pb.set(pct)
            d["_btn"] = b
        if self.drives and not self.selected_drive:
            self.select_drive(self.drives[0])

    def select_drive(self, d):
        self.selected_drive = d
        for x in self.drives:
            x["_btn"].configure(
                fg_color=("#3b8ed0", "#1f6aa5") if x is d else "transparent")
        self._set_space_info()

    # ---------------- 空间分析页 ----------------
    def _build_tab_space(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        self.space_info = ctk.CTkLabel(tab, text="请选择磁盘并开始扫盘",
                                       font=ctk.CTkFont(size=13), anchor="w")
        self.space_info.pack(fill="x", padx=8, pady=6)

        self.cat_box = ctk.CTkScrollableFrame(tab, label_text="各类文件占用")
        self.cat_box.pack(fill="both", expand=True, padx=8, pady=4)

        row = ctk.CTkFrame(tab, fg_color="transparent")
        row.pack(fill="both", expand=True, padx=8, pady=4)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        self.dir_box = ctk.CTkScrollableFrame(row, label_text="最大文件夹 TOP")
        self.dir_box.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self.file_box = ctk.CTkScrollableFrame(row, label_text="最大文件 TOP")
        self.file_box.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

    def _set_space_info(self):
        d = self.selected_drive
        if not d:
            return
        self.space_info.configure(
            text=f"当前：{d['path']} {d['label']}  已用 {scanner.fmt_size(d['used'])}"
                 f" / 共 {scanner.fmt_size(d['total'])}"
                 f"（剩余 {scanner.fmt_size(d['free'])}）")

    def _clear_box(self, box):
        for w in box.winfo_children():
            w.destroy()

    def _fill_space(self, res):
        self._clear_box(self.cat_box)
        total = sum(c["size"] for c in res["categories"]) or 1
        for c in sorted(res["categories"], key=lambda x: -x["size"]):
            if not c["size"]:
                continue
            f = ctk.CTkFrame(self.cat_box, fg_color="transparent")
            f.pack(fill="x", pady=2)
            ctk.CTkLabel(f, text=f"{c['name']}", width=70, anchor="w").pack(side="left")
            pb = ctk.CTkProgressBar(f, width=220, height=10)
            pb.pack(side="left", padx=8)
            pb.set(c["size"] / total)
            ctk.CTkLabel(
                f,
                text=f"{scanner.fmt_size(c['size'])}（{c['size']/total:.0%}）· {c['count']} 个",
                anchor="w").pack(side="left")
        self._clear_box(self.dir_box)
        for d in res["top_children"][:20]:
            r = ctk.CTkFrame(self.dir_box, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=_short(d["path"]), anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=scanner.fmt_size(d["size"]),
                         width=90, anchor="e").pack(side="right")
        self._clear_box(self.file_box)
        for fl in res["top_files"][:30]:
            r = ctk.CTkFrame(self.file_box, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=_short(fl["path"]), anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=scanner.fmt_size(fl["size"]),
                         width=90, anchor="e").pack(side="right")

    # ---------------- 垃圾清理页 ----------------
    def _build_tab_junk(self, tab):
        self.junk_scroll = ctk.CTkScrollableFrame(tab, label_text="三档清理建议")
        self.junk_scroll.pack(fill="both", expand=True, padx=8, pady=6)
        self._junk_hint("点左侧「扫描垃圾」开始分析。\n"
                        "🟢 绿档：可放心清理 ｜ 🟡 黄档：请人工确认 ｜ 🔴 红档：系统关键，禁止触碰")

    def _junk_hint(self, text):
        self._clear_box(self.junk_scroll)
        ctk.CTkLabel(self.junk_scroll, text=text, justify="left",
                     font=ctk.CTkFont(size=13)).pack(padx=12, pady=20)

    def _fill_junk(self):
        self._clear_box(self.junk_scroll)
        self.green_vars.clear()
        self.yellow_vars.clear()

        g = ctk.CTkFrame(self.junk_scroll, border_width=1, border_color="#1f7a3a")
        g.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(g, text="🟢 可放心清理（默认全选）",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#4ade80").pack(anchor="w", padx=10, pady=6)
        if not self.green_data:
            ctk.CTkLabel(g, text="未发现可清理项", text_color="gray").pack(padx=16, pady=4)
        for rule in self.green_data:
            var = tk.BooleanVar(value=True)
            self.green_vars.append((var, rule))
            r = ctk.CTkFrame(g, fg_color="transparent")
            r.pack(fill="x", padx=8, pady=2)
            ctk.CTkCheckBox(r, text="", variable=var, width=24).pack(side="left")
            ctk.CTkLabel(
                r,
                text=f"{rule['name']}（{rule['count']} 项，{scanner.fmt_size(rule['size'])}）",
                anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(r, text="查看文件", width=70,
                          command=lambda rule=rule: self._view_files(
                              rule["name"], rule["files"])).pack(side="right")

        y = ctk.CTkFrame(self.junk_scroll, border_width=1, border_color="#b98a1d")
        y.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(y, text="🟡 人工确认（请逐项查看后再删）",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#fbbf24").pack(anchor="w", padx=10, pady=6)
        self._add_yellow_group(y, "下载目录长期未动 / 大文件",
                               self.yellow_data["downloads"])
        self._add_yellow_group(y, "下载目录里的旧安装包",
                               self.yellow_data["installers"])
        dups = self.yellow_data["dups"]
        if dups:
            ctk.CTkLabel(y, text=f"重复文件（{len(dups)} 组）：",
                         font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(6, 2))
            for grp in dups[:60]:
                var = tk.BooleanVar(value=False)
                keep, *rest = grp["files"]
                self.yellow_vars.append((var, rest))
                save = grp["size"] * (len(grp["files"]) - 1)
                r = ctk.CTkFrame(y, fg_color="transparent")
                r.pack(fill="x", padx=8, pady=1)
                ctk.CTkCheckBox(r, text="", variable=var, width=24).pack(side="left")
                ctk.CTkLabel(
                    r, text=f"重复 ×{len(grp['files'])}，删多余可省 {scanner.fmt_size(save)}",
                    anchor="w").pack(side="left")
                ctk.CTkButton(r, text="看哪几份", width=70,
                              command=lambda grp=grp: self._view_files(
                                  "重复文件组", grp["files"])).pack(side="right")
            if len(dups) > 60:
                ctk.CTkLabel(y, text=f"…还有 {len(dups)-60} 组",
                             text_color="gray").pack(padx=16)

        rbox = ctk.CTkFrame(self.junk_scroll, border_width=1, border_color="#a12525")
        rbox.pack(fill="x", padx=6, pady=6)
        ctk.CTkLabel(rbox, text="🔴 系统关键（已锁定，禁止清理）",
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#f87171").pack(anchor="w", padx=10, pady=6)
        for name, desc in rules.red_summary():
            ctk.CTkLabel(rbox, text=f"🔒 {name} —— {desc}",
                         anchor="w", text_color="gray").pack(fill="x", padx=16, pady=1)

    def _add_yellow_group(self, parent, title, items):
        if not items:
            return
        ctk.CTkLabel(parent, text=f"{title}（{len(items)} 项）：",
                     font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=16, pady=(6, 2))
        for it in items[:200]:
            var = tk.BooleanVar(value=False)
            self.yellow_vars.append((var, [it["path"]]))
            r = ctk.CTkFrame(parent, fg_color="transparent")
            r.pack(fill="x", padx=8, pady=1)
            ctk.CTkCheckBox(r, text="", variable=var, width=24).pack(side="left")
            ctk.CTkLabel(r, text=_short(it["path"]), anchor="w").pack(
                side="left", fill="x", expand=True)
            ctk.CTkLabel(r, text=scanner.fmt_size(it["size"]),
                         width=90, anchor="e").pack(side="right")
        if len(items) > 200:
            ctk.CTkLabel(parent, text=f"…还有 {len(items)-200} 项",
                         text_color="gray").pack(padx=16)

    def _view_files(self, title, files):
        top = ctk.CTkToplevel(self)
        top.title(title)
        top.geometry("640x480")
        box = ctk.CTkScrollableFrame(top, label_text=f"{title}（共 {len(files)} 项）")
        box.pack(fill="both", expand=True, padx=10, pady=10)
        for fp in files[:2000]:
            ctk.CTkLabel(box, text=fp, anchor="w",
                         font=ctk.CTkFont(size=11)).pack(fill="x", padx=4)
        if len(files) > 2000:
            ctk.CTkLabel(box, text=f"…还有 {len(files)-2000} 项",
                         text_color="gray").pack()

    # ---------------- 图片 / 视频页 ----------------
    def _build_tab_images(self, tab):
        self.img_tip = ctk.CTkLabel(tab, text="扫盘后这里会列出所有图片，点开放大看",
                                    text_color="gray")
        self.img_tip.pack(pady=6)
        self.img_grid = ctk.CTkScrollableFrame(tab, label_text="图片")
        self.img_grid.pack(fill="both", expand=True, padx=8, pady=4)

    def _build_tab_videos(self, tab):
        self.vid_tip = ctk.CTkLabel(tab, text="扫盘后这里会列出所有视频封面，双击播放",
                                    text_color="gray")
        self.vid_tip.pack(pady=6)
        self.vid_grid = ctk.CTkScrollableFrame(tab, label_text="视频")
        self.vid_grid.pack(fill="both", expand=True, padx=8, pady=4)

    def _fill_media(self):
        for w in self._img_widgets + self._vid_widgets:
            w.destroy()
        self._img_widgets.clear()
        self._vid_widgets.clear()
        self.img_items = sorted(self.scan_result["images"], key=lambda x: -x["size"])
        self.vid_items = sorted(self.scan_result["videos"], key=lambda x: -x["size"])
        self.img_tip.configure(
            text=f"共 {len(self.img_items)} 张图片（按体积排序），点开放大")
        self.vid_tip.configure(
            text=f"共 {len(self.vid_items)} 个视频（按体积排序），双击用系统播放器打开")
        self._img_cursor = 0
        self._vid_cursor = 0
        self._load_img_batch()
        self._load_vid_batch()

    def _load_img_batch(self, batch=48):
        items = self.img_items[self._img_cursor:self._img_cursor + batch]
        if not items:
            return
        cols = 4
        for i, it in enumerate(items):
            idx = self._img_cursor + i
            th = previewer.image_thumbnail(it["path"])
            cell = ctk.CTkFrame(self.img_grid, fg_color="transparent",
                                width=200, height=230)
            cell.grid(row=idx // cols, column=idx % cols, padx=6, pady=6)
            cell.grid_propagate(False)
            if th:
                img = ctk.CTkImage(light_image=th, dark_image=th, size=(180, 180))
                lbl = ctk.CTkLabel(cell, image=img, text="")
                lbl.image = img
            else:
                lbl = ctk.CTkLabel(cell, text="🖼️\n无法预览", height=180)
            lbl.pack()
            lbl.bind("<Button-1>", lambda e, it=it: self._preview_image(it))
            name = os.path.basename(it["path"])
            ctk.CTkLabel(cell, text=_short(name, 24),
                         font=ctk.CTkFont(size=11)).pack()
            ctk.CTkLabel(cell, text=scanner.fmt_size(it["size"]),
                         font=ctk.CTkFont(size=11), text_color="gray").pack()
            self._img_widgets.append(cell)
        self._img_cursor += len(items)
        if self._img_cursor < len(self.img_items):
            self.after(300, self._load_img_batch)

    def _load_vid_batch(self, batch=24):
        items = self.vid_items[self._vid_cursor:self._vid_cursor + batch]
        if not items:
            return
        cols = 3
        for i, it in enumerate(items):
            idx = self._vid_cursor + i
            cv = previewer.video_cover(it["path"])
            cell = ctk.CTkFrame(self.vid_grid, fg_color="transparent",
                                width=300, height=250)
            cell.grid(row=idx // cols, column=idx % cols, padx=6, pady=6)
            cell.grid_propagate(False)
            if cv:
                img = ctk.CTkImage(light_image=cv, dark_image=cv, size=(280, 158))
                lbl = ctk.CTkLabel(cell, image=img, text="")
                lbl.image = img
            else:
                lbl = ctk.CTkLabel(cell, text="🎬\n封面提取失败", height=158)
            lbl.pack()
            lbl.bind("<Double-Button-1>", lambda e, it=it: self._play_video(it))
            name = os.path.basename(it["path"])
            ctk.CTkLabel(cell, text=_short(name, 34),
                         font=ctk.CTkFont(size=11)).pack()
            ctk.CTkLabel(cell, text=scanner.fmt_size(it["size"]),
                         font=ctk.CTkFont(size=11), text_color="gray").pack()
            self._vid_widgets.append(cell)
        self._vid_cursor += len(items)
        if self._vid_cursor < len(self.vid_items):
            self.after(500, self._load_vid_batch)

    def _preview_image(self, it):
        top = ctk.CTkToplevel(self)
        top.title(os.path.basename(it["path"]))
        top.geometry("900x700")
        im = previewer.image_full(it["path"])
        if im:
            img = ctk.CTkImage(light_image=im, dark_image=im,
                               size=(min(im.width, 860), min(im.height, 600)))
            lbl = ctk.CTkLabel(top, image=img, text="")
            lbl.image = img
            lbl.pack(pady=10)
        ctk.CTkLabel(top, text=f"{it['path']}\n{scanner.fmt_size(it['size'])}",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(pady=6)

    def _play_video(self, it):
        try:
            if os.name == "nt":
                os.startfile(it["path"])  # noqa: S606
            else:
                import subprocess
                subprocess.Popen(["xdg-open", it["path"]])
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("打不开", str(e))

    # ---------------- 后台任务 ----------------
    def _set_busy(self, busy, text=""):
        self._busy = busy
        if busy:
            self.prog.start()
            self.status_label.configure(text=text)
        else:
            self.prog.stop()
            self.prog.set(0)
            self.status_label.configure(text=text or "就绪")

    def start_scan(self):
        if self._busy or not self.selected_drive:
            return
        root = self.selected_drive["path"]
        self._set_busy(True, f"正在扫描 {root} …")
        cancel = threading.Event()

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
                    self.status_label.configure(text=f"扫描中：{_short(p)}")
                elif kind == "scan_done":
                    res = msg[1]
                    self.scan_result = res
                    st = res["stats"]
                    self._set_busy(False,
                                   f"扫描完成：{st['dirs']} 个目录 / {st['files']} 个文件，用时 {st['seconds']}s")
                    self._fill_space(res)
                    self._fill_media()
                    self._set_space_info()
                    messagebox.showinfo("扫描完成",
                                        f"共 {st['files']} 个文件，{st['dirs']} 个目录，"
                                        f"用时 {st['seconds']} 秒")
                elif kind == "scan_cancel":
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
                elif kind == "clean_done":
                    result = msg[1]
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

    # ---------------- 清理 ----------------
    def _collect_checked(self):
        paths = []
        for var, rule in self.green_vars:
            if var.get():
                paths.extend(rule["files"])
        for var, plist in self.yellow_vars:
            if var.get():
                paths.extend(plist)
        # 去重，保持顺序
        seen, out = set(), []
        for p in paths:
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    def clean_green(self):
        if self._busy:
            return
        if not self.green_data:
            messagebox.showinfo("提示", "还没有扫描结果，先点「扫描垃圾」")
            return
        paths = []
        for _var, rule in self.green_vars:
            paths.extend(rule["files"])
        self._do_clean(paths, "一键清理绿档")

    def clean_selected(self):
        if self._busy:
            return
        paths = self._collect_checked()
        if not paths:
            messagebox.showinfo("提示", "还没勾选任何可清理项")
            return
        self._do_clean(paths, "清理所选")

    def _do_clean(self, paths, title):
        size = cleaner.total_size(paths)
        ok = messagebox.askyesno(
            title,
            f"即将把 {len(paths)} 项（约 {scanner.fmt_size(size)}）移入回收站。\n"
            "回收站可还原，但仍请确认。\n\n确定继续吗？")
        if not ok:
            return
        self._set_busy(True, "正在清理…")

        def work():
            result = cleaner.safe_delete(paths)
            self.q.put(("clean_done", result))

        threading.Thread(target=work, daemon=True).start()


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
