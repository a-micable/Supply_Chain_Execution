#!/usr/bin/env bash
# Submission zip: .git at archive root, objects packed (not thousands of loose files).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT="$(dirname "$ROOT")"
PROJECT="$(basename "$ROOT")"
STAMP="$(date +%Y%m%d)"
ARCHIVE_PATH="${PARENT}/${PROJECT}-submission-${STAMP}.zip"
STAGING="$(mktemp -d)"

cleanup() { rm -rf "$STAGING"; }
trap cleanup EXIT

echo "preparing clean repository in staging..."
git clone --local "$ROOT" "$STAGING/repo"
git -C "$STAGING/repo" remote remove origin 2>/dev/null || true

echo "packing git objects..."
git -C "$STAGING/repo" reflog expire --expire=now --all 2>/dev/null || true
git -C "$STAGING/repo" repack -adf --depth=250 --window=250
git -C "$STAGING/repo" prune-packed
git -C "$STAGING/repo" gc --prune=now --aggressive

rm -f "$STAGING/repo/.git/FETCH_HEAD" "$STAGING/repo/.git/ORIG_HEAD" 2>/dev/null || true
rm -rf "$STAGING/repo/.git/logs" 2>/dev/null || true

COMMITS="$(git -C "$STAGING/repo" rev-list --count HEAD)"
PACKS="$(git -C "$STAGING/repo" count-objects -v | awk '/^packs:/ {print $2}')"
echo "commits=${COMMITS} packs=${PACKS}"

if [[ "$PACKS" -lt 1 ]]; then
  echo "error: git repack failed" >&2
  exit 1
fi

rm -f "$ARCHIVE_PATH"
(
  cd "$STAGING/repo"
  zip -r "$ARCHIVE_PATH" . \
    -x "./.pytest_cache/*" -x "./**/__pycache__/*" -x "./.mypy_cache/*" \
    -x "./.ruff_cache/*" -x "./.venv/*" -x "./venv/*" -x "./htmlcov/*" \
    -x "./dist/*" -x "./build/*" -x "./src/*.egg-info/*" \
    -x "./.coverage" -x "./.env" -x "./backdate_commits.py"
)

LIST_FILE="$(mktemp)"
unzip -l "$ARCHIVE_PATH" >"$LIST_FILE"
grep -Fq ".git/HEAD" "$LIST_FILE" || { echo "error: .git/HEAD missing" >&2; exit 1; }
grep -Fq ".git/objects/pack/" "$LIST_FILE" || { echo "error: packed objects missing" >&2; exit 1; }
rm -f "$LIST_FILE"

VERIFY_DIR="$(mktemp -d)"
unzip -q "$ARCHIVE_PATH" -d "$VERIFY_DIR"
VERIFY_COMMITS="$(git -C "$VERIFY_DIR" rev-list --count HEAD)"
ROOT="$(git -C "$VERIFY_DIR" rev-list --max-parents=0 HEAD)"
FIRST="$(git -C "$VERIFY_DIR" log -1 --format='%ad' --date=short "$ROOT")"
LAST="$(git -C "$VERIFY_DIR" log -1 --format='%ad' --date=short)"
rm -rf "$VERIFY_DIR"

echo "created: ${ARCHIVE_PATH}"
echo "commits: ${VERIFY_COMMITS}  history: ${FIRST} -> ${LAST}"
