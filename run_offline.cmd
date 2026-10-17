@echo off
setlocal
chcp 65001 >nul
if not defined APP_PYTHON set "APP_PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" set "APP_PYTHON=%USERPROFILE%\.aws-rekognition-venv\Scripts\python.exe"
if not exist "%APP_PYTHON%" (
    echo Create .venv and install requirements.txt first. See README.md.
    exit /b 1
)
pushd "%~dp0"
"%APP_PYTHON%" -X utf8 main.py detect --offline --stride 1 --max-api-calls 0
if errorlevel 1 goto failed
"%APP_PYTHON%" -X utf8 main.py render
if errorlevel 1 goto failed
echo Result: output\annotated_video.mp4
popd
exit /b 0
:failed
popd
exit /b 1
