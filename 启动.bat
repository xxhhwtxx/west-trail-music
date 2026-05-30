@echo off
chcp 65001 >nul
echo West Trail Music — 浏览器模式
echo.
echo 服务启动中，浏览器将自动打开...
start "" http://localhost:8899
"D:\WestTrailMusic\.venv\Scripts\python.exe" "D:\WestTrailMusic\server.py"
pause
