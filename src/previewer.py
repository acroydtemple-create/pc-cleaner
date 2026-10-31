# -*- coding: utf-8 -*-
"""
预览模块
- 图片：PIL 生成缩略图（自动纠正 EXIF 方向），结果缓存到临时目录
- 视频：用 imageio-ffmpeg 自带的 ffmpeg 抽一帧做封面，缓存复用
所有失败都返回 None，调用方显示占位图。
"""
import os
import hashlib
import subprocess
import tempfile

from PIL import Image, ImageOps

_CACHE_DIR = os.path.join(tempfile.gettempdir(), "deepclean_thumbs")
os.makedirs(_CACHE_DIR, exist_ok=True)


def _cache_key(path, size):
    try:
        st = os.stat(path)
        raw = f"{path}|{st.st_size}|{st.st_mtime}|{size}"
    except OSError:
        raw = f"{path}|{size}"
    return hashlib.md5(raw.encode("utf-8", "ignore")).hexdigest() + ".jpg"


def image_thumbnail(path, size=(240, 240)):
    """返回 PIL.Image（RGB 缩略图），失败返回 None"""
    ck = os.path.join(_CACHE_DIR, _cache_key(path, size))
    try:
        if os.path.isfile(ck):
            return Image.open(ck).convert("RGB")
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im.thumbnail(size, Image.LANCZOS)
            # 居中贴到纯色底上，保证网格对齐
            canvas = Image.new("RGB", size, (24, 24, 28))
            canvas.paste(im, ((size[0] - im.width) // 2,
                              (size[1] - im.height) // 2))
            canvas.save(ck, "JPEG", quality=82)
            return canvas
    except Exception:
        return None


def image_full(path, max_side=1280):
    """预览大图：按最长边缩放，失败返回 None"""
    try:
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((max_side, max_side), Image.LANCZOS)
            return im.copy()
    except Exception:
        return None


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        return exe if exe and os.path.isfile(exe) else None
    except Exception:
        return None


def video_cover(path, size=(320, 180)):
    """抽一帧做视频封面，返回 PIL.Image，失败返回 None"""
    ck = os.path.join(_CACHE_DIR, "v_" + _cache_key(path, size))
    try:
        if os.path.isfile(ck):
            return Image.open(ck).convert("RGB")
        exe = _ffmpeg_exe()
        if not exe:
            return None
        w, h = size
        vf = (f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
              f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x181820")
        ok = False
        for ss in ("1", "0"):
            cmd = [exe, "-y", "-v", "error", "-ss", ss, "-i", path,
                   "-vframes", "1", "-vf", vf, ck]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30,
                               check=False)
            except Exception:
                continue
            if os.path.isfile(ck) and os.path.getsize(ck) > 0:
                ok = True
                break
        if not ok:
            return None
        return Image.open(ck).convert("RGB")
    except Exception:
        return None


def clear_cache():
    for fn in os.listdir(_CACHE_DIR):
        try:
            os.remove(os.path.join(_CACHE_DIR, fn))
        except OSError:
            pass
