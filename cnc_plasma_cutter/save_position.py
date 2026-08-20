#!/usr/bin/env python3
"""
Persist machine position across LinuxCNC restarts.

This machine homes immediately (no home switches), so LinuxCNC would otherwise
come up believing it sits at zero no matter where it was actually left. This
daemon records the live joint positions into the [JOINT_n] HOME / HOME_OFFSET
values in the INI while LinuxCNC runs. On the next start, HOME ALL then declares
the real position, so PARK can drive back to the true corner.

Started from the INI:  [APPLICATIONS] APP = ./save_position.py
Can also be run by hand from the config directory for debugging.

HOME and HOME_OFFSET are always written to the SAME value. If they differ,
LinuxCNC rapids the joint to HOME immediately after homing.

Progress and errors go to save_position.log beside the INI, because anything
printed to stdout is lost when LinuxCNC is started from a desktop icon.

Caveat: this trusts that nothing moved the machine while it was powered off.
Steppers have no position feedback, so a gantry pushed by hand while the drives
are off will make the saved value wrong. Home switches are the real fix.
"""

import glob
import os
import sys
import time

import linuxcnc

POLL_SECONDS = 1.0
IDLE_POLLS = 3              # must be still this many polls before saving
MIN_CHANGE = 0.02           # mm; ignore noise below this
MIN_WRITE_INTERVAL = 5.0    # seconds; limit SD card writes
GIVE_UP_AFTER = 60          # consecutive failed polls before deciding we are done

LOG_LINES_KEPT = 200


def find_ini():
    if len(sys.argv) > 1:
        return sys.argv[1]
    if os.environ.get('INI_FILE_NAME'):
        return os.environ['INI_FILE_NAME']
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = sorted(glob.glob(os.path.join(here, '*.ini')))
    return candidates[0] if len(candidates) == 1 else None


class Log:
    """Tiny self-trimming logger; this runs every session forever."""

    def __init__(self, path):
        self.path = path

    def __call__(self, message):
        stamp = time.strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(self.path, 'a') as f:
                f.write('%s  %s\n' % (stamp, message))
            self.trim()
        except Exception:
            pass

    def trim(self):
        try:
            with open(self.path) as f:
                lines = f.readlines()
            if len(lines) > LOG_LINES_KEPT * 2:
                with open(self.path, 'w') as f:
                    f.writelines(lines[-LOG_LINES_KEPT:])
        except Exception:
            pass


def read_positions(stat):
    """Return joint positions, or None if the machine is not fully homed."""
    stat.poll()
    count = stat.joints or 0
    if not count:
        return None
    if not all(stat.homed[n] for n in range(count)):
        return None
    return [stat.joint_actual_position[n] for n in range(count)]


def same(a, b, tol):
    if a is None or b is None or len(a) != len(b):
        return False
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def write_ini(path, positions):
    """Rewrite HOME/HOME_OFFSET inside each [JOINT_n] section, in place.

    Line-based on purpose: configparser would strip the comments and layout that
    make this INI readable.
    """
    with open(path) as f:
        lines = f.readlines()

    section = None
    out = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
        if section and section.startswith('JOINT_'):
            try:
                joint = int(section.split('_', 1)[1])
            except ValueError:
                joint = None
            if joint is not None and joint < len(positions):
                key = stripped.split('=', 1)[0].strip() if '=' in stripped else ''
                if key in ('HOME', 'HOME_OFFSET'):
                    out.append('{} = {:.3f}\n'.format(key, positions[joint]))
                    continue
        out.append(line)

    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        f.writelines(out)
    os.replace(tmp, path)      # atomic: a crash mid-write cannot truncate the INI


def main():
    ini_path = find_ini()
    if not ini_path or not os.path.isfile(ini_path):
        print('save_position: cannot locate INI file', file=sys.stderr)
        return 1

    log = Log(os.path.join(os.path.dirname(os.path.abspath(ini_path)),
                           'save_position.log'))
    log('started, watching %s' % ini_path)

    stat = None
    previous = None
    saved = None
    still = 0
    last_write = 0.0
    failures = 0
    announced_homed = False
    announced_unhomed = False

    while True:
        time.sleep(POLL_SECONDS)

        # Build the status channel lazily and keep retrying: at DELAY seconds
        # into startup LinuxCNC may not be answering NML yet.
        if stat is None:
            try:
                stat = linuxcnc.stat()
            except Exception as err:
                failures += 1
                if failures == 1:
                    log('waiting for LinuxCNC: %s' % err)
                if failures >= GIVE_UP_AFTER:
                    log('giving up after %d attempts, exiting' % failures)
                    return 1
                continue

        try:
            current = read_positions(stat)
        except Exception as err:
            failures += 1
            if failures == 1:
                log('poll failed: %s' % err)
            if failures >= GIVE_UP_AFTER:
                log('LinuxCNC gone (%d failed polls), exiting' % failures)
                return 0
            continue

        failures = 0

        if current is None:
            if not announced_unhomed:
                log('not homed yet; nothing to save until HOME ALL')
                announced_unhomed = True
                announced_homed = False
            previous = None
            still = 0
            continue

        if not announced_homed:
            log('homed, tracking: ' + ' '.join('%.3f' % p for p in current))
            announced_homed = True
            announced_unhomed = False

        still = still + 1 if same(current, previous, 0.001) else 0
        previous = current

        if still < IDLE_POLLS:
            continue
        if same(current, saved, MIN_CHANGE):
            continue
        if time.time() - last_write < MIN_WRITE_INTERVAL:
            continue

        try:
            write_ini(ini_path, current)
        except Exception as err:
            log('write failed: %s' % err)
            continue

        saved = current
        last_write = time.time()
        log('saved ' + ' '.join('%.3f' % p for p in current))


if __name__ == '__main__':
    sys.exit(main())
