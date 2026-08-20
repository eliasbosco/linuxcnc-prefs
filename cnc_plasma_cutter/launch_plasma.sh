#!/bin/bash
# ----------------------------------------------------------------------
# launch_plasma.sh - start LinuxCNC/QtPlasmaC automatically at boot
#
# Called from ~/.config/autostart/linuxcnc-plasma.desktop, so it runs
# once per graphical login. LightDM autologins user "pi" into the xfce
# session (/etc/lightdm/lightdm.conf: autologin-user=pi,
# autologin-session=xfce), which means "graphical login" == "boot".
#
# WHY A SCRIPT AND NOT JUST Exec=linuxcnc ...ini IN THE .desktop FILE:
#
#   1. THE MESA CARD IS ON THE NETWORK. hm2_eth talks to the 7i92 at
#      10.10.10.10 (see cnc_plasma_cutter.hal line 9) over eth0, and
#      eth0's 10.10.10.100/8 address is brought up by NetworkManager
#      ("Wired connection 1"). XDG autostart fires as soon as the desktop
#      is ready, which on a cold boot can beat NetworkManager to the
#      punch. If the card is unreachable when hal starts, LinuxCNC dies
#      immediately with "hm2_eth: ERROR: Can't connect to 10.10.10.10"
#      and the operator is left staring at an empty desktop. So: wait for
#      the card to answer before launching.
#
#   2. NO DOUBLE LAUNCH. Starting a second instance while the first holds
#      the realtime modules fails in a confusing way. Note the guard
#      looks for linuxcncsvr, NOT for the /usr/bin/linuxcnc wrapper -
#      killed sessions can leave orphaned wrapper shells (PPID 1) behind
#      that are not a running machine.
#
#   3. SOMEWHERE TO LOOK WHEN IT DOESN'T COME UP. A GUI that never
#      appears leaves no trace; this leaves one in $LOG.
#
# To disable autostart without deleting anything:
#   mv ~/.config/autostart/linuxcnc-plasma.desktop{,.disabled}
# ----------------------------------------------------------------------

CONFIG_DIR="/home/pi/linuxcnc/configs/cnc_plasma_cutter"
INI="$CONFIG_DIR/cnc_plasma_cutter.ini"
MESA_IP="10.10.10.10"       # keep in step with board_ip in cnc_plasma_cutter.hal
MESA_WAIT=60                # seconds to wait for the card before giving up
LOG="$CONFIG_DIR/launch_plasma.log"

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# Keep the log from growing without bound across hundreds of boots.
[ -f "$LOG" ] && [ "$(stat -c %s "$LOG")" -gt 262144 ] && tail -c 131072 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"

log "--- autostart: graphical session up, preparing to launch ---"

if pgrep -x linuxcncsvr > /dev/null; then
    log "LinuxCNC is already running (linuxcncsvr found) - not starting a second instance"
    exit 0
fi

# Wait for the 7i92 to answer. One ping per second, so the loop counter
# doubles as the elapsed seconds.
waited=0
until ping -c 1 -W 1 "$MESA_IP" > /dev/null 2>&1; do
    waited=$((waited + 1))
    if [ "$waited" -ge "$MESA_WAIT" ]; then
        log "ERROR: Mesa 7i92 at $MESA_IP did not answer within ${MESA_WAIT}s - NOT launching."
        log "       Check the ethernet cable to the card and 'ip -br addr' for 10.10.10.100 on eth0."
        # Tell the operator on screen; the desktop is up, so this is visible.
        command -v notify-send > /dev/null && \
            notify-send -u critical "LinuxCNC did not start" \
                        "Mesa 7i92 at $MESA_IP is unreachable. See launch_plasma.log."
        exit 1
    fi
    sleep 1
done
log "Mesa 7i92 at $MESA_IP answered after ${waited}s"

cd "$CONFIG_DIR" || { log "ERROR: cannot cd to $CONFIG_DIR"; exit 1; }

log "starting: linuxcnc $INI"
exec linuxcnc "$INI" >> "$LOG" 2>&1
