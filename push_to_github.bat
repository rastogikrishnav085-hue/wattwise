@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   WattWise - Verify, commit, push to GitHub
echo ============================================
echo.

where git >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Git is not installed.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv is missing. Run start_wattwise.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

echo [TEST] Running full test suite...
python -m pytest tests\ -q
if !errorlevel! neq 0 (
    echo [ERROR] Tests failed. NOT pushing.
    pause
    exit /b 1
)

echo [CHECK] Compiling Python files...
python -m compileall -q app.py api.py predict.py scripts src
if !errorlevel! neq 0 (
    echo [ERROR] Compilation failed. NOT pushing.
    pause
    exit /b 1
)

echo [CHECK] Looking for accidental secret files...
if exist ".env" (
    echo [ERROR] .env exists locally, which is fine, but it must remain untracked.
)
git status --short

git check-ignore .env >nul 2>nul
if !errorlevel! neq 0 (
    echo [WARNING] .env is NOT ignored. Fix .gitignore before pushing.
    pause
    exit /b 1
)

if not exist ".git" (
    set /p REPO_URL="Paste your GitHub repository URL: "
    if "!REPO_URL!"=="" (
        echo [ERROR] Repository URL is required.
        pause
        exit /b 1
    )
    git init
    git branch -M main
    git remote add origin "!REPO_URL!"
) else (
    git remote get-url origin >nul 2>nul
    if !errorlevel! neq 0 (
        set /p REPO_URL="No origin configured. Paste your GitHub repository URL: "
        if "!REPO_URL!"=="" exit /b 1
        git remote add origin "!REPO_URL!"
    )
)

for /f "delims=" %%e in ('git config user.email') do set "GITEMAIL=%%e"
for /f "delims=" %%n in ('git config user.name') do set "GITNAME=%%n"
if "!GITEMAIL!"=="" (
    set /p GIT_NAME="Git name: "
    set /p GIT_EMAIL="Git email: "
    git config user.name "!GIT_NAME!"
    git config user.email "!GIT_EMAIL!"
)

echo [SYNC] Fetching GitHub main branch if it exists...
git fetch origin main >nul 2>nul
if !errorlevel! equ 0 (
    git rev-parse --verify origin/main >nul 2>nul
    if !errorlevel! equ 0 (
        git merge-base --is-ancestor origin/main HEAD >nul 2>nul
        if !errorlevel! neq 0 (
            echo [SYNC] Merging remote main into local main...
            git pull --rebase --allow-unrelated-histories origin main
            if !errorlevel! neq 0 (
                echo [ERROR] Remote sync failed. Resolve the Git conflict, then rerun.
                pause
                exit /b 1
            )
        )
    )
)

set "MSG=%~1"
if "!MSG!"=="" set "MSG=Update WattWise release"

git add -A
git diff --cached --quiet
if !errorlevel! neq 0 (
    git commit -m "!MSG!"
    if !errorlevel! neq 0 exit /b 1
) else (
    echo [INFO] No new changes to commit.
)

echo [PUSH] Pushing main to GitHub...
git push -u origin main
if !errorlevel! neq 0 (
    echo [ERROR] Git push failed. No claim of a successful GitHub push is being made.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   GitHub push completed successfully.
echo ============================================
git status --short --branch
pause
