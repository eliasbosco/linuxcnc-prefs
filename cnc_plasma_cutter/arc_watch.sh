#!/bin/bash
# ----------------------------------------------------------------------
# arc_watch.sh - timestamp every arc-ok / torch-on transition during a cut
#
# WHY: the QtPlasmaC machine log only stamps to the MINUTE, which is far
# too coarse to tell "the arc died 62 s into the cut" from "the arc died
# 95 s into the cut", and it cannot tell you whether the ARC actually went
# out or whether only the SIGNAL dropped. This logs both, to millisecond
# wall-clock, with the elapsed time since the torch fired.
#
# THE QUESTION IT ANSWERS: on a "valid arc lost", did plasmac:torch-on
# stay asserted while arc-ok dropped (-> the plasma dropped the arc, or
# the arc-ok wiring glitched) or did torch-on drop first (-> plasmac gave
# up for its own reasons)? And how many seconds into the cut, every time?
#
# Usage:
#   ./arc_watch.sh                 40 Hz, log to arc_watch_<stamp>.log
#   ./arc_watch.sh -n 0.05         slower sampling (20 Hz)
#   ./arc_watch.sh -o /tmp/x.log   explicit log file
#   ./arc_watch.sh -q              log file only, no terminal output
#
# Start it BEFORE you press Cycle Start, leave it running for several
# cuts, then Ctrl-C for a summary. LinuxCNC must be RUNNING.
#
# RESOLUTION LIMIT: this is a userspace poller, so it sees events at the
# sample interval (25 ms by default), not microseconds. That is fine for
# timing an arc loss and for measuring dropouts of tens of ms or more. If
# the traces show arc-ok never dropping at all, the event was shorter than
# a sample - then use halscope on plasmac:arc-ok-in with a falling-edge
# trigger, which captures at the servo rate.
#
# Companion to gpio_watch.sh (live pin table) and pin_probe.sh (drive
# pins with LinuxCNC closed).
# ----------------------------------------------------------------------
set -u

INTERVAL=0.025
OUT=""
QUIET=""

while [ $# -gt 0 ]; do
    case "$1" in
        -n) INTERVAL="$2"; shift ;;
        -o) OUT="$2";      shift ;;
        -q) QUIET=1 ;;
        -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# "halcmd show comp" succeeds against an empty HAL because halcmd registers
# itself as a User component, so test for REALTIME components instead.
if ! halcmd -s show comp 2>/dev/null | awk '$2 == "RT" { f = 1 } END { exit !f }'; then
    echo "ERROR: HAL has no realtime components - LinuxCNC is NOT running." >&2
    echo "       Start QtPlasmaC first, then re-run this script." >&2
    exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
[ -n "$OUT" ] || OUT="$HERE/arc_watch_$(date +%Y%m%d_%H%M%S).log"

# ---------- one fork per sample ----------
# "halcmd getp" takes a single pin, so a getp-per-signal loop would fork 7
# processes every 25 ms. "show sig" returns every signal in ONE call; awk
# picks out the ones we care about. Columns are: type value name [links].
read_sample() {
    halcmd -s show sig 2>/dev/null | awk '
        $3 == "plasmac:torch-on"        { t  = $2 }
        $3 == "plasmac:arc-ok-in"       { ri = $2 }
        $3 == "plasmac:arc-ok"          { ok = $2 }
        $3 == "plasmac:arc_ok_out"      { oo = $2 }
        $3 == "plasmac:arc-voltage-in"  { hz = $2 }
        $3 == "plasmac:arc_voltage_out" { v  = $2 }
        $3 == "plasmac:axis-position"   { z  = $2 }
        END {
            printf "%s %s %s %s %s %s %s\n",
                   (t  == "" ? "?" : t),  (ri == "" ? "?" : ri),
                   (ok == "" ? "?" : ok), (oo == "" ? "?" : oo),
                   (hz == "" ? "?" : hz), (v  == "" ? "?" : v),
                   (z  == "" ? "?" : z)
        }'
}

now_ms() { echo $(( $(date +%s%N) / 1000000 )); }
stamp()  { date '+%H:%M:%S.%3N'; }

emit() {
    if [ -n "$QUIET" ]; then echo "$*" >> "$OUT"
    else echo "$*" | tee -a "$OUT"
    fi
}

# ---------- state ----------
P_TORCH="" P_RAW="" P_OK="" P_OO=""
T0=0                # ms at torch-on rising edge
DROP_AT=0           # ms at arc-ok falling edge
N_LOSS=0
LOSS_TIMES=""       # space separated "seconds into cut" values

since_t0() {
    [ "$T0" -eq 0 ] && { echo "    --"; return; }
    awk -v a="$1" -v b="$T0" 'BEGIN { printf "%6.2f", (a - b) / 1000 }'
}

finish() {
    emit ""
    emit "===== SUMMARY ====="
    emit "arc-ok losses recorded: $N_LOSS"
    if [ -n "$LOSS_TIMES" ]; then
        emit "seconds into cut at each loss:$LOSS_TIMES"
        echo "$LOSS_TIMES" | awk '{
            mn = 1e9; mx = 0; s = 0
            for (i = 1; i <= NF; i++) { v = $i + 0; s += v
                if (v < mn) mn = v; if (v > mx) mx = v }
            printf "  min %.2fs   max %.2fs   mean %.2fs\n", mn, mx, s / NF
        }' | while read -r l; do emit "$l"; done
        emit ""
        emit "A TIGHT CLUSTER means something accumulating - air receiver"
        emit "draining or a thermal/duty-cycle limit. SCATTERED means an"
        emit "event-driven cause - crossing a kerf, plate edge, standoff."
    fi
    emit "log: $OUT"
    exit 0
}
trap finish INT TERM

# ---------- go ----------
{
  echo "# arc_watch.sh started $(date '+%F %T')  interval=${INTERVAL}s"
  echo "# columns: time  event  t+cut(s)  torch-on  arc-ok-in(raw)  arc-ok(debounced)  arc-volts  arc-Hz  Z"
} >> "$OUT"
[ -n "$QUIET" ] || {
  echo "Logging to $OUT  (Ctrl-C for summary)"
  printf '%-13s %-14s %8s  %-6s %-6s %-6s %8s %10s %8s\n' \
         TIME EVENT "t+cut" TORCH RAW DEBNC VOLTS HZ Z
}

while :; do
    read -r TORCH RAW OK OO HZ VOLT Z <<< "$(read_sample)"
    T=$(now_ms)

    EV=""
    if [ "$TORCH" != "$P_TORCH" ] && [ -n "$P_TORCH" ]; then
        if [ "$TORCH" = "TRUE" ]; then T0=$T; EV="TORCH-ON"
        else EV="torch-off"; fi
    fi
    if [ "$OK" != "$P_OK" ] && [ -n "$P_OK" ]; then
        if [ "$OK" = "TRUE" ]; then
            if [ "$DROP_AT" -ne 0 ]; then
                EV="ARC-OK-BACK after $(( T - DROP_AT ))ms"
            else EV="ARC-OK-SET"; fi
        else
            DROP_AT=$T; N_LOSS=$(( N_LOSS + 1 ))
            S=$(since_t0 "$T" | tr -d ' ')
            LOSS_TIMES="$LOSS_TIMES $S"
            EV="*** ARC-OK LOST ***"
        fi
    fi
    # a raw-only glitch that the debounce swallowed is worth seeing too
    if [ -z "$EV" ] && [ "$RAW" != "$P_RAW" ] && [ -n "$P_RAW" ]; then
        EV="raw-only-change"
    fi

    if [ -n "$EV" ]; then
        printf -v _ '' 2>/dev/null || true
        LINE=$(printf '%-13s %-14s %8s  %-6s %-6s %-6s %8s %10s %8s' \
               "$(stamp)" "$EV" "$(since_t0 "$T" | tr -d ' ')" \
               "$TORCH" "$RAW" "$OK" "$VOLT" "$HZ" "$Z")
        emit "$LINE"
    fi

    P_TORCH="$TORCH"; P_RAW="$RAW"; P_OK="$OK"; P_OO="$OO"
    sleep "$INTERVAL"
done
