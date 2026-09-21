@echo off
REM 打包 GLM 用量悬浮窗为 Windows 可执行文件
REM 用法: build.bat [onefile^|onedir]   默认 onefile
REM   onefile - 单个 exe，便于拷贝（启动时多 1~3 秒解压，杀软误报率略高）
REM   onedir  - 目录形式，启动最快、误报率低（分发时把整个目录打 zip）
setlocal
cd /d "%~dp0"

set MODE=%1
if "%MODE%"=="" set MODE=onefile
if not "%MODE%"=="onefile" if not "%MODE%"=="onedir" (
    echo 未知模式: %MODE% （可选 onefile / onedir）
    exit /b 1
)

python -m PyInstaller --clean --noconfirm --%MODE% --noconsole ^
    --distpath dist\%MODE% --workpath build --specpath . ^
    --name GLMUsageWidget widget.py
if errorlevel 1 (
    echo 打包失败
    exit /b 1
)

echo.
echo 打包完成:
if "%MODE%"=="onefile" (
    echo   dist\onefile\GLMUsageWidget.exe
) else (
    echo   dist\onedir\GLMUsageWidget\GLMUsageWidget.exe
)
echo 运行后 config.json / widget.log 生成在 exe 同目录（不会写进临时目录）。
endlocal
