#!/usr/bin/env python3
"""
CUT RECORDER - leave enough on the SD card to restart an interrupted job.

WHY THIS EXISTS
---------------
Pulling the plug in the middle of a cut destroys three things at once, and all
three are needed to pick the job back up:

  1. WHERE IN THE PROGRAM the machine was. LinuxCNC keeps the executing line
     number in RAM only.

  2. THE PROGRAM AS THE INTERPRETER SAW IT. QtPlasmaC never runs the file that
     was opened. Every .ngc goes through qtplasmac_gcode ([FILTER] ngc in the
     INI), and milltask loads the filter's OUTPUT from a temp directory that
     qtvcp makes with tempfile.mkdtemp() under /tmp. /tmp is tmpfs on this Pi,
     and qtvcp removes the directory on exit anyway, so that file is gone after
     a reboot. A line number only means something against that exact file, so
     without a copy of it the line number is worthless. (Line 1 of the original
     is not line 1 of the filtered version: the filter adds a marker comment, a
     preamble, material changes and per-cut Z moves.)

  3. THE WORK OFFSET. LinuxCNC writes linuxcnc.var from its parameter table
     when milltask exits. Pull the plug and that write never happens, so G54
     comes back as whatever it was at the START of the last clean session - the
     touch-off done for this job is lost.

This daemon writes all three to the SD card while a job runs. resume_cut.py
reads them back and rebuilds the remainder of the job.

WHAT IT DOES NOT DO
-------------------
It does not record the machine's physical position - save_position.py already
keeps that in the [JOINT_n] HOME/HOME_OFFSET values, and after the fsync fix in
that file it keeps doing so while the machine is moving, which is what makes Z
truthful after an outage. The two daemons are deliberately separate: one owns
the INI, this one owns the resume/ directory, and neither can corrupt the
other's file.

It only watches AUTO. Probing, framing, torch pulse and the user buttons all
run as MDI and are not jobs to resume.

DURABILITY
----------
Every record is written to a temp file, fsynced, renamed over the real one, and
then the DIRECTORY is fsynced as well. Without the last step a power cut can
leave the directory entry still pointing at the old inode even though the new
data reached the card. The rename means a reader always sees one whole record,
never half of one.

Writes are rate limited to WRITE_INTERVAL. The cost of that interval is how
much of the cut gets re-run: a resume restarts at the beginning of the recorded
line, so at the 1000 mm/min this machine travels at, 0.5 s is under 10 mm of
overlap, and overlap on a resumed plasma cut is wanted, not a problem.

Started from the INI:  [APPLICATIONS] APP = ./cut_recorder.py
Can also be run by hand from the config directory for debugging.

Progress and errors go to cut_recorder.log beside the INI, because anything
printed to stdout is lost when LinuxCNC is started from a desktop icon.
"""

import glob
import os
import shutil
import sys
import time

import linuxcnc

POLL_SECONDS = 0.25
WRITE_INTERVAL = 0.5        # seconds; floor between records while cutting
HEARTBEAT_INTERVAL = 5.0    # seconds; write even if the line has not changed
GIVE_UP_AFTER = 240         # consecutive failed polls before deciding we are done
LOG_LINES_KEPT = 200

RECORD_VERSION = 1

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
RESUME_DIR = os.path.join(CONFIG_DIR, 'resume')

LIVE_STATE = os.path.join(RESUME_DIR, 'live_state')
LIVE_PROGRAM = os.path.join(RESUME_DIR, 'live_program.ngc')
# Snapshot of a record that was still marked "running" when this daemon
# started, i.e. the previous session died without stopping. Kept aside so that
# probing or a test cut after the outage cannot overwrite the only copy of
# where the real job stopped.
HELD_STATE = os.path.join(RESUME_DIR, 'interrupted_state')
HELD_PROGRAM = os.path.join(RESUME_DIR, 'interrupted_program.ngc')


def find_ini():
    if len(sys.argv) > 1:
        return sys.argv[1]
    if os.environ.get('INI_FILE_NAME'):
        return os.environ['INI_FILE_NAME']
    candidates = sorted(glob.glob(os.path.join(CONFIG_DIR, '*.ini')))
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


# ---------------------------------------------------------------- durability

def fsync_dir(path):
    """Force a rename to reach the card, not just the new file's data."""
    fd = os.open(path or '.', os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def durable_write(path, text):
    """Write text so that a power cut leaves either the old file or the new
    one, never a truncated mixture, and so that "the new one" really is on the
    card rather than sitting in the page cache."""
    tmp = path + '.tmp'
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        os.write(fd, text.encode('utf-8'))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(path))


def durable_copy(src, dest):
    shutil.copyfile(src, dest + '.tmp')
    fd = os.open(dest + '.tmp', os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(dest + '.tmp', dest)
    fsync_dir(os.path.dirname(dest))


# ---------------------------------------------------------------- the record

def format_record(fields):
    """key = value lines, sorted, so the file can just be cat'd at the machine."""
    return ''.join('%s = %s\n' % (k, fields[k]) for k in sorted(fields))


def read_record(path):
    fields = {}
    try:
        with open(path) as f:
            for line in f:
                if '=' in line:
                    key, value = line.split('=', 1)
                    fields[key.strip()] = value.strip()
    except Exception:
        return None
    return fields or None


def count_lines(path):
    try:
        with open(path, 'rb') as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


# ---------------------------------------------------------------- collection

def is_running(stat):
    """A job worth recording: AUTO with the interpreter still holding the file.

    PAUSED counts. A job left paused when the GUI is closed is exactly as
    interrupted as one killed by a power cut, and is resumed the same way.
    """
    return (stat.task_mode == linuxcnc.MODE_AUTO
            and stat.interp_state != linuxcnc.INTERP_IDLE)


def executing_line(stat):
    """The line the MOTION controller is on, not the one the interpreter has
    read. They differ by the whole lookahead queue - hundreds of lines on a
    plasma job - and it is the moving one that says where the torch is."""
    return stat.motion_line or stat.current_line or 0


def collect(stat, program_lines):
    joints = [stat.joint_actual_position[n] for n in range(stat.joints or 0)]
    g5x = list(stat.g5x_offset)
    g92 = list(stat.g92_offset)
    return {
        'version': RECORD_VERSION,
        'state': 'running',
        'written': time.strftime('%Y-%m-%d %H:%M:%S'),
        'program': os.path.basename(stat.file),
        'program_source': stat.file,
        'program_lines': program_lines,
        'line': executing_line(stat),
        'paused': 'yes' if stat.paused else 'no',
        'joints': ' '.join('%.3f' % p for p in joints),
        'position': '%.3f %.3f %.3f' % (stat.position[0], stat.position[1],
                                        stat.position[2]),
        'g5x_index': stat.g5x_index,
        'g5x_offset': '%.6f %.6f %.6f' % (g5x[0], g5x[1], g5x[2]),
        'g92_offset': '%.6f %.6f %.6f' % (g92[0], g92[1], g92[2]),
        'rotation_xy': '%.6f' % stat.rotation_xy,
        'units_per_mm': '1' if stat.linear_units == 1.0 else '0.03937',
    }


# ---------------------------------------------------------------- main

def hold_interrupted_record(log):
    """If the last session left a record marked running, it died mid-job.

    Preserve it under the interrupted_* names before this session is allowed to
    write over live_*, so that a probe test or a second job after the outage
    cannot destroy the only copy of where the real cut stopped.
    """
    previous = read_record(LIVE_STATE)
    if not previous or previous.get('state') != 'running':
        return
    try:
        durable_copy(LIVE_STATE, HELD_STATE)
        if os.path.isfile(LIVE_PROGRAM):
            durable_copy(LIVE_PROGRAM, HELD_PROGRAM)
        log('previous session died mid-job (%s line %s) - held as %s'
            % (previous.get('program', '?'), previous.get('line', '?'),
               os.path.basename(HELD_STATE)))
    except Exception as err:
        log('could not hold the interrupted record: %s' % err)


def main():
    ini_path = find_ini()
    if not ini_path or not os.path.isfile(ini_path):
        print('cut_recorder: cannot locate INI file', file=sys.stderr)
        return 1

    os.makedirs(RESUME_DIR, exist_ok=True)
    log = Log(os.path.join(CONFIG_DIR, 'cut_recorder.log'))
    log('started, recording into %s' % RESUME_DIR)
    hold_interrupted_record(log)

    stat = None
    failures = 0

    was_running = False
    copied_source = None
    program_lines = 0
    last_line = None
    last_write = 0.0
    last_record = None
    announced_wait = False

    while True:
        time.sleep(POLL_SECONDS)

        # Build the status channel lazily and keep retrying: at DELAY seconds
        # into startup LinuxCNC may not be answering NML yet.
        if stat is None:
            try:
                stat = linuxcnc.stat()
            except Exception as err:
                failures += 1
                if not announced_wait:
                    log('waiting for LinuxCNC: %s' % err)
                    announced_wait = True
                if failures >= GIVE_UP_AFTER:
                    log('giving up after %d attempts, exiting' % failures)
                    return 1
                continue

        try:
            stat.poll()
        except Exception as err:
            failures += 1
            if failures == 1:
                log('poll failed: %s' % err)
            if failures >= GIVE_UP_AFTER:
                log('LinuxCNC gone (%d failed polls), exiting' % failures)
                return 0
            continue
        failures = 0

        if not is_running(stat):
            if was_running and last_record:
                # Mark the run over. Anything still saying "running" on disk is
                # by definition a session that died, so this line is what keeps
                # a clean stop from being offered as a crash next time.
                final = dict(last_record)
                final['state'] = 'stopped'
                final['written'] = time.strftime('%Y-%m-%d %H:%M:%S')
                final['at_end'] = ('yes' if program_lines
                                   and int(final['line']) >= program_lines - 5
                                   else 'no')
                try:
                    durable_write(LIVE_STATE, format_record(final))
                    log('job stopped at line %s of %d (at_end=%s)'
                        % (final['line'], program_lines, final['at_end']))
                except Exception as err:
                    log('final write failed: %s' % err)
            was_running = False
            last_line = None
            continue

        # The interpreter's file changes when a new program is loaded, and also
        # when QtPlasmaC loads its own rfl.ngc for a run from line. Either way
        # the line numbers now refer to a different file, so take a fresh copy.
        source = stat.file
        if source and source != copied_source:
            try:
                durable_copy(source, LIVE_PROGRAM)
                program_lines = count_lines(LIVE_PROGRAM)
                copied_source = source
                log('copied %s (%d lines)' % (source, program_lines))
            except Exception as err:
                log('could not copy %s: %s' % (source, err))
                # Without the copy a line number cannot be used, so do not
                # pretend otherwise: keep the old copy and stop recording until
                # a later poll succeeds.
                continue

        if not was_running:
            log('job running: %s' % os.path.basename(source or '?'))
            was_running = True

        line = executing_line(stat)
        now = time.time()
        due = (line != last_line and now - last_write >= WRITE_INTERVAL) \
            or now - last_write >= HEARTBEAT_INTERVAL
        if not due:
            continue

        record = collect(stat, program_lines)
        try:
            durable_write(LIVE_STATE, format_record(record))
        except Exception as err:
            log('write failed: %s' % err)
            continue
        last_record = record
        last_line = line
        last_write = now


if __name__ == '__main__':
    sys.exit(main())
