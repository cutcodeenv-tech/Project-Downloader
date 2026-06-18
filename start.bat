@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"

if defined PYTHON_BIN (
    set "PYTHON_EXE=%PYTHON_BIN%"
    set "PYTHON_ARGS="
    call :check_python
    if errorlevel 1 exit /b %ERRORLEVEL%
) else (
    call :find_python
    if "%PYTHON_EXE%"=="" (
        call :install_python
        call :find_python
    )
)

if "%PYTHON_EXE%"=="" (
    echo Rabochiy Python ne nayden. Ustanovite Python 3.11/3.12 ili zadaite PYTHON_BIN.
    exit /b 1
)

call :ensure_venv
if errorlevel 1 exit /b %ERRORLEVEL%
call :ensure_requirements
if errorlevel 1 exit /b %ERRORLEVEL%

set "BASE_DIR=%ROOT_DIR%"
if defined PYTHONPATH (
    set "PYTHONPATH=%ROOT_DIR%\scripts;%PYTHONPATH%"
) else (
    set "PYTHONPATH=%ROOT_DIR%\scripts"
)

cd /d "%ROOT_DIR%"
if /I "%~1"=="web" (
    call "%PYTHON_EXE%" %PYTHON_ARGS% "%ROOT_DIR%\web\app.py"
) else (
    call "%PYTHON_EXE%" %PYTHON_ARGS% "%ROOT_DIR%\core\main.py"
)
exit /b %ERRORLEVEL%

:find_python
set "PYTHON_EXE="
set "PYTHON_ARGS="
call :try_python py -3.11
if "%PYTHON_EXE%"=="" call :try_python py -3.12
if "%PYTHON_EXE%"=="" call :try_python py -3.10
if "%PYTHON_EXE%"=="" call :try_python py -3.13
if "%PYTHON_EXE%"=="" call :try_python python
exit /b 0

:install_python
echo Rabochiy Python ne nayden. Probuyu ustanovit Python 3.11...
where winget >nul 2>nul
if errorlevel 1 (
    echo winget ne nayden. Ustanovite Python 3.11/3.12 vruchnuyu ili zadaite PYTHON_BIN.
    exit /b 1
)
winget install --id Python.Python.3.11 -e --accept-package-agreements --accept-source-agreements
exit /b %ERRORLEVEL%

:ensure_venv
set "VENV_PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"
if exist "%VENV_PYTHON%" (
    call "%VENV_PYTHON%" -c "import pyexpat, pip" >nul 2>nul
    if not errorlevel 1 (
        set "PYTHON_EXE=%VENV_PYTHON%"
        set "PYTHON_ARGS="
        exit /b 0
    )
)
echo Sozdayu lokalnoe okruzhenie Python: %ROOT_DIR%\.venv
if exist "%ROOT_DIR%\.venv" rmdir /s /q "%ROOT_DIR%\.venv"
call "%PYTHON_EXE%" %PYTHON_ARGS% -m venv "%ROOT_DIR%\.venv"
if errorlevel 1 exit /b %ERRORLEVEL%
set "PYTHON_EXE=%VENV_PYTHON%"
set "PYTHON_ARGS="
call :check_python
exit /b %ERRORLEVEL%

:ensure_requirements
if not exist "%ROOT_DIR%\requirements.txt" (
    echo Fayl zavisimostey ne nayden: %ROOT_DIR%\requirements.txt
    exit /b 1
)
set "REQ_HASH_FILE=%ROOT_DIR%\.venv\.requirements.sha256"
for /f "usebackq delims=" %%I in (`call "%PYTHON_EXE%" %PYTHON_ARGS% -c "from pathlib import Path; import hashlib; print(hashlib.sha256(Path(r'%ROOT_DIR%\requirements.txt').read_bytes()).hexdigest())"`) do set "CURRENT_REQ_HASH=%%I"
set "INSTALLED_REQ_HASH="
if exist "%REQ_HASH_FILE%" set /p INSTALLED_REQ_HASH=<"%REQ_HASH_FILE%"
if /I "%CURRENT_REQ_HASH%"=="%INSTALLED_REQ_HASH%" exit /b 0
echo Ustanavlivayu zavisimosti iz requirements.txt...
call "%PYTHON_EXE%" %PYTHON_ARGS% -m pip install --disable-pip-version-check -r "%ROOT_DIR%\requirements.txt"
if errorlevel 1 exit /b %ERRORLEVEL%
>%REQ_HASH_FILE% echo %CURRENT_REQ_HASH%
exit /b %ERRORLEVEL%

:try_python
where %1 >nul 2>nul
if errorlevel 1 exit /b 0
set "PYTHON_EXE=%1"
set "PYTHON_ARGS=%~2"
call :check_python
if errorlevel 1 (
    set "PYTHON_EXE="
    set "PYTHON_ARGS="
)
exit /b 0

:check_python
call "%PYTHON_EXE%" %PYTHON_ARGS% -c "import sys, pyexpat, pip; raise SystemExit(0 if (3, 10) <= sys.version_info[:2] <= (3, 12) else 1)" >nul 2>nul
exit /b %ERRORLEVEL%
