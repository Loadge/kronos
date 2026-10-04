#!/bin/sh
# Guard run before this repo is pushed to its PUBLIC mirror. It blocks the push (exit 1) when the
# history holds a secret (gitleaks) or ANY string of $MIRROR_DENYLIST: in a diff, in a commit
# message, or in a file name. The list itself is a CI variable on purpose: a public repo must not
# contain the very strings it is trying not to publish.
#
#   MIRROR_DENYLIST='regex|of|private|strings' sh ci/mirror-guard.sh      (from the repo root)
set -eu
: "${MIRROR_DENYLIST:?MIRROR_DENYLIST is not set - refusing to publish without a guard}"
git config --global --add safe.directory "$(pwd)" 2>/dev/null || true

echo "1/2 gitleaks over the full history..."
gitleaks git . --redact --no-banner --exit-code 7

echo "2/2 denylist over every commit (diffs, messages, file names)..."
diff_commits=$(git log --all --format='%h' -G"$MIRROR_DENYLIST" || true)
msg_commits=$(git log --all --format='%h %B%x00' | tr '\n' ' ' | tr '\0' '\n' | grep -E "$MIRROR_DENYLIST" | cut -d' ' -f1 || true)
file_hits=$(git log --all --name-only --format= | sort -u | grep -E "$MIRROR_DENYLIST" || true)

if [ -n "$diff_commits$msg_commits$file_hits" ]; then
  echo "BLOCKED: the history contains denylisted strings (the strings are not printed)."
  [ -n "$diff_commits" ] && echo "  commits whose diff adds or removes one: $(echo "$diff_commits" | tr '\n' ' ')"
  [ -n "$msg_commits" ] && echo "  commits whose message has one: $(echo "$msg_commits" | tr '\n' ' ')"
  [ -n "$file_hits" ] && echo "  file names with one: $(echo "$file_hits" | wc -l) file(s)"
  exit 1
fi
echo "guard passed: no secrets and no denylisted strings in $(git rev-list --all --count) commits"
