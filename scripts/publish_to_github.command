#!/bin/zsh
set -euo pipefail

REPO="${1:-liamczelusta/Updated-Stock-Research}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PUBLISH_ROOT="$PROJECT_DIR/.github-publish"
REPO_DIR="$PUBLISH_ROOT/${REPO:t}"

echo "Publishing Stock Research Dashboard to $REPO"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI is not installed. Install it first, then run this again."
  echo "Recommended: brew install gh"
  exit 1
fi

if ! command -v git >/dev/null 2>&1; then
  echo "Git is not installed. Run xcode-select --install, then run this again."
  exit 1
fi

gh auth status >/dev/null

mkdir -p "$PUBLISH_ROOT"
if [ ! -d "$REPO_DIR/.git" ]; then
  gh repo clone "$REPO" "$REPO_DIR"
else
  git -C "$REPO_DIR" pull --ff-only
fi

rsync -a --delete \
  --exclude ".git" \
  --exclude ".venv" \
  --exclude ".cache" \
  --exclude ".pytest_cache" \
  --exclude ".pyinstaller-cache" \
  --exclude "__pycache__" \
  --exclude "*.pyc" \
  --exclude "build" \
  --exclude "dist" \
  --exclude "release" \
  --exclude ".streamlit/secrets.toml" \
  --exclude "*.xlsx" \
  --exclude "*.xlsm" \
  "$PROJECT_DIR/app.py" \
  "$PROJECT_DIR/desktop_launcher.py" \
  "$PROJECT_DIR/Open Stock Research Dashboard.bat" \
  "$PROJECT_DIR/Stop Stock Research Dashboard.bat" \
  "$PROJECT_DIR/StockResearchDashboard.spec" \
  "$PROJECT_DIR/requirements.txt" \
  "$PROJECT_DIR/runtime.txt" \
  "$PROJECT_DIR/README.md" \
  "$PROJECT_DIR/pyproject.toml" \
  "$PROJECT_DIR/.gitignore" \
  "$PROJECT_DIR/src" \
  "$PROJECT_DIR/scripts" \
  "$PROJECT_DIR/docs" \
  "$PROJECT_DIR/tests" \
  "$PROJECT_DIR/.streamlit" \
  "$PROJECT_DIR/.github" \
  "$REPO_DIR/"

git -C "$REPO_DIR" add -A
if git -C "$REPO_DIR" diff --cached --quiet; then
  echo "No changes to publish."
else
  git -C "$REPO_DIR" commit -m "Add Windows desktop build and folder scanner"
  git -C "$REPO_DIR" push
fi

echo "Done. Check GitHub Actions for the Windows build."
