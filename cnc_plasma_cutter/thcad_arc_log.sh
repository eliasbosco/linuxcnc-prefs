#!/bin/bash
# ----------------------------------------------------------------------
# thcad_arc_log.sh - find out WHY the THCAD reads ~0 Hz while the torch fires
#
# SYMPTOM (2026-08-13): torch off reads 0.00 V correctly, but during a cut the
# ARC box shows -39 V. Under the real formula
#       volts = (freq_Hz - Offset_Hz) * Scale = (freq - 3128.4) * 0.0124
# -39 V works back to freq ~= 0 Hz. So the counter is not merely wrong during
# the cut, it has STOPPED. A cut at 100 V should read ~11200 Hz, which is far
# inside the 66.7 kHz ceiling of the current glitch filter, so this is not
# clipping at the top of the range.
#
# THE TWO CANDIDATES, and they need opposite fixes:
#
#   A) SIGNAL KILLED. Torch HF start / arc noise swamps the single-ended FOUT+
#      run, or browns out the THCAD, and no edges arrive at all.
#      -> rawcounts FREEZES. delta is exactly 0, sample after sample.
#
#   B) DIRECTION BIT FLIPPING. Quad-B (GPIO26) is unwired, and in counter-mode
#      it IS the count direction. HF noise on a floating input flips it, the
#      counter runs up then down, and the counts cancel to a net of nothing.
#      -> rawcounts KEEPS MOVING but the delta changes SIGN between samples,
#         and abs() of the net is near zero while the activity is high.
#
# abs.0 in custom.hal cannot save case B - it takes the magnitude of an
# already-cancelled velocity. Only pinning GPIO26 to a defined level fixes it.
#
# Usage:  ./thcad_arc_log.sh              wait for torch-on, log until it ends
#         ./thcad_arc_log.sh -t 120       give up waiting after 120 s
#         ./thcad_arc_log.sh -o log.txt   explicit log file
#
# Start it BEFORE Cycle Start. LinuxCNC must be running. Reads only.
#
# *** BEFORE YOU CUT FOR THIS TEST: turn THC ENABLE OFF. ***
# The arc voltage plasmac is receiving is garbage, so any height correction it
# computes from it is garbage too. With "Use auto volts" the target is sampled
# from the same bad reading, which can look deceptively stable - that is THC
# doing nothing, not THC working.
#
# Companion to thcad_zero.sh (torch-off zero check) and arc_watch.sh.
# ----------------------------------------------------------------------
set -u

WAIT=300
OUT=""
while getopts "t:o:" o; do case $o in t) WAIT=$OPTARG;; o) OUT=$OPTARG;; esac; done
[ -n "$OUT" ] || OUT="thcad_arc_$(date +%y-%m-%d_%H-%M-%S).log"

halcmd show pin 2>/dev/null | grep -q '\.' || {
    echo "ERROR: HAL has no pins - LinuxCNC is not running."; exit 1; }

BASE=$(halcmd show pin 2>/dev/null | awk '{for(i=1;i<=NF;i++) if ($i ~ /encoder\.00\.velocity$/) {print $i; exit}}')
BASE=${BASE%velocity}
[ -n "$BASE" ] || { echo "ERROR: encoder not found"; exit 1; }

echo "logging to $OUT"
echo "waiting up to ${WAIT}s for torch-on ... (Cycle Start when ready)"
{
  echo "# t_rel rawcounts delta velocity arc_volts torch_on arc_ok"
} > "$OUT"

# One `show pin` per sample gets every value from a SINGLE snapshot, so the
# count, the velocity and the volts are all from the same instant. Polling
# each pin with its own halcmd would smear them across ~20 ms and make the
# delta analysis meaningless.
snap() {
    # Match the pin name by EXACT field equality. Matching on a suffix picks up
    # the signal name too ("plasmac.torch-on ==> plasmac:torch-on" both end in
    # torch-on), and $(i-1) then lands on the "==>" arrow instead of the value.
    # That silently wrote "==>" into the torch_on column of the 17:14 log.
    halcmd show pin 2>/dev/null | awk -v enc="$BASE" '
        {for(i=1;i<=NF;i++) {
            if ($i == enc "rawcounts")            rc=$(i-1)
            else if ($i == enc "velocity")        vl=$(i-1)
            else if ($i == "plasmac.arc-voltage-out") av=$(i-1)
            else if ($i == "plasmac.torch-on")    to=$(i-1)
            # arc-ok-in is the HARDWARE input (Mode 1 takes arc-ok from
            # gpio.014, not from the voltage). There is no plain
            # "plasmac.arc-ok" pin - asking for one logs NA.
            else if ($i == "plasmac.arc-ok-in")   ao=$(i-1)
        }}
        END {printf "%s %s %s %s %s\n", (rc==""?"NA":rc), (vl==""?"NA":vl), (av==""?"NA":av), (to==""?"NA":to), (ao==""?"NA":ao)}'
}

T_START=$(date +%s.%N)
PREV=""; FIRED=0; IDLE=0
while :; do
    NOW=$(date +%s.%N)
    EL=$(echo "$NOW - $T_START" | bc -l)
    read -r RC VL AV TO AO <<< "$(snap)"
    [ "$RC" = "NA" ] && { echo "ERROR: could not read rawcounts"; exit 1; }

    if [ -n "$PREV" ]; then D=$((RC - PREV)); else D=0; fi
    PREV=$RC
    printf "%.3f %s %s %s %s %s %s\n" "$EL" "$RC" "$D" "$VL" "$AV" "$TO" "$AO" >> "$OUT"

    [ "$TO" = "TRUE" ] && FIRED=1
    if [ "$FIRED" = 1 ] && [ "$TO" != "TRUE" ]; then
        IDLE=$((IDLE+1)); [ "$IDLE" -gt 30 ] && break
    else IDLE=0; fi
    if [ "$FIRED" = 0 ] && (( $(echo "$EL > $WAIT" | bc -l) )); then
        echo "timed out waiting for torch-on"; exit 1; fi
    sleep 0.05
done

echo; echo "=== torch fired - analysis ==="
awk 'NR>1 {
    on = ($6=="TRUE")
    d = $3; ad = (d<0?-d:d)
    if (on) { n1++; net1+=d; act1+=ad; if (d!=0) moved1++; if (d<0) neg1++; v1+=$5 }
    else    { n0++; net0+=d; act0+=ad; if (d!=0) moved0++; v0+=$5 }
}
END {
    if (!n1) { print "no torch-on samples captured"; exit }
    printf "torch OFF: %d samples  net %+d counts  activity %d  volts %.1f\n",
           n0, net0, act0, (n0? v0/n0 : 0)
    printf "torch ON : %d samples  net %+d counts  activity %d  volts %.1f\n",
           n1, net1, act1, v1/n1
    printf "           deltas that moved at all: %d / %d   negative: %d\n\n",
           moved1, n1, neg1
    if (moved1 == 0)
        print "VERDICT A: COUNTER FROZEN. rawcounts did not move ONCE while the\n           torch was on - no edges are arriving. The FOUT+ signal or the\n           THCAD itself is being killed by the arc. Screen/reroute FOUT+\n           away from the torch lead, check the THCAD 5V under load."
    else if (neg1 > n1*0.15)
        print "VERDICT B: DIRECTION FLIPPING. rawcounts is moving BOTH ways while\n           the torch is on, so counts are cancelling to nothing. This is\n           the floating Quad-B (GPIO26) direction input picking up HF.\n           TIE GPIO26 (P1 pin 6) - 1k to GND. abs.0 cannot fix this."
    else
        printf "VERDICT: counter is moving forward (%d net counts). If the volts are\n         still wrong the fault is in the scaling, not the counting.\n", net1
}' "$OUT"
echo; echo "full trace: $OUT"
