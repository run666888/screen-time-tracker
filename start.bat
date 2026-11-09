@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 正在启动屏幕使用时间追踪...
echo.

REM 检查 tracker 是否已在运行
tasklist /FI "IMAGENAME eq pythonw.exe" /FO CSV | findstr /C:"pythonw.exe" >nul
if %errorlevel% equ 0 (
    echo 检测到后台采集程序已在运行
) else (
    echo 启动后台采集程序...
    start "" /MIN pythonw.exe tracker.py
    timeout /t 2 /nobreak >nul
)

REM 启动面板
echo 启动 Web 面板 (http://127.0.0.1:19999)...
start "" pythonw.exe server.py
timeout /t 3 /nobreak >nul
start http://127.0.0.1:19999

echo.
echo 屏幕使用时间已启动！浏览器正在打开...
pause
