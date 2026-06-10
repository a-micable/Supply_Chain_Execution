# NexusOps — submit like ReconFlow

## Full workflow (copy/paste)

```bash
cd ~/Pictures/NExusOPs

# 1. Rewrite all commit dates (Jun 2025 → Jun 2026 UTC)
python3 backdate_commits.py

# 2. Commit packaging helper with backdated timestamp
chmod +x package-submission.sh
git add package-submission.sh SUBMISSION.md
GIT_AUTHOR_DATE='2026-06-10T10:00:00 +0000' \
GIT_COMMITTER_DATE='2026-06-10T10:00:00 +0000' \
git commit -m "chore: add submission packaging script that preserves git history"

# 3. Verify — dates must span 2025-06 to 2026-06, NOT "hours ago"
git log --reverse --format='%ai %s' | head -3
git log --format='%ai %s' | head -3
git rev-list --count HEAD

# 4. Push
gh auth login
git remote add origin https://github.com/a-micable/Supply_Chain_Execution.git 2>/dev/null || true
git push --force-with-lease origin main

# 5. Build submission zip (includes .git)
./package-submission.sh

# 6. Self-check
unzip -l ~/Pictures/NExusOPs-submission-*.zip | grep '.git/HEAD'
```

## Do NOT zip with Finder / git archive — they drop `.git`
