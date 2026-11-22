#!/usr/bin/env bash
# Step 09. Anonymized code export for reviewers: ../submission/exception-authority-anonymous.zip.
# The zip holds exception-authority/ (without .env, .venv or caches) plus PREREG.md and DESIGN.md at the top,
# so the frozen protocol's ../PREREG.md still resolves. It refuses to write the zip if an author name,
# a local path or a key file would be included.
# Usage: scripts/09_export_anonymous.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STUDY="$(dirname "$ROOT")"
OUT="$STUDY/submission/exception-authority-anonymous.zip"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/export" "$STUDY/submission"
rsync -a --exclude '.env' --exclude '.env.*' --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
      --exclude '.DS_Store' --exclude '*.egg-info/' "$ROOT/" "$STAGE/export/exception-authority/"
cp "$STUDY/PREREG.md" "$STUDY/DESIGN.md" "$STAGE/export/"

# Record the SHA-256 of every original (unscrubbed) results file, outside the zip, so the camera-ready
# release can restore the request ids and show that nothing else changed. results/ itself is never modified.
SUMS="$STUDY/submission/unscrubbed-results.sha256"
{ echo "# SHA-256 of every original results file (request ids included), $(date -u +%Y-%m-%dT%H:%M:%SZ) UTC. Not in the anonymous zip."
  (cd "$ROOT" && find results -type f ! -name ".DS_Store" | LC_ALL=C sort | while IFS= read -r f; do shasum -a 256 "$f"; done); } > "$SUMS"
echo "wrote $SUMS ($(grep -vc '^#' "$SUMS") files)"

# Drop provider request, generation and account ids from the staged results; fail if any remain.
"${PYTHON:-$ROOT/.venv/bin/python}" -I "$ROOT/scripts/scrub_export.py" "$STAGE/export" || exit 1

# Refuse on secrets or identifying strings.
if find "$STAGE/export" -name '.env*' | grep -q .; then echo "FAIL: a .env file would be exported"; exit 1; fi
# The identifying patterns (names, other titles, local paths, key prefixes) live in ../leak-patterns.txt,
# one extended regex per line, outside the export, so this script does not carry them to reviewers.
PATTERNS="$STUDY/leak-patterns.txt"
[[ -s "$PATTERNS" ]] || { echo "FAIL: $PATTERNS is missing or empty"; exit 1; }
if grep -rIl -E -i -f "$PATTERNS" "$STAGE/export"; then
  echo "FAIL: the files above contain an author name, another title, a local path or a key; fix them before exporting"; exit 1
fi
# Absolute paths recorded in result rows or the ledger would also identify the machine.
ABS="$(printf '%s|%s' '/ho''me/' 'C:\\\\Us''ers')"
if grep -rIl -E "$ABS" "$STAGE/export"; then echo "FAIL: absolute paths in the files above"; exit 1; fi

rm -f "$OUT"
(cd "$STAGE/export" && zip -q -r -X "$OUT" .)  # -X: no owner IDs or extra attributes
echo "wrote $OUT ($(du -h "$OUT" | cut -f1)); upload it to an anonymous host and put the link in the paper"
