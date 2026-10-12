#!/usr/bin/env bash
# Regenerates the committed examples/ snapshot (run_log.txt, outbox.jsonl,
# report.md, report.html, hunter.db) from the exact command sequence in the
# README quickstart - the only sanctioned way to update examples/. A plain
# `python -m hunter run` never touches examples/: config.yaml's runtime
# paths point at the git-ignored out/ directory by default.
#
# Usage: scripts/regenerate_examples.sh   (run from the repo root)
set -euo pipefail

cd "$(dirname "$0")/.."

LOG="$(mktemp)"
trap 'rm -f "$LOG"' EXIT

run() {
  printf '$' >> "$LOG"
  for arg in "$@"; do printf ' %q' "$arg" >> "$LOG"; done
  printf '\n' >> "$LOG"
  "$@" >> "$LOG" 2>&1
}

run python -m hunter reset
run python -m hunter run
run python -m hunter review
run python -m hunter edit 5 --text "Hi Dana, congrats on the move to Brightwave AI - I came across your previous work on fraud-scoring infrastructure and would be glad to connect."
run python -m hunter approve --all
run python -m hunter simulate --days 7
run python -m hunter review
run python -m hunter approve --all
run python -m hunter approve 6
run python -m hunter approve 9
run python -m hunter approve 10
run python -m hunter report --html

cp "$LOG" examples/run_log.txt
cp out/outbox.jsonl examples/outbox.jsonl
cp out/report.md examples/report.md
cp out/report.html examples/report.html
cp hunter.db examples/hunter.db

echo "examples/ regenerated. Diff it before committing - it should differ from the previous"
echo "commit only in timestamps and message ids, unless a prompt or scoring change was intended."
