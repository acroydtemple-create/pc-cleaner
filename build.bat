@echo off
chcp 65001 >nul
echo 正在安装依赖...
pip install -r requirements.txt
echo 正在打包单文件 exe ...
pyinstaller --noconfirm --onefile --windowed ^
  --name "深度清理工具" ^
  --collect-all customtkinter ^
  --collect-all imageio_ffmpeg ^
  src\main.py
echo.
echo 打包完成: dist\深度清理工具.exe
pause
