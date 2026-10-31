@echo off
chcp 65001 >nul
echo 正在安装依赖...
pip install -r requirements.txt
echo 正在打包单文件 exe ...
pyinstaller --noconfirm --onefile --windowed ^
  --name DeepClean ^
  --icon assets/icon.ico ^
  --add-data "assets/logo.png;assets" ^
  --collect-all customtkinter ^
  src\main.py
echo.
echo 打包完成: dist\深度清理工具.exe
pause
