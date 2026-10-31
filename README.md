# 深度清理工具 🧹

给"电脑满了但不知道删哪"的人用的 **Windows 绿色小工具**：单文件 exe，微信发过去、双击即用，不用安装。

## 功能（v0.1 第一版）

| 模块 | 说明 |
|---|---|
| 🔍 全盘扫描 | 列出所有磁盘，每个盘的空间构成（图片/视频/文档/安装包…各占多少）、最大文件夹 TOP、最大文件 TOP |
| 🟢 可放心清理 | 系统临时文件、浏览器缓存、更新残留、缩略图缓存等，一键清理 |
| 🟡 人工确认 | 下载目录长期未动的大文件、旧安装包、重复文件——列出来逐项看 |
| 🔴 禁止触碰 | Windows 系统目录、Program Files 等直接锁死，程序里根本选不中 |
| 🗑️ 安全删除 | **所有删除一律进回收站**（可还原），每次清理写日志，未知文件默认归人工确认 |

## 给朋友用（微信发送）

1. 拿到 `深度清理工具.exe`（约 30–40MB，微信可直接发）
2. 双击打开 → 选磁盘 → **开始扫盘**
3. 点 **扫描垃圾** → 勾选 → 清理

不需要管理员权限，不用安装，不写注册表。

## 自己打包 exe（Windows 电脑上）

```bat
pip install -r requirements.txt
build.bat
```

产物在 `dist\深度清理工具.exe`。

## GitHub Actions 自动打包

push 一个 tag 即自动在云端打包 Windows exe 并挂到 Release：

```bash
git tag v0.1.0 && git push origin v0.1.0
```

也可以在 Actions 页点 **Run workflow** 手动触发，产物在 Artifacts 下载。

## 目录结构

```
src/
  main.py        入口
  ui_app.py      界面（customtkinter）
  scanner.py     扫描引擎：分类统计/大文件/大目录/图片视频清单
  rules.py       三档规则：绿/黄/红 + 白名单
  cleaner.py     回收站删除 + 日志
build.bat                  本地一键打包
.github/workflows/build.yml  云端自动打包
```

## 安全设计

- 红档路径双重拦截：UI 锁死 + `cleaner.safe_delete` 二次校验
- 删除走系统回收站（Windows 用 `SHFileOperation` / `send2trash`），不是彻底删除
- 扫盘是只读操作，不修改任何文件
- 未知文件一律归为"人工确认"，程序不替用户做决定
