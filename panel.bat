@echo off
chcp 65001 >nul
cd /d "C:\Users\33834\ScreenTimeTracker"

echo 正在打开屏幕使用时间面板...
start "" pythonw.exe server.py
timeout /t 2 /nobreak >nul
start http://127.0.0.1:19999

echo 面板已启动，浏览器即将打开...
