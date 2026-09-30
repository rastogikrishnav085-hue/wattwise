#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  WattWise - Test, then push to GitHub"
echo "============================================"
echo ""

# --- 1. Make sure the venv exists ---
if [ ! -d ".venv" ]; then
    echo "[ERROR] No .venv found. Run start_wattwise.sh at least once first"
    echo "        (it sets up the virtual environment and installs everything)."
    exit 1
fi

source .venv/bin/activate

# --- 2. Run the full automated test suite — this is the actual gate ---
echo "[TEST] Running full test suite..."
if ! python -m pytest tests/ -q; then
    echo ""
    echo "============================================"
    echo "  TESTS FAILED — NOT pushing to GitHub."
    echo "  Fix whatever's shown above, then run this script again."
    echo "============================================"
    exit 1
fi
echo "[OK] All tests passed."
echo ""

# --- 3. Syntax-check every entrypoint too, in case something isn't covered by a test ---
echo "[CHECK] Compiling every Python file (catches syntax errors, bad imports)..."
if ! python -m compileall -q app.py api.py predict.py scripts src; then
    echo "[ERROR] A file failed to compile — see above. NOT pushing."
    exit 1
fi
echo "[OK] Everything compiles cleanly."
echo ""

# --- 4. First-time git setup, only if this folder isn't a repo yet ---
if [ ! -d ".git" ]; then
    echo "[SETUP] No git repository here yet."
    echo "        Create an empty repository on github.com first (don't add a"
    echo "        README/license there — this folder already has files)."
    read -rp "Paste its URL (e.g. https://github.com/you/wattwise.git): " REPO_URL
    git init -q
    git branch -M main
    git remote add origin "$REPO_URL"
    echo "[OK] Git initialized, remote set to $REPO_URL"
    # A repo created on GitHub with a LICENSE already has one commit; bring it in first,
    # otherwise the push below is rejected as "unrelated histories".
    git pull origin main --allow-unrelated-histories --no-edit || echo "[INFO] Nothing to merge from the remote yet - continuing."
    echo ""
fi

# git needs to know who's committing — a fresh machine usually doesn't have this set
if [ -z "$(git config user.email)" ] || [ -z "$(git config user.name)" ]; then
    echo "[SETUP] Git doesn't know your name/email yet (needed once per machine)."
    read -rp "Your name: " GIT_NAME
    read -rp "Your email (can be any email, doesn't need to be verified): " GIT_EMAIL
    git config user.name "$GIT_NAME"
    git config user.email "$GIT_EMAIL"
    echo "[OK] Set for this repository."
    echo ""
fi

# --- 5. Commit whatever changed, then push ---
COMMIT_MSG="${1:-Update $(date -u +'%Y-%m-%d %H:%M UTC')}"
git add -A

if git diff --cached --quiet; then
    echo "[INFO] Nothing changed since the last push."
else
    git commit -q -m "$COMMIT_MSG"
    echo "[OK] Committed: $COMMIT_MSG"
fi

echo "[PUSH] Pushing to GitHub..."
git push -u origin main

echo ""
echo "============================================"
echo "  Done. Your repo is up to date on GitHub."
echo "============================================"
