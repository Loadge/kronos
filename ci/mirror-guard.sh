#!/bin/sh
# Guard run before this repo is pushed to its PUBLIC mirror. It blocks the push (exit 1) when the
# history that WILL BE PUBLISHED holds a secret (gitleaks) or ANY string of $MIRROR_DENYLIST: in a
# diff, in a commit message, or in a file name. The list itself is a CI variable on purpose: a public
# repo must not contain the very strings it is trying not to publish.
#
# It checks what is pushed (the history reachable from $REFS, default HEAD), NOT every ref of the
# clone: GitLab keeps a refs/pipelines/<id> for every old pipeline, so a CI clone can hold history
# that was rewritten away and that the mirror never sends. Scanning --all there blocks forever.
#
#   MIRROR_DENYLIST='regex|of|private|strings' sh ci/mirror-guard.sh [REFS]      (from the repo root)
set -eu
: "${MIRROR_DENYLIST:?MIRROR_DENYLIST is not set - refusing to publish without a guard}"
REFS="${1:-HEAD}"
git config --global --add safe.directory "$(pwd)" 2>/dev/null || true

echo "1/2 gitleaks over the history reachable from $REFS..."
gitleaks git . --redact --no-banner --exit-code 7 --log-opts="$REFS"

echo "2/2 denylist over every commit reachable from $REFS (diffs, messages, file names)..."
diff_commits=$(git log "$REFS" --format='%h' -G"$MIRROR_DENYLIST" || true)
msg_commits=$(git log "$REFS" --format='%h %B%x00' | tr '\n' ' ' | tr '\0' '\n' | grep -E "$MIRROR_DENYLIST" | cut -d' ' -f1 || true)
file_hits=$(git log "$REFS" --name-only --format= | sort -u | grep -E "$MIRROR_DENYLIST" || true)

if [ -n "$diff_commits$msg_commits$file_hits" ]; then
  echo "BLOCKED: the history to be published contains denylisted strings (the strings are not printed)."
  [ -n "$diff_commits" ] && echo "  commits whose diff adds or removes one: $(echo "$diff_commits" | tr '\n' ' ')"
  [ -n "$msg_commits" ] && echo "  commits whose message has one: $(echo "$msg_commits" | tr '\n' ' ')"
  [ -n "$file_hits" ] && echo "  file names with one: $(echo "$file_hits" | wc -l) file(s)"
  exit 1
fi
echo "guard passed: no secrets and no denylisted strings in $(git rev-list "$REFS" --count) commits ($REFS)"
