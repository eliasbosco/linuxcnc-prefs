#!/bin/bash
# ----------------------------------------------------------------------
# gpio_watch.sh - live view of every FREE INPUT GPIO on the Mesa 7i92 /
# F7192 clone, so you can trigger a switch / opto / relay by hand and see
# which port changes state.
#
# This is the read-only counterpart to pin_probe.sh:
#   pin_probe.sh   LinuxCNC CLOSED - DRIVES each pin so you can find it
#                  with a meter.
#   gpio_watch.sh  LinuxCNC RUNNING - WATCHES each pin so you can find it
#                  with a signal.
#
# Uses "watch -d", which highlights any character that changed since the
# last refresh - the pin you just triggered lights up on its own.
#
# Usage:
#   ./gpio_watch.sh                 watch all free INPUT pins (default)
#   ./gpio_watch.sh --all           include outputs and module-owned pins
#   ./gpio_watch.sh --only 22,29,18
#   ./gpio_watch.sh -n 0.5          refresh interval (default 0.2 s)
#   ./gpio_watch.sh --list          print the table once, then exit
#   ./gpio_watch.sh --standalone    LinuxCNC CLOSED: load the card ourselves
#
# A second table lists every ENCODER instance: its live input-a / input-b
# levels plus rawcounts and velocity. Watch rawcounts, not the GPIO bit -
# the THCAD free-runs near 100 kHz, so a bit sampled 5x/second says nothing,
# while a rawcounts value that refuses to climb proves no pulses arrive.
#
# NOTES
#  * Pins owned by a stepgen / encoder / pwmgen expose .in but NO .out.
#    They are readable but not usable as general inputs. The encoder ones
#    are shown anyway (that is the THCAD feed); stepgen / pwm pins need
#    --all. The OWNER column says which module took the pin.
#  * hostmot2 GPIOs default to input (is_output = FALSE), so a pin that
#    reads nothing is a WIRING problem, not a config problem.
#  * A floating FPGA input drifts; a pin sitting rock-steady TRUE has a
#    pull-up, and an opto/switch to ground will read ACTIVE LOW - use
#    .in_not when you net it to a signal.
# ----------------------------------------------------------------------
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
SELF="$HERE/$(basename "$0")"

INTERVAL=0.2
SHOW_ALL=""
ONLY=""
MODE=watch
STANDALONE=""
PASSTHRU=()

# Standalone mode loads the card itself. Keep this matching the machine's
# real config string in cnc_plasma_cutter.hal, so pin ownership (and hence
# which pins are free) is identical to production.
BOARD_IP=10.10.10.10
HM2_CONFIG="num_encoders=1 num_pwmgens=1 num_stepgens=5"

while [ $# -gt 0 ]; do
    case "$1" in
        --all)    SHOW_ALL=1;         PASSTHRU+=("$1") ;;
        --only)   ONLY="$2";          PASSTHRU+=("$1" "$2"); shift ;;
        -n)       INTERVAL="$2";      PASSTHRU+=("$1" "$2"); shift ;;
        --list)   MODE=list;          PASSTHRU+=("$1") ;;
        --standalone) STANDALONE=1 ;;
        --render) MODE=render ;;          # internal, called by watch
        -h|--help) sed -n '2,36p' "$SELF"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done

# ---------- GPIO index -> connector + DB25 pin ----------
# Per "mesaflash --device 7i92 --addr 10.10.10.10 --readhmid":
# GPIO 000-016 = P2, GPIO 017-033 = P1, both in DB25 order.
DB25_ORDER=(1 14 2 15 3 16 4 17 5 6 7 8 9 10 11 12 13)
phys_pin() {
    local idx=$((10#$1)) conn off
    if [ "$idx" -le 16 ]; then conn=P2; off=$idx; else conn=P1; off=$((idx - 17)); fi
    printf '%s-%02d' "$conn" "${DB25_ORDER[$off]}"
}

# ---------- silk legend, read off the board (F7192_V2.2) ----------
silk_hint() {
    case "$1" in
        014|015|016|017|018|019) printf '8-way "%s"' "${1#0}" ;;
        022|024|029)             printf '4-way "%s"' "${1#0}" ;;
        *)                       printf -- '-' ;;
    esac
}

# ---------- which module owns a pin ----------
# Module-owned pins expose .in but no .out, so they are easy to DETECT, but
# hostmot2 will not tell you WHICH module took them. This map is read off
# "mesaflash --device 7i92 --addr 10.10.10.10 --readhmid" for this card's
# firmware; re-check it if you ever reflash or change the config= string.
gpio_owner() {
    case "$1" in
        001)             printf 'pwm.0'  ;;
        004|006|008|010|012) printf 'step'   ;;
        005|007|009|011|013) printf 'dir'    ;;
        026)             printf 'enc.0B' ;;
        027)             printf 'enc.0A' ;;
        *)               printf 'in-use' ;;
    esac
}

# Encoder-owned pins are worth showing by default (that is the THCAD input);
# stepgen / pwm pins are noise unless you ask for --all.
is_encoder_pin() { case "$1" in 026|027) return 0 ;; *) return 1 ;; esac; }

# ---------- locate the board ----------
find_board() {
    halcmd -s show pin 2>/dev/null \
      | grep -oE '\bhm2_[A-Za-z0-9_]+\.[0-9]+' | sort -u | head -1
}

# "halcmd show comp" SUCCEEDS against a completely empty HAL, because halcmd
# registers itself as a User component - so it is useless as a "is LinuxCNC
# running?" test. Look for realtime components instead.
have_realtime() {
    halcmd -s show comp 2>/dev/null | awk '$2 == "RT" { found = 1 } END { exit !found }'
}

# ======================================================================
# RENDER - one refresh. Deliberately makes exactly ONE halcmd call:
# "halcmd getp" accepts a single pin only, so a getp-per-pin loop would
# fork ~100 processes/second at -n0.2 on a Pi. "show pin" returns every
# value plus its signal linkage in one shot.
# ======================================================================
if [ "$MODE" = render ]; then
    BOARD="${GW_BOARD:-$(find_board)}"
    TABLE="${GW_TABLE:?internal: no table}"

    # One call covers gpio AND encoder pins: "show pin <prefix>" matches on
    # prefix, so the whole board comes back in a single round trip.
    halcmd -s show pin "$BOARD" 2>/dev/null | awk -v table="$TABLE" -v board="$BOARD" '
        # halcmd -s columns: owner type dir value name [<==|==> signal]
        {
            name = $5
            if (index(name, board ".") != 1) next
            key = substr(name, length(board) + 2)   # e.g. gpio.029.in
            val[key] = $4
            if (NF >= 7 && ($6 == "<==" || $6 == "==>")) sig[key] = $7
        }
        function mark(v) { return (v == "TRUE") ? "[ HIGH ]" : "[  low ]" }
        END {
            printf "  %-9s %-7s %-10s %-7s %-8s %s\n", \
                   "GPIO", "PIN", "TERMINAL", "OWNER", "STATE", "SIGNAL"
            printf "  %-9s %-7s %-10s %-7s %-8s %s\n", \
                   "--------", "------", "---------", "------", "-------", "------"
            nenc = 0
            while ((getline line < table) > 0) {
                split(line, f, "\t")
                if (f[1] == "E") { enc[nenc++] = f[2]; continue }
                idx = f[2]; phys = f[3]; silk = f[4]; own = f[5]
                state = (own == "OUT") ? val["gpio." idx ".out"] \
                                       : val["gpio." idx ".in"]
                s = sig["gpio." idx ".in"]
                if (s == "") s = sig["gpio." idx ".in_not"]
                if (s == "") s = sig["gpio." idx ".out"]
                if (s == "") s = "-"
                printf "  gpio.%-4s %-7s %-10s %-7s %-8s %s\n", \
                       idx, phys, silk, own, mark(state), s
            }
            if (nenc == 0) exit
            printf "\n  %-9s %-9s %-9s %-14s %s\n", \
                   "ENCODER", "INPUT-A", "INPUT-B", "RAWCOUNTS", "VELOCITY (Hz)"
            printf "  %-9s %-9s %-9s %-14s %s\n", \
                   "--------", "--------", "--------", "-------------", "-------------"
            for (i = 0; i < nenc; i++) {
                e = enc[i]
                printf "  enc.%-5s %-9s %-9s %-14s %s\n", e, \
                       mark(val["encoder." e ".input-a"]), \
                       mark(val["encoder." e ".input-b"]), \
                       val["encoder." e ".rawcounts"], \
                       val["encoder." e ".velocity"]
            }
            print "\n  (rawcounts must CLIMB for a live THCAD - a frozen value"
            print "   means no pulses are reaching the counter at all)"
        }'
    exit 0
fi

# ======================================================================
# OUTER - sanity checks, build the static table, hand off to watch
# ======================================================================
if ! halcmd show comp >/dev/null 2>&1; then
    echo "ERROR: cannot talk to HAL at all (is the RTAPI/HAL library present?)." >&2
    exit 1
fi

# ---------- standalone: load the card ourselves, then re-enter ----------
if [ -n "$STANDALONE" ]; then
    if have_realtime; then
        echo "ERROR: realtime is already loaded - close LinuxCNC first," >&2
        echo "       or just run without --standalone." >&2
        exit 1
    fi
    if ! ping -c1 -W2 "$BOARD_IP" >/dev/null 2>&1; then
        echo "ERROR: no reply from $BOARD_IP - check the ethernet link." >&2
        exit 1
    fi
    HALFILE=$(mktemp /tmp/gpio_watch_XXXX.hal)
    trap 'rm -f "$HALFILE"; halrun -U >/dev/null 2>&1' EXIT
    cat > "$HALFILE" <<EOF
loadrt hostmot2
loadrt hm2_eth board_ip="$BOARD_IP" config="$HM2_CONFIG"
setp hm2_7i92.0.watchdog.timeout_ns 20000000
loadrt threads name1=servo-thread period1=1000000
addf hm2_7i92.0.read  servo-thread
addf hm2_7i92.0.write servo-thread
start
loadusr -w $SELF ${PASSTHRU[@]:-}
EOF
    halrun -f "$HALFILE"
    exit $?
fi

if ! have_realtime; then
    echo "ERROR: HAL is empty - LinuxCNC is NOT running." >&2
    echo "       To watch pins WITHOUT starting LinuxCNC, re-run with:" >&2
    echo "         $0 --standalone ${PASSTHRU[*]:-}" >&2
    echo "       This script is the opposite of pin_probe.sh: it reads the" >&2
    echo "       LIVE pin values, so LinuxCNC must be UP and the machine on." >&2
    echo "       Start it with:  linuxcnc $HERE/cnc_plasma_cutter.ini" >&2
    echo "       (to drive pins with LinuxCNC closed, use ./pin_probe.sh)" >&2
    exit 1
fi

BOARD="$(find_board)"
if [ -z "$BOARD" ]; then
    echo "ERROR: realtime is loaded but no hm2 board is present in HAL." >&2
    echo "       Check that hm2_eth loaded - the card may not be reachable" >&2
    echo "       at 10.10.10.10, which shows up as a HAL error at startup." >&2
    exit 1
fi

TABLE=$(mktemp /tmp/gpio_watch_XXXX)
trap 'rm -f "$TABLE"' EXIT

# Free pins are the ones that expose .out; module-owned pins expose only
# .in / .in_not. Strip any trailing "<== signal" before matching.
mapfile -t FREE < <(halcmd -s show pin "$BOARD.gpio" 2>/dev/null \
    | awk '{for (i = 1; i <= NF; i++) if ($i ~ /\.gpio\.[0-9]+\.out$/) {
                n = split($i, a, "."); print a[4] }}' | sort -u)

mapfile -t ALLIDX < <(halcmd -s show pin "$BOARD.gpio" 2>/dev/null \
    | awk '{for (i = 1; i <= NF; i++) if ($i ~ /\.gpio\.[0-9]+\.in$/) {
                n = split($i, a, "."); print a[4] }}' | sort -u)

is_free() { local p; for p in "${FREE[@]}"; do [ "$p" = "$1" ] && return 0; done; return 1; }

want() {
    [ -z "$ONLY" ] && return 0
    local w
    for w in ${ONLY//,/ }; do
        [ "$(printf '%03d' "$((10#$w))")" = "$1" ] && return 0
    done
    return 1
}

COUNT=0
for idx in "${ALLIDX[@]}"; do
    want "$idx" || continue
    if is_free "$idx"; then
        out=$(halcmd getp "$BOARD.gpio.$idx.is_output" 2>/dev/null)
        own=$([ "$out" = "TRUE" ] && echo OUT || echo IN)
    else
        own="$(gpio_owner "$idx")"         # stepgen / encoder / pwmgen
    fi
    # Default view: free INPUT pins, plus the encoder-owned pins (the THCAD
    # feed). Stepgen / pwm pins are output-only noise - --all to see them.
    if [ -z "$SHOW_ALL" ] && [ "$own" != "IN" ] && ! is_encoder_pin "$idx"; then
        continue
    fi
    printf 'P\t%s\t%s\t%s\t%s\n' \
           "$idx" "$(phys_pin "$idx")" "$(silk_hint "$idx")" "$own" >> "$TABLE"
    COUNT=$((COUNT + 1))
done

# ---------- encoder instances ----------
# .input-a / .input-b are the live logic levels of the encoder's own pins,
# and rawcounts is the only thing that shows a ~100 kHz THCAD is alive - a
# GPIO bit sampled at 5 Hz tells you nothing about a signal that fast.
mapfile -t ENCS < <(halcmd -s show pin "$BOARD.encoder" 2>/dev/null \
    | grep -oE "\.encoder\.[0-9]+\." | grep -oE '[0-9]+' | sort -u)

for e in "${ENCS[@]}"; do
    printf 'E\t%s\t-\t-\tenc\n' "$e" >> "$TABLE"
    COUNT=$((COUNT + 1))
done

if [ "$COUNT" -eq 0 ]; then
    echo "ERROR: no pins matched." >&2
    exit 1
fi

export GW_TABLE="$TABLE" GW_BOARD="$BOARD"

if [ "$MODE" = list ]; then
    "$SELF" --render
    exit 0
fi

echo "Watching $COUNT pin(s) on $BOARD at ${INTERVAL}s. Trigger your input now."
echo "Changed values are highlighted by 'watch -d'.  Ctrl-C to quit."
sleep 1
exec watch -d -t -n "$INTERVAL" "GW_TABLE='$TABLE' GW_BOARD='$BOARD' '$SELF' --render"
