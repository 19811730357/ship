@echo off
echo ========================================
echo 航运智能账单助手 V2
echo ========================================
echo.

echo 激活conda环境...
call conda activate ship_env

echo.
echo 启动Streamlit应用...
echo 浏览器将自动打开 http://localhost:8501
echo.
echo 按 Ctrl+C 停止服务
echo.

streamlit run app.py

pause
