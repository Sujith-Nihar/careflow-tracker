#!/usr/bin/env bash
# End-to-end demonstration of the async evaluation path.
#
#   command -> queue -> worker -> persisted result
#   poisoned job -> retried -> dead-letter queue -> operator can find it
#
# Runs entirely locally against a moto SQS server. The same worker code and the same
# queue shape run in AWS; only the endpoint and who creates the queues differ.
set -uo pipefail
cd "$(dirname "$0")/.."

VENV=.venv/bin
ART=artifacts/worker
mkdir -p "$ART"

echo "== starting a local SQS =="
$VENV/python -m moto.server -p 5001 > "$ART/moto.log" 2>&1 &
MOTO_PID=$!
trap 'kill $MOTO_PID 2>/dev/null || true' EXIT
until curl -sf http://localhost:5001/ >/dev/null 2>&1; do sleep 0.5; done
export SQS_ENDPOINT_URL=http://localhost:5001
export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1
# Three receives then dead-letter, and a short visibility window so the demo does not
# spend two minutes waiting for a redelivery.
export EVAL_MAX_RECEIVES=3 EVAL_VISIBILITY_TIMEOUT=2 EVAL_WAIT_SECONDS=1
echo "   ready"

echo
echo "== 1. a job that should succeed =="
$VENV/python -m worker.enqueue --scenarios A_routine_scheduling,C_postop_transfer_fail_callback \
  | tee "$ART/enqueue_success.txt"

echo
echo "== 2. a poisoned job: a scenario that does not exist =="
$VENV/python -m worker.enqueue --scenarios Z_does_not_exist \
  | tee "$ART/enqueue_poison.txt"

echo
echo "== 3. worker drains the queue =="
# Four passes: the good job, then the poisoned one three times until it is dead-lettered.
$VENV/python -c "
import sys; sys.path.insert(0, '.')
from worker.main import main
main(max_messages=5)
" 2>&1 | tee "$ART/worker.log"

echo
echo "== 4. what ended up in the dead-letter queue =="
$VENV/python -m worker.dlq_inspect | tee "$ART/dlq.txt"

echo
echo "== 5. correlating a failure to its logs =="
JOB=$(grep -o 'job-[a-f0-9]*' "$ART/enqueue_poison.txt" | head -1)
echo "  poisoned job: $JOB"
grep "\"job_id\": \"$JOB\"" "$ART/worker.log" | tail -3 | tee "$ART/correlated.txt"

echo
echo "evidence written to $ART/"
