#!/usr/bin/env bash
# Drives Codex non-interactive review of the forensic_triage Path A build.
cd "/mnt/c/Users/jroyp/Dropbox/Claude Folder/forensic_triage" || exit 1
CODEX="$HOME/.codexnpm/bin/codex"
[ -x "$CODEX" ] || CODEX="$(command -v codex || echo codex)"
P="$(cat codex_feedback/_patha_review_prompt.txt)"
OUT="codex_feedback/codex_forensic_patha_2026-06-24.md"
"$CODEX" exec review "$P" 2>&1 \
  | grep -vE 'rmcp::transport|mcp: robinhood|mcp startup' \
  > "$OUT"
echo "___CODEX_EXIT=${PIPESTATUS[0]}" >> "$OUT"
