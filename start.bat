@echo off
cd /d "%~dp0"
if /I not "%~d0"=="D:" (
    echo This project must be started from drive D.
    exit /b 1
)
set PYTHONDONTWRITEBYTECODE=1
set PYTHONUTF8=1
set STREAMLIT_BROWSER_GATHER_USAGE_STATS=false
echo ========================================
echo 航运智能账单助手 V2
echo ========================================
echo.

echo 激活conda环境...
call conda activate ship_env
if errorlevel 1 exit /b 1

echo.
echo 启动Streamlit应用...
echo 浏览器将自动打开 http://localhost:8501
echo.
echo 按 Ctrl+C 停止服务
echo.

python -B -c "import sys; sys.path.insert(0, 'src'); from billing_agent.runtime import launch_streamlit; raise SystemExit(launch_streamlit())"

pause
