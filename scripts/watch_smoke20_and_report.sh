#!/usr/bin/env bash
# watch_smoke20_and_report — polls smoke20 JSONL then writes metrics/figures
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/.venv/bin/activate"
OUT=results/KnowGuardExpert_nemotron_ultra_smoke20.jsonl
LOG=logs/smoke20_ultra_watcher.log
PIDFILE=logs/smoke20_ultra.pid
echo "[$(date)] watcher start target=20" | tee -a "$LOG"
while true; do
  n=0
  [[ -f "$OUT" ]] && n=$(wc -l < "$OUT")
  alive=0
  if [[ -f "$PIDFILE" ]] && ps -p "$(cat "$PIDFILE")" >/dev/null 2>&1; then alive=1; fi
  echo "[$(date)] progress n=$n/20 alive=$alive" >> "$LOG"
  if [[ "$n" -ge 20 ]]; then
    echo "[$(date)] complete n=$n — computing metrics + figures" | tee -a "$LOG"
    python scripts/compute_metrics.py "$OUT" --output results/KnowGuardExpert_nemotron_ultra_smoke20_metrics.json >> "$LOG" 2>&1
    python scripts/report_smoke20_figures.py "$OUT" --outdir results/smoke20_figures >> "$LOG" 2>&1
    echo "[$(date)] report done" | tee -a "$LOG"
    exit 0
  fi
  if [[ "$alive" -eq 0 ]]; then
    echo "[$(date)] worker dead with n=$n — reporting partial if any" | tee -a "$LOG"
    if [[ "$n" -gt 0 ]]; then
      python scripts/compute_metrics.py "$OUT" --output results/KnowGuardExpert_nemotron_ultra_smoke20_metrics.json >> "$LOG" 2>&1 || true
      python scripts/report_smoke20_figures.py "$OUT" --outdir results/smoke20_figures >> "$LOG" 2>&1 || true
    fi
    exit 1
  fi
  sleep 60
done
