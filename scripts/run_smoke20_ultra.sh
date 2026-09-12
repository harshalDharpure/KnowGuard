#!/usr/bin/env bash
# Smoke20 KnowGuard on Nemotron Ultra (NIM) — freest GPU + nohup background.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
source "$ROOT/.venv/bin/activate"
export PYTHONUNBUFFERED=1
if [[ -f "$ROOT/.env" ]]; then set -a; source "$ROOT/.env"; set +a; fi
# Keep keys present-but-empty so helper._load_dotenv_if_present cannot re-inject them.
export OPENROUTER_API_KEY=
export OPENAI_API_KEY=
export GOOGLE_API_KEY=
export GEMINI_API_KEY=
export USE_API=nvidia
export KNOWGUARD_NIM_MIN_INTERVAL="${KNOWGUARD_NIM_MIN_INTERVAL:-2.5}"

PY="$ROOT/.venv/bin/python"
MODEL="nvidia/nemotron-3-ultra-550b-a55b"
DATA="ioMEDQA_smoke20.jsonl"
OUT="results/KnowGuardExpert_nemotron_ultra_smoke20.jsonl"
SLOG="logs/smoke20_ultra.log"
PIDFILE="logs/smoke20_ultra.pid"
mkdir -p logs results

if [[ -z "${NVIDIA_API_KEY:-}${NGC_API_KEY:-}" ]]; then
  echo "[$(date)] ERROR: NVIDIA_API_KEY/NGC_API_KEY missing" | tee -a "$SLOG"
  exit 1
fi

if [[ ! -f "data/interactive/$DATA" ]]; then
  echo "[$(date)] ERROR: missing data/interactive/$DATA" | tee -a "$SLOG"
  exit 1
fi

pick_gpu() {
  nvidia-smi --query-gpu=index,memory.free --format=csv,noheader,nounits \
    | sort -t',' -k2 -nr | head -n 1 | cut -d',' -f1 | tr -d ' '
}

GPU=$(pick_gpu)
FREE_MB=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits -i "$GPU" | tr -d ' ')

COMMON=(
  --expert_class KnowGuardExpert
  --question_type open-ended
  --patient_class FactSelectPatient
  --data_dir data/interactive
  --dev_filename "$DATA"
  --output_filename "$OUT"
  --log_filename "$SLOG"
  --expert_model "$MODEL"
  --patient_model "$MODEL"
  --judge_model "$MODEL"
  --max_questions 12
  --max_tokens 512
  --self_consistency 1
  --min_questions 3
  --kg_threshold 4.0
  --abstain_threshold 4.0
  --rationale_generation
  --know_mode text_only
  --max_queue_size 10
  --initial_triplets 4
  --max_hop_depth 2
  --beam_size 3
  --use_question_query
  --llm_relevance_threshold 0.1
  --kg_csv data/kg/combined_primekg_hetionet.csv
  --disease2demo_csv data/kg/baseline_dataset/Disease2demo.csv
  --faiss_dir data/kg/faiss_db_combined
  --embedding_model sentence-transformers/all-MiniLM-L6-v2
  --who_overview_json data/kg/WHO/overview.json
  --use_clinical_rag
  --clinical_corpus_dir data/kg/clinical_corpus
  --clinical_rag_top_k 5
  --clinical_rag_rerank
  --use_adjudicator
  --use_discriminative_questions
  --use_entropy_gate
  --entropy_commit_threshold 0.9
  --no_dual_process
  --no_council
  --phase_routing
  --use_api nvidia
)

echo "[$(date)] smoke20 Ultra start model=$MODEL gpu=$GPU free_mb=$FREE_MB out=$OUT" | tee -a "$SLOG"

# Fresh smoke run (resume is supported by Open_benchmark if file exists; remove for clean 20)
if [[ "${FRESH:-1}" == "1" ]]; then
  rm -f "$OUT"
fi

CUDA_VISIBLE_DEVICES="$GPU" nohup "$PY" Open_benchmark.py "${COMMON[@]}" >> "$SLOG" 2>&1 &
PID=$!
echo "$PID" > "$PIDFILE"
echo "[$(date)] launched pid=$PID gpu=$GPU pidfile=$PIDFILE" | tee -a "$SLOG"
echo "PID=$PID GPU=$GPU OUT=$OUT LOG=$SLOG"
