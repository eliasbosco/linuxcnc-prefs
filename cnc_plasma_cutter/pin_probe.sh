#!/bin/bash
# ----------------------------------------------------------------------
# pin_probe.sh - walk every FREE GPIO on the Mesa 7i92 / F7192 clone,
# driving each one HIGH so it can be found with a multimeter.
#
# LinuxCNC must be CLOSED. The script first asks the card itself, with
#   mesaflash --readhmid
# for the GPIO -> connector/DB25-pin map, then loads hm2_eth with the
# machine's config= string so the pins owned by the 5 stepgens and the
# encoder are not GPIO at all and can never be toggled here. Only pins
# that expose a .out pin are walked.
#
# The pwmgen is NOT loaded (num_pwmgens=0), so its pin is handed back to
# GPIO and gets walked too - a plasma has no use for it.
#
# Probe between the terminal under test and any G / GND terminal.
# A driven pin reads ~3.3 V high, ~0 V low. These are bare FPGA pins:
# probe only, do not load them.
#
# Usage:
#   ./pin_probe.sh              walk all free pins, prompting at each
#   ./pin_probe.sh --list       just print the map, then exit
#   ./pin_probe.sh --only 22,24,29,18
#   ./pin_probe.sh --auto 2     no prompts, 2 s per pin (unattended)
#
# Notes you type are appended to pin_probe_notes.txt next to this script.
# ----------------------------------------------------------------------
set -u

BOARD=hm2_7i92.0
BOARD_IP=10.10.10.10
DEVICE=7i92
# num_encoders=1 is kept so the THCAD arc-voltage pins stay protected.
HM2_CONFIG="num_encoders=1 num_pwmgens=0 num_stepgens=5"

HERE="$(cd "$(dirname "$0")" && pwd)"
SELF="$HERE/$(basename "$0")"
NOTES="$HERE/pin_probe_notes.txt"

MODE=walk
ONLY=""
AUTO=""
while [ $# -gt 0 ]; do
    case "$1" in
        --list)   MODE=list ;;
        --only)   ONLY="$2"; shift ;;
        --auto)   AUTO="$2"; shift ;;
        --inner)  MODE=inner ;;
        -h|--help) sed -n '2,27p' "$SELF"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
export PP_ONLY="${ONLY:-${PP_ONLY:-}}"
export PP_AUTO="${AUTO:-${PP_AUTO:-}}"
: "${PP_MODE_LIST:=}"          # keep what the outer run exported
: "${PP_MAP:=}"
export PP_MODE_LIST PP_MAP
[ "$MODE" = list ] && export PP_MODE_LIST=1

# ---------- silk legend, read off the board photo (F7192_V2.2) ----------
silk_hint() {
    case "$1" in
        014|015|016|017|018|019) echo "silk \"${1#0}\", 8-way block: 5V G 14 15 16 17 18 19" ;;
        022|024|029)             echo "silk \"${1#0}\", 4-way block by the LinuxCNC logo: 22 24 29 G" ;;
        *)                       echo "not silked - D-sub / 2x4 header / axis block" ;;
    esac
}

# ---------- the interactive part, run under halrun via loadusr -w ----------
if [ "$MODE" = inner ]; then
    declare -A PHYS FUNC
    while read -r idx phys fn; do
        PHYS[$idx]="$phys"; FUNC[$idx]="$fn"
    done < "$PP_MAP"

    mapfile -t PINS < <(halcmd -s show pin "$BOARD.gpio" 2>/dev/null \
        | awk '$NF ~ /\.out$/ {n=$NF; sub(/.*gpio\./,"",n); sub(/\.out$/,"",n); print n}' \
        | sort -u)

    if [ ${#PINS[@]} -eq 0 ]; then
        echo "ERROR: no free GPIO pins found - did hm2_eth load?" >&2
        exit 1
    fi

    if [ -n "$PP_ONLY" ]; then
        SEL=()
        for want in ${PP_ONLY//,/ }; do
            w=$(printf '%03d' "$((10#$want))")
            for p in "${PINS[@]}"; do [ "$p" = "$w" ] && SEL+=("$p"); done
        done
        PINS=("${SEL[@]}")
        [ ${#PINS[@]} -eq 0 ] && { echo "ERROR: --only matched no free pin." >&2; exit 1; }
    fi

    echo
    echo "Free GPIO (stepgen / encoder pins are absent by design) - map from mesaflash:"
    printf '  %-10s %-8s %-14s %s\n' GPIO PIN 'CARD FUNC' TERMINAL
    for p in "${PINS[@]}"; do
        printf '  gpio.%s   %-8s %-14s %s\n' \
               "$p" "${PHYS[$p]:-?}" "${FUNC[$p]:--}" "$(silk_hint "$p")"
    done
    echo "  ${#PINS[@]} pin(s) to walk"
    echo
    [ -n "$PP_MODE_LIST" ] && exit 0

    if [ -z "$PP_AUTO" ] && [ ! -t 0 ]; then
        echo "ERROR: no terminal on stdin - run this from a normal shell," >&2
        echo "       or use --auto <seconds>." >&2
        exit 1
    fi

    echo "Probe each terminal against a G / GND terminal. ~3.3 V = this pin."
    echo "  SPACE = next pin    r = pulse 10x    n = type a note    q = quit"
    echo "Notes are appended to: $NOTES"
    echo
    [ -n "$PP_AUTO" ] || { read -rsn1 -p "Press any key to start... " _; echo; }

    printf '\n===== probe run =====\n' >> "$NOTES"

    QUIT=0; IDX=0
    for p in "${PINS[@]}"; do
        [ "$QUIT" = 1 ] && break
        PP="${PHYS[$p]:-?}"
        halcmd setp "$BOARD.gpio.$p.is_output" 1 >/dev/null
        halcmd setp "$BOARD.gpio.$p.out" 1      >/dev/null
        printf '\n>>> [%2d/%2d]  gpio.%s  =  %s  is HIGH\n' \
               "$((++IDX))" "${#PINS[@]}" "$p" "$PP"
        printf '            %s\n' "$(silk_hint "$p")"

        if [ -n "$PP_AUTO" ]; then
            sleep "$PP_AUTO"
        else
            while true; do
                read -rsn1 key
                case "$key" in
                    "")  break ;;                       # space / enter
                    r|R) echo "    pulsing gpio.$p ($PP) 10x..."
                         for _ in $(seq 10); do
                             halcmd setp "$BOARD.gpio.$p.out" 0 >/dev/null; sleep 0.15
                             halcmd setp "$BOARD.gpio.$p.out" 1 >/dev/null; sleep 0.15
                         done ;;
                    n|N) read -r -p "    note for gpio.$p ($PP): " note
                         printf 'gpio.%s  %-8s %s\n' "$p" "$PP" "$note" >> "$NOTES"
                         echo "    saved." ;;
                    q|Q) QUIT=1; break ;;
                esac
            done
        fi

        halcmd setp "$BOARD.gpio.$p.out" 0        >/dev/null
        halcmd setp "$BOARD.gpio.$p.is_output" 0  >/dev/null
    done

    echo
    echo "All pins returned to input / low. Notes: $NOTES"
    exit 0
fi

# ---------- outer: sanity checks, mesaflash map, then halrun ----------
if pgrep -x linuxcncsvr >/dev/null || pgrep -f "linuxcnc .*\.ini" >/dev/null; then
    echo "ERROR: LinuxCNC is running - close it first (it owns the 7i92)." >&2
    exit 1
fi
if ! ping -c1 -W2 "$BOARD_IP" >/dev/null 2>&1; then
    echo "ERROR: no reply from $BOARD_IP - check the ethernet link." >&2
    exit 1
fi

# GPIO index -> connector + DB25 pin, straight from the card's IDROM.
# mesaflash must run BEFORE hm2_eth is loaded, or the driver owns the socket.
MAP=$(mktemp /tmp/pin_probe_map_XXXX)
HALFILE=$(mktemp /tmp/pin_probe_XXXX.hal)
trap 'rm -f "$HALFILE" "$MAP"' EXIT

mesaflash --device "$DEVICE" --addr "$BOARD_IP" --readhmid 2>/dev/null \
  | awk '
      /^IO Connections for/ { conn = $NF; next }
      conn != "" && $1 ~ /^[0-9]+$/ && $3 == "IOPort" {
          lbl = ($4 == "None") ? "-" : $4 "#" $5 " " $6
          printf "%03d %s-%02d %s\n", $2, conn, $1, lbl
      }' > "$MAP"

if [ ! -s "$MAP" ]; then
    echo "ERROR: mesaflash --readhmid returned no IO map for $DEVICE at $BOARD_IP." >&2
    echo "       (it cannot talk to the card while hm2_eth is loaded)" >&2
    exit 1
fi
export PP_MAP="$MAP"

cat > "$HALFILE" <<EOF
loadrt hostmot2
loadrt hm2_eth board_ip="$BOARD_IP" config="$HM2_CONFIG"
setp $BOARD.watchdog.timeout_ns 20000000
loadrt threads name1=servo-thread period1=1000000
addf $BOARD.read  servo-thread
addf $BOARD.write servo-thread
start
loadusr -w $SELF --inner
EOF

halrun -f "$HALFILE"
