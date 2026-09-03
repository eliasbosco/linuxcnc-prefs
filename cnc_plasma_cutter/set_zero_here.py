#!/usr/bin/env python3
"""
SET ZERO HERE - declare the machine's current physical position to be machine
zero, so PARK comes back to this exact spot.

WHY THIS NEEDS A RESTART
------------------------
This machine has no home switches. Both HOME_SEARCH_VEL and HOME_LATCH_VEL are
absent from every [JOINT_n] section, so LinuxCNC uses "immediate homing": HOME
ALL sets each joint's position to that joint's HOME_OFFSET, wherever the machine
happens to be standing.

HOME_OFFSET is read from the INI once, when LinuxCNC starts, and there is no way
to change it in a running instance:

  - linuxcnc.command() exposes home() and unhome(), but no home-offset setter.
  - homemod.so exports only joint.N.{homed,home-state,home-sw-in,homing,
    index-enable} - no offset pin to poke with halcmd.

So "make the current position be zero" means: write 0 into the INI, restart, and
let HOME ALL declare the position. That is what this script does. Unhoming and
rehoming WITHOUT a restart would only re-apply the offset loaded at startup,
which is the stale number we are trying to get rid of.

WHEN TO USE IT
--------------
When the gantry has been pushed by hand with the drives off, or a stepper has
lost steps, LinuxCNC's idea of where it is no longer matches reality. That makes
the soft limits wrong as well as PARK, which is the dangerous part: the machine
believes it has travel it does not have. Jog to the corner you want to call zero,
press this, let it restart, then HOME ALL.

HOW IT RUNS
-----------
Stage 1 (this process, a child of the QtPlasmaC GUI): safety-check, confirm with
the operator, stop save_position.py, write the zeros, hand off to stage 2.

Stage 2 (re-exec of this file with --restart, detached with setsid): it has to
outlive the GUI it is about to kill, which is why it cannot be stage 1. It powers
the machine down, ends the session, clears the persisted offsets in linuxcnc.var
- AFTER LinuxCNC exits, because LinuxCNC rewrites that file from memory on the
way out and would undo an earlier edit - then relaunches through
launch_plasma.sh, which waits for the Mesa card and refuses to start a second
instance.

Wired to a user button in cnc_plasma_cutter.prefs [BUTTONS] as
"%/home/pi/linuxcnc/configs/cnc_plasma_cutter/set_zero_here.py". The handler
Popen()s that without reading stdout, so everything here goes to the log file
instead: a chatty script would eventually block on a full pipe.
"""

import os
import signal
import subprocess
import sys
import time

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
INI = os.path.join(CONFIG_DIR, 'cnc_plasma_cutter.ini')
VAR_FILES = [os.path.join(CONFIG_DIR, 'linuxcnc.var'),
             os.path.join(CONFIG_DIR, 'linuxcnc.var.bak')]
LAUNCHER = os.path.join(CONFIG_DIR, 'launch_plasma.sh')
BACKUP_DIR = os.path.join(CONFIG_DIR, 'backups')
LOG_PATH = os.path.join(CONFIG_DIR, 'set_zero_here.log')

# 5220 is the active coordinate system number. G54 is the valid default and a
# zero there breaks startup, so it is the one parameter never cleared.
ACTIVE_COORD_SYSTEM_PARAM = '5220'

SHUTDOWN_TIMEOUT = 30.0     # seconds to wait for a clean LinuxCNC exit
LOG_LINES_KEPT = 200


def log(message):
    stamp = time.strftime('%Y-%m-%d %H:%M:%S')
    try:
        with open(LOG_PATH, 'a') as f:
            f.write('%s  %s\n' % (stamp, message))
        with open(LOG_PATH) as f:
            lines = f.readlines()
        if len(lines) > LOG_LINES_KEPT * 2:
            with open(LOG_PATH, 'w') as f:
                f.writelines(lines[-LOG_LINES_KEPT:])
    except Exception:
        pass


# ---------------------------------------------------------------- processes

def find_processes(predicate):
    """PIDs whose argv satisfies predicate. Avoids a psutil dependency.

    Deliberately argv-AWARE rather than a substring search over the whole
    command line. A shell whose command text merely mentions "linuxcncsvr" is
    not linuxcncsvr, and stage 2 sends SIGKILL to whatever this returns - a
    naive substring match here happily selects an editor, a grep, or the very
    terminal being used to debug this script.
    """
    found = []
    for entry in os.listdir('/proc'):
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid():
            continue
        try:
            with open('/proc/%d/cmdline' % pid, 'rb') as f:
                argv = [a for a in f.read().decode('utf-8', 'replace').split('\0') if a]
        except Exception:
            continue
        if not argv:
            continue
        try:
            if predicate(argv):
                found.append(pid)
        except Exception:
            continue
    return found


def _runs(argv, name, interpreters=('python',)):
    """True if this process is EXECUTING `name`, not merely mentioning it.

    Two accepted shapes, and nothing else:
      argv[0] is `name`                     - a binary, or a script exec'd direct
      argv[0] is an interpreter, argv[1] is `name`
                                            - shebang form, where the kernel puts
                                              the interpreter first:
                                              /usr/bin/python3 /usr/bin/qtvcp ...

    Both narrowings are load-bearing. Scanning all of argv would match
    "grep qtvcp some.ini"; accepting any argv[1] would match "vi
    save_position.py". Neither is a running machine, and stage 2 sends SIGKILL
    to what these predicates select.
    """
    leader = os.path.basename(argv[0])
    if leader == name:
        return True
    return (len(argv) > 1
            and os.path.basename(argv[1]) == name
            and any(leader.startswith(i) for i in interpreters))


def _mentions_ini(argv):
    """Tolerates the INI being passed absolute or relative."""
    wanted = os.path.basename(INI)
    return any(os.path.basename(a) == wanted for a in argv)


def is_position_daemon(argv):
    return _runs(argv, 'save_position.py') and any(CONFIG_DIR in a for a in argv)


def is_our_gui(argv):
    # The wrapper runs:  qtvcp -ini <INI> qtplasmac
    # qtvcp has a python3 shebang, so argv is
    #   /usr/bin/python3 /usr/bin/qtvcp -ini <INI> qtplasmac
    return _runs(argv, 'qtvcp') and _mentions_ini(argv)


def is_our_wrapper(argv):
    # /bin/bash /usr/bin/linuxcnc <INI>
    return (_runs(argv, 'linuxcnc', interpreters=('bash', 'sh', 'dash'))
            and _mentions_ini(argv))


def is_program(name):
    """Matches a process by the program it is actually executing, not its args."""
    return lambda argv: os.path.basename(argv[0]) == name


def kill_pids(pids, sig=signal.SIGTERM):
    for pid in pids:
        try:
            os.kill(pid, sig)
        except OSError:
            pass


def stop_position_daemon():
    """save_position.py rewrites HOME/HOME_OFFSET from the live position.

    It must be gone before the zeros are written, or it will put the old numbers
    straight back. It is restarted by the INI's [APPLICATIONS] section on the
    next launch, so nothing needs to put it back.
    """
    pids = find_processes(is_position_daemon)
    if pids:
        log('stopping save_position.py: %s' % pids)
        kill_pids(pids)
        time.sleep(1.0)
        still = find_processes(is_position_daemon)
        if still:
            log('save_position.py still up, SIGKILL: %s' % still)
            kill_pids(still, signal.SIGKILL)
    return len(pids)


# ---------------------------------------------------------------- ini / var

def read_positions():
    """(positions, homed, message). positions is None when LinuxCNC is not up."""
    try:
        import linuxcnc
    except Exception as err:
        return None, False, 'linuxcnc module unavailable: %s' % err
    try:
        stat = linuxcnc.stat()
        stat.poll()
    except Exception as err:
        return None, False, 'LinuxCNC is not running: %s' % err

    count = stat.joints or 0
    positions = [stat.joint_actual_position[n] for n in range(count)]
    homed = bool(count) and all(stat.homed[n] for n in range(count))

    if stat.interp_state != linuxcnc.INTERP_IDLE:
        return positions, homed, 'a program is running - stop it first'
    return positions, homed, None


def backup(path):
    if not os.path.isfile(path):
        return None
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dest = os.path.join(BACKUP_DIR, '%s.prezero.%s'
                        % (os.path.basename(path), time.strftime('%y%m%d_%H%M%S')))
    with open(path, 'rb') as src, open(dest, 'wb') as dst:
        dst.write(src.read())
    return dest


def zero_ini_home_values(path):
    """Set HOME and HOME_OFFSET to 0.000 in every [JOINT_n] section.

    Line-based, like save_position.py's writer: configparser would strip the
    comments and layout that make this INI readable.
    """
    with open(path) as f:
        lines = f.readlines()

    section = None
    changed = 0
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
        if section and section.startswith('JOINT_') and '=' in stripped:
            key = stripped.split('=', 1)[0].strip()
            if key in ('HOME', 'HOME_OFFSET'):
                out.append('%s = 0.000\n' % key)
                changed += 1
                continue
        out.append(line)

    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.writelines(out)
    os.replace(tmp, path)      # atomic: a crash mid-write cannot truncate the INI
    return changed


def clear_var_offsets():
    """Zero every G28/G30/G92/G54-G59.3 parameter, keeping 5220.

    Only safe once LinuxCNC has exited: it writes this file from its in-memory
    parameter table during shutdown, so an edit made while it is running is
    thrown away.
    """
    total = 0
    for path in VAR_FILES:
        if not os.path.isfile(path):
            continue
        out = []
        for line in open(path):
            fields = line.split()
            if len(fields) == 2 and fields[0] != ACTIVE_COORD_SYSTEM_PARAM:
                if float(fields[1]) != 0.0:
                    total += 1
                out.append('%s\t0.000000\n' % fields[0])
            else:
                out.append(line)
        tmp = path + '.tmp'
        with open(tmp, 'w') as f:
            f.writelines(out)
        os.replace(tmp, path)
    return total


# ---------------------------------------------------------------- operator

def ask(positions, homed):
    """Modal yes/no. Returns True to go ahead.

    The QtPlasmaC handler Popen()s this script without waiting, so blocking here
    does not freeze the GUI. Tk is used rather than Qt to keep a second Qt
    application out of the GUI's process tree.
    """
    axes = ['X', 'Y', 'Z', 'Y2']
    if positions:
        shown = '\n'.join('    %-3s %10.3f' % (axes[i] if i < len(axes) else 'J%d' % i, p)
                          for i, p in enumerate(positions))
        where = 'The machine currently reads:\n\n%s\n\n' % shown
        if not homed:
            where += 'NOTE: the machine is not homed, so those numbers\nare not meaningful yet.\n\n'
    else:
        where = 'LinuxCNC does not appear to be running.\n\n'

    message = (
        'Make this position machine ZERO?\n\n'
        + where +
        'This will:\n'
        '  - set HOME and HOME_OFFSET to 0 on all four joints\n'
        '  - clear the stored work offsets (G54-G59.3, G92)\n'
        '  - RESTART QtPlasmaC (about 30 seconds)\n\n'
        'Any loaded job will be lost. After it restarts,\n'
        'press HOME ALL and this spot reads 0.\n\n'
        'Do not move the machine until it is back up.'
    )

    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        answer = messagebox.askyesno('SET ZERO HERE', message, icon='warning',
                                     default='no', parent=root)
        root.destroy()
        return answer
    except Exception as err:
        log('no dialog available (%s)' % err)
        # Better to do nothing than to restart the machine unasked.
        return False


def notify(title, message):
    try:
        subprocess.Popen(['notify-send', '-u', 'critical', title, message],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------- stage 2

def stage2_restart():
    """Detached: end the session, clear the var file, relaunch."""
    log('--- stage 2: restarting LinuxCNC ---')
    time.sleep(1.0)

    # Drop the drive enables before anything is torn down.
    try:
        import linuxcnc
        cmd = linuxcnc.command()
        cmd.state(linuxcnc.STATE_OFF)
        cmd.wait_complete(5)
        log('machine powered off')
    except Exception as err:
        log('could not power off cleanly: %s' % err)

    # Ending the GUI makes the /usr/bin/linuxcnc wrapper run its own teardown,
    # which is what writes linuxcnc.var and runs shutdown.hal.
    gui = find_processes(is_our_gui)
    log('terminating GUI: %s' % gui)
    kill_pids(gui)

    # Wait for milltask as well as linuxcncsvr, not just the server. The
    # wrapper's Cleanup kills them in the order linuxcncsvr, motion-logger,
    # milltask - and milltask is the one that writes linuxcnc.var from its
    # parameter table on the way out. Clearing that file the moment the server
    # disappears would race a milltask that is still writing it, and the stale
    # offsets would come straight back.
    core = [is_program('linuxcncsvr'), is_program('milltask')]

    def still_up():
        return [pid for pred in core for pid in find_processes(pred)]

    deadline = time.time() + SHUTDOWN_TIMEOUT
    while time.time() < deadline:
        if not still_up():
            break
        time.sleep(0.5)

    if still_up():
        log('clean shutdown timed out after %.0fs (%s), forcing'
            % (SHUTDOWN_TIMEOUT, still_up()))
        for pred in core + [is_our_gui]:
            kill_pids(find_processes(pred), signal.SIGKILL)
        time.sleep(2.0)
        try:
            subprocess.run(['halrun', '-U'], timeout=15,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as err:
            log('halrun -U failed: %s' % err)
    else:
        log('LinuxCNC exited cleanly')

    # launch_plasma.sh guards on linuxcncsvr only, because a killed session can
    # leave orphaned wrapper shells behind. Clear them out so they do not pile up.
    orphans = find_processes(is_our_wrapper)
    if orphans:
        log('clearing orphaned wrapper shells: %s' % orphans)
        kill_pids(orphans, signal.SIGKILL)

    time.sleep(1.0)

    cleared = clear_var_offsets()
    log('cleared %d non-zero offset(s) in linuxcnc.var' % cleared)

    # save_position.py was stopped before the INI was written, but LinuxCNC has
    # only just let go of the file. Confirm the zeros really are on disk.
    # Compared as numbers, not text: save_position.py formats with %.3f and a
    # tiny negative float comes out as "-0.000", which is zero but not "0.000".
    stale = []
    with open(INI) as f:
        for ln in f:
            if not ln.startswith(('HOME =', 'HOME_OFFSET =')):
                continue
            try:
                if float(ln.split('=', 1)[1]) != 0.0:
                    stale.append(ln.strip())
            except ValueError:
                stale.append(ln.strip())
    if stale:
        log('zeros did not stick (%s), rewriting' % stale)
        zero_ini_home_values(INI)

    log('relaunching via %s' % LAUNCHER)
    os.execv('/bin/bash', ['/bin/bash', LAUNCHER])


# ---------------------------------------------------------------- stage 1

def stage1_button():
    log('--- SET ZERO HERE pressed ---')

    positions, homed, problem = read_positions()
    if problem and positions is not None:
        log('refused: %s' % problem)
        notify('SET ZERO HERE', problem.capitalize() + '.')
        return 1

    if not ask(positions, homed):
        log('operator cancelled')
        return 0

    if positions:
        log('zeroing at ' + ' '.join('%.3f' % p for p in positions))

    stop_position_daemon()

    saved = backup(INI)
    log('INI backed up to %s' % saved)
    changed = zero_ini_home_values(INI)
    log('zeroed %d HOME/HOME_OFFSET value(s)' % changed)

    if changed == 0:
        log('WARNING: no HOME values found to zero - is the INI intact?')

    # Detached with setsid so it survives the GUI it is about to end. Without a
    # new session it would be killed alongside its parent.
    subprocess.Popen([sys.executable, os.path.abspath(__file__), '--restart'],
                     start_new_session=True,
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    log('stage 2 handed off; stage 1 done')
    return 0


def main():
    if '--restart' in sys.argv:
        try:
            stage2_restart()
        except Exception as err:
            log('stage 2 FAILED: %s' % err)
            notify('SET ZERO HERE failed',
                   'LinuxCNC may be down. Start it from the desktop and check '
                   'set_zero_here.log.')
            return 1
        return 0
    return stage1_button()


if __name__ == '__main__':
    sys.exit(main())
