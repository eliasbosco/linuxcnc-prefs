#!/bin/bash
# ----------------------------------------------------------------------
# pin_probe.sh - walk every FREE GPIO on the Mesa 7i92 / F7192 clone,
# driving each one HIGH so it can be found with a multimeter.
#
# Runs in either of two modes, picked automatically:
#
# STANDALONE (LinuxCNC closed) - the original behaviour. Asks the card
# itself, with "mesaflash --readhmid", for the GPIO -> connector/DB25-pin
# map, then loads hm2_eth with the machine's config= string so the pins
# owned by the 5 stepgens and the encoder are not GPIO at all and can
# never be toggled here. The pwmgen is NOT loaded (num_pwmgens=0), so its
# pin is handed back to GPIO and gets walked too. The map is cached to
# pin_probe_map.txt so attached runs can still show connector pins.
#
# ATTACHED (LinuxCNC / QtPlasmaC running) - talks to the live HAL with
# halcmd instead of loading its own. mesaflash CANNOT run in this mode
# (hm2_eth owns the socket), so the connector map comes from the cached
# pin_probe_map.txt if one exists, otherwise pins are listed without it.
# Pins already net'd to a signal in the running config are SKIPPED, not
# driven - fighting a signal's writer would error or, worse, work. Each
# pin's is_output/out are saved before and restored after, so a pin the
# config was already driving is left exactly as it was found.
#
#   !! ATTACHED MODE DRIVES REAL PINS ON A LIVE MACHINE !!
#   Put the machine in E-stop first. An unlabelled pin may be wired to
#   something that moves, and this walks pins one at a time driving each
#   to 3.3 V. The script asks for confirmation before starting.
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
#   ./pin_probe.sh --force      attached mode: skip the E-stop prompt
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
MAPCACHE="$HERE/pin_probe_map.txt"

MODE=walk
ONLY=""
AUTO=""
FORCE=""
while [ $# -gt 0 ]; do
    case "$1" in
        --list)   MODE=list ;;
        --only)   ONLY="$2"; shift ;;
        --auto)   AUTO="$2"; shift ;;
        --force)  FORCE=1 ;;
        --inner)  MODE=inner ;;
        -h|--help) sed -n '2,42p' "$SELF"; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
    shift
done
export PP_ONLY="${ONLY:-${PP_ONLY:-}}"
export PP_AUTO="${AUTO:-${PP_AUTO:-}}"
: "${PP_MODE_LIST:=}"          # keep what the outer run exported
: "${PP_MAP:=}"
: "${PP_ATTACHED:=}"           # set by the outer run when LinuxCNC is up
export PP_MODE_LIST PP_MAP PP_ATTACHED
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
    if [ -n "$PP_MAP" ] && [ -s "$PP_MAP" ]; then
        while read -r idx phys fn; do
            PHYS[$idx]="$phys"; FUNC[$idx]="$fn"
        done < "$PP_MAP"
    fi

    # A pin net'd to a signal prints with the signal after the pin name:
    #   ... hm2_7i92.0.gpio.030.out     <== plasmac:torch-on
    #   ... hm2_7i92.0.gpio.015.in_not  ==> plasmac:float-switch
    # so the pin name is NOT the last field. Any gpio.NNN.* that is linked
    # marks the WHOLE of gpio.NNN as in use, not just that one field -
    # gpio.015 is the float switch even though only its .in_not is net'd,
    # and driving .out on it would fight the external switch and clobber
    # the input the machine is reading. Free pins are walked, used ones are
    # listed so it is obvious why they were left alone.
    declare -A OWNER
    HAVE_OUT=(); USED=()
    while read -r p field sig; do
        if [ "$sig" != "-" ]; then
            [ -n "${OWNER[$p]:-}" ] || { USED+=("$p"); OWNER[$p]="$sig ($field)"; }
        elif [ "$field" = out ]; then
            HAVE_OUT+=("$p")
        fi
    done < <(halcmd -s show pin "$BOARD.gpio" 2>/dev/null \
        | awk '{ for (i=1;i<=NF;i++) if ($i ~ /gpio\.[0-9]+\.[a-z_]+$/) {
                     n=$i; sub(/.*gpio\./,"",n)
                     f=n; sub(/^[0-9]+\./,"",f); sub(/\..*$/,"",n)
                     print n, f, (i<NF ? $NF : "-") } }' \
        | sort -u)

    # Only pins that expose an .out can be driven at all (stepgen / pwmgen /
    # encoder pins do not), minus anything the running config is using.
    PINS=(); LINKED=("${USED[@]}")
    for p in "${HAVE_OUT[@]}"; do
        [ -n "${OWNER[$p]:-}" ] || PINS+=("$p")
    done

    if [ ${#PINS[@]} -eq 0 ]; then
        if [ -n "$PP_ATTACHED" ]; then
            echo "ERROR: no free GPIO pins - is LinuxCNC really up? (halcmd found none)" >&2
        else
            echo "ERROR: no free GPIO pins found - did hm2_eth load?" >&2
        fi
        exit 1
    fi

    if [ -n "$PP_ONLY" ]; then
        SEL=()
        for want in ${PP_ONLY//,/ }; do
            w=$(printf '%03d' "$((10#$want))")
            for p in "${PINS[@]}"; do [ "$p" = "$w" ] && SEL+=("$p"); done
            for p in "${LINKED[@]}"; do
                [ "$p" = "$w" ] && echo "  skipping gpio.$w - already net'd to ${OWNER[$w]}" >&2
            done
        done
        PINS=("${SEL[@]}")
        [ ${#PINS[@]} -eq 0 ] && { echo "ERROR: --only matched no free pin." >&2; exit 1; }
    fi

    echo
    if [ -n "$PP_ATTACHED" ]; then
        echo "ATTACHED to the running LinuxCNC. Free GPIO (stepgen / encoder /"
        echo "pwmgen pins are absent by design, net'd pins are listed below):"
    else
        echo "Free GPIO (stepgen / encoder pins are absent by design) - map from mesaflash:"
    fi
    printf '  %-10s %-8s %-14s %s\n' GPIO PIN 'CARD FUNC' TERMINAL
    for p in "${PINS[@]}"; do
        printf '  gpio.%s   %-8s %-14s %s\n' \
               "$p" "${PHYS[$p]:-?}" "${FUNC[$p]:--}" "$(silk_hint "$p")"
    done
    echo "  ${#PINS[@]} pin(s) to walk"
    if [ ${#LINKED[@]} -gt 0 ]; then
        echo
        echo "  NOT walked - already used by the running config:"
        for p in "${LINKED[@]}"; do
            printf '    gpio.%s   %-8s <== %s\n' "$p" "${PHYS[$p]:-?}" "${OWNER[$p]}"
        done
    fi
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

    # Restore whatever we found on the way out. In standalone mode this is
    # always input/low, but attached to a running config a pin may already
    # be set up as a driven output (e.g. one poked by hand with halcmd), and
    # blindly forcing it back to input would change the machine's state.
    restore_pin() {
        halcmd setp "$BOARD.gpio.$1.out"       "${2:-FALSE}" >/dev/null 2>&1
        halcmd setp "$BOARD.gpio.$1.is_output" "${3:-FALSE}" >/dev/null 2>&1
    }
    CUR=""; CUR_OUT=""; CUR_IO=""
    trap '[ -n "$CUR" ] && restore_pin "$CUR" "$CUR_OUT" "$CUR_IO"' EXIT INT TERM

    QUIT=0; IDX=0
    for p in "${PINS[@]}"; do
        [ "$QUIT" = 1 ] && break
        PP="${PHYS[$p]:-?}"
        CUR_OUT=$(halcmd -s getp "$BOARD.gpio.$p.out"       2>/dev/null || echo FALSE)
        CUR_IO=$(halcmd  -s getp "$BOARD.gpio.$p.is_output" 2>/dev/null || echo FALSE)
        CUR="$p"
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

        restore_pin "$p" "$CUR_OUT" "$CUR_IO"
        CUR=""
    done
    trap - EXIT INT TERM

    echo
    echo "All pins restored to the state they were found in. Notes: $NOTES"
    exit 0
fi

# ---------- outer: attached mode, if LinuxCNC already owns the card ----------
if pgrep -x linuxcncsvr >/dev/null || pgrep -f "linuxcnc .*\.ini" >/dev/null; then
    if ! halcmd -s show comp >/dev/null 2>&1; then
        echo "ERROR: LinuxCNC is running but halcmd cannot reach its HAL." >&2
        echo "       (different user? try running this as the same user)" >&2
        exit 1
    fi

    # mesaflash is useless here - hm2_eth holds the socket - so fall back to
    # the map cached by the last standalone run. Missing cache is not fatal;
    # the walk still works, it just cannot print connector/DB25 pin numbers.
    if [ -s "$MAPCACHE" ]; then
        export PP_MAP="$MAPCACHE"
    else
        export PP_MAP=""
        echo "NOTE: no cached pin map ($MAPCACHE) - connector pins will show as '?'." >&2
        echo "      Run this once with LinuxCNC closed to build the cache." >&2
    fi
    export PP_ATTACHED=1

    if [ -z "$FORCE" ] && [ -z "$PP_MODE_LIST" ]; then
        cat >&2 <<'WARN'

  *** LinuxCNC is RUNNING - this will drive real pins on a live machine. ***
  Put the machine in E-STOP before continuing. Pins already net'd in the
  config are skipped, but an unlabelled free pin may still be wired to
  something. Pass --force to skip this prompt.

WARN
        if [ ! -t 0 ]; then
            echo "ERROR: not a terminal - use --force to confirm non-interactively." >&2
            exit 1
        fi
        read -r -p "  Machine in E-stop? type YES to continue: " ok
        [ "$ok" = YES ] || { echo "  aborted."; exit 1; }
    fi

    exec "$SELF" --inner
fi

# ---------- outer: sanity checks, mesaflash map, then halrun ----------
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

# Cache it - mesaflash cannot run while LinuxCNC holds the card, so an
# attached run has no other way to name connector / DB25 pins.
cp -f "$MAP" "$MAPCACHE" 2>/dev/null || true

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
