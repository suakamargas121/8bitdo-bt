@echo off
chcp 65001 >nul
title 8BitDo Ultimate 2C Wireless: Latency & Polling Benchmark
cd /d "%~dp0"
echo ========================================================
echo  8BitDo Ultimate 2C Wireless: Latency Benchmark
echo ========================================================
echo.

where py >nul 2>nul
if %ERRORLEVEL% equ 0 (
    py -3.12 benchmark_latency.py
    if %ERRORLEVEL% neq 0 (
        py benchmark_latency.py
    )
) else (
    python benchmark_latency.py
)

echo.
pause
