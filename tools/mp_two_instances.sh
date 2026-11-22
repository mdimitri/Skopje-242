#!/bin/bash
# Two real game windows playing multiplayer over loopback, each saves its screenshot, then both quit (developer test; logs/game_a.log, game_b.log).
# usage: tools/mp_two_instances.sh [world_dir] [seconds]     needs a display (xvfb-run -a -s "-screen 0 1400x600x24" on a headless box)
cd "$(dirname "$0")/.."
W=${1:-data/cache/world}; T=${2:-12}; OUT=${OUT:-/tmp/mp_two}; mkdir -p "$OUT" logs
C="--world $W --mute --size 640x480 --nomenu"
python3 src/main.py $C --mp-host --mp-players 2 --hero 3 --name Ana --color 0 --window-pos 0,0 --screenshot-after $((T-2)):$OUT/a.png --quit-after $T --log-suffix a > "$OUT/a.out" 2>&1 &
sleep 4
python3 src/main.py $C --mp-join 127.0.0.1 --hero 8 --name Kiko --color 1 --window-pos 660,0 --screenshot-after $((T-2)):$OUT/b.png --quit-after $T --log-suffix b > "$OUT/b.out" 2>&1 &
wait
grep -h "mp-dev\|faces\]" logs/game_a.log logs/game_b.log
