#!/bin/bash
# Backtest edge resumable, tourne la nuit (basse charge). One-shot : s'arrête une fois
# les 15208 courses couvertes (marqueur DONE). Résultat agrégé dans bt_night_result.log.
cd /opt/blackturf || exit 0
LOG=/opt/blackturf/bt_night.log
RES=/opt/blackturf/bt_night_result.log
[ -f "$RES" ] && exit 0   # déjà fini
docker cp backend/scripts/backtest_edge_stream.py blackturf_worker:/app/scripts/backtest_edge_stream.py 2>>"$LOG"
TOTAL=15208
echo "=== run $(date) ===" >> "$LOG"
for i in $(seq 1 20); do
  docker compose -f docker-compose.prod.yml exec -T worker sh -c "cd /app && python scripts/backtest_edge_stream.py >> /tmp/bt_night_stream.log 2>&1"
  P=$(docker compose -f docker-compose.prod.yml exec -T worker sh -c "cat /tmp/bt_edge_progress.txt 2>/dev/null" | tr -d '[:space:]')
  echo "run $i progress=$P" >> "$LOG"
  if [ -n "$P" ] && [ "$P" -ge "$TOTAL" ]; then
    # agrège et fige le résultat
    docker compose -f docker-compose.prod.yml exec -T worker sh -c "tail -40 /tmp/bt_night_stream.log" > "$RES" 2>&1
    echo "DONE $(date)" >> "$LOG"
    break
  fi
done
