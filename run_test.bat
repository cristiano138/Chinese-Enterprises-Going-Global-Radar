@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo 正在启动链路自检...
echo.
python test_connection.py
if errorlevel 1 (
  echo.
  echo [!] 如果上面提示找不到 python，说明 Python 没装到系统里。
  echo     把这段截图发给助手即可。
  echo.
  pause
)
