#!/bin/bash
# ----------------------------------------------------------------------
# thcad_zero.sh - decide WHY the ARC readout is not 0 V with the torch off
#
# WHY: with the torch off and the HBC65 idle the true input is 0 V, so the
# ARC box must read 0. QtPlasmaC computes
#       volts = velocity_Hz * Scale + Offset       (0.0124 / -38.75 here)
# and TWO completely different faults both put |39| on that display:
#
#   velocity = +6270 Hz  ->  +39 V   counter registers 2 counts per FOUT
#                                    cycle (the wandering multiplier N
#                                    documented in custom.hal). Card fine,
#                                    counting wrong.
#   velocity =     0 Hz  ->  -39 V   nothing is counting at all: the bare
#                                    Offset is showing through. Dead FOUT+
#                                    run, dead card, or wrong pin.
#
# A phone photo of the screen cannot be trusted to show the minus sign, so
# read the number here instead. The card is spec'd to emit ~3125 Hz at 0 V
# (100 kHz raw / 32, see custom.hal), which is exactly what the current
# calibration maps to 0.00 V - so 3125 is the target, and the ratio of what
# you measure to 3125 IS the count multiplier N.
#
# Usage:  ./thcad_zero.sh            5 s sample
#         ./thcad_zero.sh 20         20 s sample (catches drift)
#
# LinuxCNC must be RUNNING and the torch must be OFF (do not press Cycle
# Start). This only reads pins - it drives nothing.
#
# Companion to arc_watch.sh (arc-ok/torch-on timing) and pin_probe.sh
# (drive pins with LinuxCNC closed).
# ----------------------------------------------------------------------
set -u

SECS=${1:-5}
FZERO=3125          # spec'd THCAD2 output at 0 V input, already /32
PREFS="$(dirname "$0")/cnc_plasma_cutter.prefs"

command -v halcmd >/dev/null || { echo "halcmd not found"; exit 1; }
# halcmd can exit 0 with empty output when there is no realtime session, so
# test the OUTPUT, not the exit status.
# halcmd happily attaches to (or creates) an EMPTY hal instance when nothing
# is running - it prints the table header and exits 0. So the test is "are
# there any pins", not "did halcmd succeed".
PINS=$(halcmd show pin 2>/dev/null)
echo "$PINS" | grep -q '\.' || {
    echo "ERROR: HAL has no pins - LinuxCNC is not running. Start it, leave the"
    echo "       torch OFF, and run this again."; exit 1; }

# Find the encoder rather than hard-coding hm2_7i92.0 - the board name
# changes if the card or the firmware is ever swapped. Match on the field
# itself rather than a column number: `show pin` gained an Inst column in
# 2.9, so the name is not always $5.
VEL=$(echo "$PINS" | awk '{for(i=1;i<=NF;i++) if ($i ~ /encoder\.00\.velocity$/) {print $i; exit}}')
RAW=${VEL%velocity}rawcounts
[ -n "$VEL" ] || { echo "ERROR: no encoder.00.velocity pin found"; exit 1; }

# Calibration actually in force, straight from the prefs file.
SCALE=$(awk -F= '/^Arc Voltage Scale/  {gsub(/ /,"",$2); print $2}' "$PREFS")
OFFS=$(awk  -F= '/^Arc Voltage Offset/ {gsub(/ /,"",$2); print $2}' "$PREFS")

TORCH=$(halcmd getp plasmac.torch-on 2>/dev/null || echo "?")
[ "$TORCH" = "TRUE" ] && {
    echo "REFUSING: plasmac.torch-on is TRUE - this test needs the torch OFF"
    exit 1; }

echo "encoder : $VEL"
echo "cal     : Scale=$SCALE  Offset=$OFFS   (volts = (Hz - Offset) * Scale)"
# Offset is the ZERO-VOLT FREQUENCY in Hz. If it is negative it is wrong -
# that is the old volts-shaped value and it puts the ARC box ~39 V high.
case "$OFFS" in -*) echo "  !! Offset is NEGATIVE. It must be the zero-volt frequency in Hz"
                    echo "  !! (~3128 here), not a voltage. The ARC box will read ~39 V high.";;
esac
# Report the settings that are supposed to be holding the count multiplier at
# 1, so a run proves they are actually in force rather than assuming custom.hal
# had the last word. sample-frequency 2000000 is the one that matters.
BASE=${VEL%00.velocity}
printf "hostmot2: sample-frequency=%s  filter=%s  scale=%s\n" \
    "$(halcmd getp ${BASE}sample-frequency 2>/dev/null || echo '?')" \
    "$(halcmd getp ${BASE}00.filter        2>/dev/null || echo '?')" \
    "$(halcmd getp ${BASE}00.scale         2>/dev/null || echo '?')"
# plasmac applies its OWN scale/offset to the frequency - the prefs file is
# only what the GUI is supposed to push into these pins at startup. If the ARC
# box disagrees with (freq * Scale + Offset) computed from the prefs, it is
# these pins that are wrong, not the encoder. Dump every voltage-related
# plasmac pin rather than guessing the names.
echo "plasmac voltage pins (the authority - prefs are only the source):"
halcmd show pin plasmac 2>/dev/null | grep -iE "volt" | sed 's/^/  /' || echo "  none"

echo "sampling $SECS s with the torch off ..."
echo

# Two independent measurements of the same thing. .velocity is hostmot2's
# own timestamped estimate; rawcounts/elapsed is a plain count over wall
# time. If they disagree the velocity estimator is the problem, not the
# wiring - that distinction is worth the three extra lines.
C0=$(halcmd getp "$RAW"); T0=$(date +%s.%N)
SAMPLES=""
END=$(echo "$T0 + $SECS" | bc -l)
while (( $(echo "$(date +%s.%N) < $END" | bc -l) )); do
    SAMPLES="$SAMPLES $(halcmd getp "$VEL")"
    sleep 0.1
done
C1=$(halcmd getp "$RAW"); T1=$(date +%s.%N)

# What plasmac ACTUALLY receives, i.e. downstream of abs.0 in custom.hal.
# This is the number the ARC box renders, so it is the one that settles any
# argument about the sign.
AVI=$(halcmd getp plasmac.arc-voltage-in 2>/dev/null || echo "n/a")
# arc-voltage-out is the volts plasmac itself computed - it IS the number in
# the ARC box. Everything else here is a prediction; this is the observation,
# and it also picks up the lowpass filter if one is ever enabled.
AVO=$(halcmd getp plasmac.arc-voltage-out 2>/dev/null || echo "n/a")

echo "$SAMPLES" | tr ' ' '\n' | grep -v '^$' | awk -v s="$SCALE" -v o="$OFFS" \
     -v fz="$FZERO" -v c0="$C0" -v c1="$C1" -v t0="$T0" -v t1="$T1" \
     -v enc="${VEL%velocity}" -v avi="$AVI" -v avo="$AVO" '
{ v=$1+0; n++; sum+=v; if (n==1||v<min) min=v; if (n==1||v>max) max=v }
END {
    if (!n) { print "no samples"; exit 1 }
    mean=sum/n; a=mean<0?-mean:mean
    printf "velocity   : mean %.1f Hz   min %.1f   max %.1f   (n=%d)\n", mean,min,max,n
    printf "rawcounts  : %.1f Hz over %.2f s\n", (c1-c0)/(t1-t0), t1-t0
    # abs.0 sits between the encoder and plasmac, so the MAGNITUDE is what
    # gets scaled into volts - never the raw signed velocity.
    # plasmac computes volts = (freq - Offset) * Scale, with Offset a FREQUENCY
    # in Hz. Verified against a simultaneous pin snapshot 2026-08-13; see the
    # THE OFFSET IS A FREQUENCY block in custom.hal.
    v = (a - o) * s
    printf "after abs  : %.1f Hz  -> %.2f V  -> the ARC box shows %d\n", a, v, int(v+(v<0?-0.5:0.5))
    printf "plasmac in : %s Hz  (live, downstream of abs.0)\n", avi
    printf "ARC BOX    : %s V  <- measured, not predicted\n", avo
    printf "multiplier : N = %.3f  (magnitude / %d)\n\n", a/fz, fz
    if (a < 50)
        print "VERDICT: DEAD COUNTER. Nothing is reaching the counter, so the bare\n         Offset is what you see (-39). Chase the FOUT+ wiring / the card,\n         NOT the calibration. Check FOUT- is left floating (custom.hal)."
    else {
        r=a/fz
        if (r > 0.9 && r < 1.1) {
            print "VERDICT: COUNTING CLEANLY (N=1). This is the good case - the ARC box\n         should be reading ~0. Calibrate against real arc voltage now."
            if (mean < 0)
                print "\n         (velocity is NEGATIVE. That is EXPECTED and harmless: Quad-B\n         GPIO26 is unwired, so the count direction floats and flips\n         between sessions. abs.0 in custom.hal takes the magnitude, so\n         the reading is correct either way. Do NOT flip encoder scale.)"
        }
        else
            printf "VERDICT: MULTIPLE COUNTS PER CYCLE, N ~ %.2f. The card is fine; the\n         counter sees %.2f edges per FOUT cycle. This came back after being\n         solved by the 2 MHz sample clock - check encoder.sample-frequency\n         first, then the FOUT+ wiring. Last resort, divide it out with\n           setp %sscale %.0f\n         (only valid while N stays put - re-run this after every restart).\n", r, r, enc, r
    }
    if (max-min > 200) printf "\nNOTE: spread is %.0f Hz - the reading is not steady. Treat any\n      calibration done now as worthless.\n", max-min
}'
