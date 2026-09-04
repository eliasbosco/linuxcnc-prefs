#!/usr/bin/env python3
"""
RESUME CUT - rebuild the remainder of a job that stopped part way through.

Use it after a power cut, a crashed or killed GUI, an aborted cycle, a lost arc,
or a job that was paused and abandoned. cut_recorder.py has been writing the
line number, a copy of the program the interpreter was actually running, and
the work offset to resume/ the whole time; this reads that back and writes a new
program containing only the part that was not cut.

WHAT IT PRODUCES
----------------
RESUME_LAST_CUT.ngc, in the directory the last job was loaded from. Open it and
press CYCLE START. It is a normal program: the preview shows exactly what is
left to cut, so the placement can be checked on the plate before the torch
fires.

The remainder is built with plasmac.run_from_line, which is the same module the
GUI's own RUN FROM LINE button uses. That matters more than it looks: turning
"line 4137 of a filtered file" into a runnable program means re-establishing
G20/G21, G40/G41.1, G64, G90/G91, the M52/M62-M65/M67 torch, THC and velocity
flags, the material change (M190 / M66 P3), the cut feed rate, the last
commanded XY, and the M03 $0 that starts the arc. Getting one of those wrong is
a torch firing at the wrong height or a THC diving into the plate. Reusing
QtPlasmaC's own implementation means the resumed program is assembled exactly
the way the GUI would assemble it, and keeps working when QtPlasmaC changes.

The resume starts at the BEGINNING of the line that was executing, so the last
partly cut segment is cut again from its start. That overlap is deliberate: it
gives the new pierce a bit of already-open kerf to join onto.

THE PROGRAM IS NORMALISED FIRST
-------------------------------
run_from_line reads the program as text and only recognises the canonical
spelling: "G01", "G02", "M03 $0", "X598.409". A job that reaches the
interpreter without going through [FILTER] keeps whatever spelling it was
written with, and on this machine that is dxf2ngc.py's column-aligned "G1 X
598.409 ... M3 $0 S1" - a DXF loaded with the DXF button, or a program handed
over by pick_shape.py, is opened with command.program_open() and never sees
qtplasmac_gcode. Neither run_from_line_get() nor run_from_line_set() reports
that it could not read such a line. It simply omits the "G00 X.. Y.." that
positions the torch and the "M03 $0 S1" that lights it, and the resumed program
then flies over the remaining shapes with the torch off.

So the recorded program is normalised into a scratch copy before run_from_line
sees it: axis words are closed up and G and M codes are zero padded, exactly as
qtplasmac_gcode's parse_code() would have done. The substitution is per line
and changes no line count, so the recorded line number still refers to the same
line.

WAS THE TORCH ON WHEN IT STOPPED?
---------------------------------
run_from_line_set() emits its M03 immediately after positioning at the last
commanded XY, which is right when the job stopped mid-cut - that XY is on the
cut line - and wrong when it stopped while travelling between shapes, where
that XY is the END OF THE PREVIOUS SHAPE. Firing there and then letting the
program's own travel move run would drag a lit arc across the plate to the next
pierce point. The torch state at the recorded line is therefore worked out from
the M03/M05 pairs ahead of it, and when the torch was off the early M03 is
dropped: the program's own M03 fires at the right place a few lines later.

WHY THE OFFSET HAS TO BE PUT BACK BY HAND
-----------------------------------------
LinuxCNC writes linuxcnc.var from its parameter table when milltask exits. A
power cut never gets there, so G54 comes back holding whatever it was at the
START of the last clean session and the touch-off done for this job is gone.
The recorded offset is compared with the live one and, if it differs, this
script offers to put it back with G10 L2 by MDI - before the file is loaded, so
the preview is drawn in the right place.

BEFORE PRESSING CYCLE START
---------------------------
Nothing here can know whether the plate moved, so check by eye that the preview
lands where the remaining cut belongs. After an outage also check the
consumables: the torch sat in the puddle with no post-flow.

Wired to a user button in cnc_plasma_cutter.prefs [BUTTONS] as
"%/home/pi/linuxcnc/configs/cnc_plasma_cutter/resume_cut.py". The handler
Popen()s that without reading stdout, so everything here goes to resume_cut.log
instead: a chatty script would eventually block on a full pipe.
"""

import os
import re
import shutil
import sys
import tempfile
import time

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
RESUME_DIR = os.path.join(CONFIG_DIR, 'resume')
INI = os.path.join(CONFIG_DIR, 'cnc_plasma_cutter.ini')
QTVCP_PREFS = os.path.join(CONFIG_DIR, 'qtvcp.prefs')
LOG_PATH = os.path.join(CONFIG_DIR, 'resume_cut.log')

# Written by cut_recorder.py. interrupted_* is its snapshot of a record that was
# still marked "running" when it started, i.e. a session that died; live_* is
# the current session's record.
CANDIDATES = [
    ('interrupted_state', 'interrupted_program.ngc'),
    ('live_state', 'live_program.ngc'),
]

# One dot only: qtvcp refuses to open a file whose basename has more than one,
# because LinuxCNC cannot.
OUTPUT_NAME = 'RESUME_LAST_CUT.ngc'

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


# ---------------------------------------------------------------- the record

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


def triple(fields, key):
    try:
        parts = fields.get(key, '').split()
        return [float(p) for p in parts[:3]] + [0.0] * max(0, 3 - len(parts))
    except ValueError:
        return [0.0, 0.0, 0.0]


def find_candidate():
    """The newest usable record, with the program copy that goes with it.

    Newest wins rather than "interrupted first": once a resumed job has been
    cut, its own record is the interesting one, and the held snapshot is only
    there so that a probe test after the outage cannot destroy the crash
    record.
    """
    found = []
    for state_name, program_name in CANDIDATES:
        state = os.path.join(RESUME_DIR, state_name)
        program = os.path.join(RESUME_DIR, program_name)
        record = read_record(state)
        if not record or not os.path.isfile(program):
            continue
        record['_state_file'] = state
        record['_program'] = program
        record['_written'] = record.get('written', '')
        found.append(record)
    if not found:
        return None
    found.sort(key=lambda r: r['_written'], reverse=True)
    return found[0]


# ---------------------------------------------------------------- g-code text
#
# The one place on this machine that knows what canonical g-code text looks
# like. pick_shape.py imports all of it; custom_filter.py keeps its own copy of
# PADDED_WORD because the filter exec()s that file into a method's local scope
# and it cannot import anything that is not already there.

# A G or M code at a code position: not part of a longer number and not inside
# a parameter name.
TORCH_ON = re.compile(r'(?<![A-Z0-9_.<#])M0*3(?![0-9])')
TORCH_OFF = re.compile(r'(?<![A-Z0-9_.<#])M0*5(?![0-9])')
# Whitespace between a word letter and its value, as custom_filter.py removes
# it. '$' is deliberately outside the lookahead, which is what leaves plasmac's
# "M03 $0 S1" tool syntax alone.
PADDED_WORD = re.compile(r'(?<![A-Z0-9_.<#])([A-Z])[ \t]+(?=[-+.0-9])')
# A single digit G or M code: "G1", "M3". The lookahead keeps "G91.1" and
# "M190" out of it - only a code that is genuinely one digit long is padded.
PADDED_CODE = re.compile(r'(?<![A-Z0-9_.<#])([GM])([0-9])(?![0-9.])')
# qtplasmac_gcode's illegal_character() rewrites a line it will not accept as
# ";<the original line> |<what was wrong with it>". The tail is what this
# matches: a ';' comment with a ' |' in it.
ANNOTATION = re.compile(r'^(\s*;.*?)\s\|[^|]*$')
# A balanced inline comment. g-code resumes after the ')'.
INLINE_COMMENT = re.compile(r'\([^)]*\)')


def code_only(line):
    """Everything on the line the interpreter will execute.

    Not the same question as split_comment()'s. That one cuts at the first
    comment character, which is what a rewrite wants - anything past it is
    left alone - but g-code resumes after a closing ')', so "G64 P0.25 (path
    tolerance) G17" carries a live G17 that split_comment() hands back as part
    of the comment.
    """
    return INLINE_COMMENT.sub(' ', line).split(';')[0]


def split_comment(line):
    """Split a line into its code and its trailing comment, at whichever
    comment character comes first."""
    cut = len(line)
    for tag in ';(':
        found = line.find(tag)
        if found != -1:
            cut = min(cut, found)
    return line[:cut], line[cut:]


def normalised_copy(path, prefix='resume_cut-'):
    """A copy of the program in the spelling run_from_line can read.

    Axis words are closed up ("X 598.409" -> "X598.409") and single digit G and
    M codes are zero padded ("G1" -> "G01", "M3 $0" -> "M03 $0"), which is what
    qtplasmac_gcode's parse_code() does to everything that goes through
    [FILTER]. run_from_line matches on those exact strings and says nothing
    when it fails to match, so a program that skipped the filter has to be put
    into the same shape before it is handed over.

    The other direction is undone as well: qtplasmac_gcode's
    illegal_character() comments out a line it will not accept and appends
    "|<what was wrong with it>", and that annotation must not survive into a
    generated program. run_from_line_get() picks the G6x line out with
    "line.split('G64')[1]", which throws away everything to the left of the
    G64 - the ';' that made it a comment included - so a resume built from a
    filtered file puts the '|' back into live code and LinuxCNC refuses the
    file with "bad character '\\174' used". The annotation is therefore
    stripped here, leaving the line the plain comment it was before the filter
    got to it.

    Returns (copy_path, changed_lines). Only the code half of a line is
    touched, and one line in gives one line out, so every line number still
    refers to the same line of the file the operator is looking at.

    The copy lives in a temp directory that is left behind on purpose: when a
    generated program turns out wrong, the exact input run_from_line was given
    is the first thing worth looking at, and the log names it.
    """
    directory = tempfile.mkdtemp(prefix=prefix)
    copy = os.path.join(directory, os.path.basename(path))
    changed = 0
    with open(path) as source, open(copy, 'w') as target:
        for raw in source:
            # Split the line ending off and put it back untouched, so a file
            # whose last line has none keeps it that way and the line count is
            # exactly what it was.
            line = raw.rstrip('\n')
            ending = raw[len(line):]
            code, comment = split_comment(line)
            fixed = PADDED_CODE.sub(r'\g<1>0\g<2>', PADDED_WORD.sub(r'\1', code))
            fixed += ANNOTATION.sub(r'\1', comment)
            if fixed != line:
                changed += 1
            target.write(fixed + ending)
    return copy, changed


def torch_was_on(path, start_line):
    """Was the torch lit when the machine reached start_line (1-based)?

    The M03/M05 pairs ahead of the line say so, and nothing else does: the
    recorded Z only says the torch was down, which it also is while the THC
    holds height between two cuts of the same shape, and the recorded line
    number is the only thing that survives a power cut anyway.

    run_from_line_set() uses this to decide whether its own M03 belongs at the
    resume point - see the header. A file that cannot be read counts as "on",
    the answer that keeps the pierce where run_from_line would have put it.
    """
    lit = False
    try:
        with open(path) as f:
            for number, line in enumerate(f, 1):
                if number >= start_line:
                    break
                code = split_comment(line)[0]
                if TORCH_ON.search(code):
                    lit = True
                elif TORCH_OFF.search(code):
                    lit = False
    except Exception:
        return True
    return lit


def collapse_repeated_torch_on(path):
    """Drop a torch-on that immediately repeats the one before it.

    run_from_line_set() emits the resume point's M03 itself and can then copy
    the same line again out of postData, when the line it starts from is the
    M03 of the next shape. Firing an already lit torch is harmless, but a
    duplicate in a generated program is the kind of thing that gets read as a
    bug later.
    """
    with open(path) as f:
        lines = f.readlines()
    out, previous = [], None
    for raw in lines:
        code = split_comment(raw)[0].replace(' ', '')
        if TORCH_ON.search(code) and code == previous:
            continue
        out.append(raw)
        previous = code if code.strip() else previous
    if len(out) != len(lines):
        with open(path, 'w') as f:
            f.writelines(out)
    return len(lines) - len(out)


# ---------------------------------------------------------------- machine

def machine_state():
    """(stat, blocker, limitation).

    Only one thing genuinely blocks: a program already running, because the
    recorder would be overwriting the record this script is trying to read.
    Being unpowered or unhomed does not block. Writing the resume file is a
    read-only operation on a recording, and it is useful to be able to look at
    what a resume would contain before touching the machine - the operator may
    well want to check the line number against the plate first. Those states do
    prevent the G10 L2 offset restore, so they come back as a limitation and
    that half is skipped.
    """
    try:
        import linuxcnc
    except Exception as err:
        return None, 'linuxcnc module unavailable: %s' % err, None
    try:
        stat = linuxcnc.stat()
        stat.poll()
    except Exception as err:
        return None, 'LinuxCNC is not running: %s' % err, None

    if stat.interp_state != linuxcnc.INTERP_IDLE:
        return stat, 'a program is running - stop it first', None
    if stat.estop:
        return stat, None, 'the machine is in E-stop'
    if not stat.enabled:
        return stat, None, 'the machine is not powered on'
    count = stat.joints or 0
    if not count or not all(stat.homed[n] for n in range(count)):
        return stat, None, 'the machine is not homed'
    return stat, None, None


def restore_offset(index, wanted, rotation):
    """Put the recorded work offset back with G10 L2, by MDI.

    Done here rather than as a line at the top of the generated program so that
    the preview is already drawn in the right place when the operator checks it
    against the plate.
    """
    import linuxcnc
    cmd = linuxcnc.command()
    stat = linuxcnc.stat()
    stat.poll()
    entry_mode = stat.task_mode

    words = 'G10 L2 P%d X%.6f Y%.6f Z%.6f R%.6f' % (
        index, wanted[0], wanted[1], wanted[2], rotation)
    log('restoring offset by MDI: %s' % words)
    cmd.mode(linuxcnc.MODE_MDI)
    cmd.wait_complete(5)
    cmd.mdi(words)
    cmd.wait_complete(10)
    # Hand the GUI back the mode it was in; QtPlasmaC follows task_mode, so
    # leaving it in MDI would leave the jog buttons looking wrong.
    if entry_mode and entry_mode != linuxcnc.MODE_MDI:
        cmd.mode(entry_mode)
        cmd.wait_complete(5)
    return words


# ---------------------------------------------------------------- output path

def output_directory():
    """Where the operator will look for the file: the directory the last job
    came from, then [DISPLAY] PROGRAM_PREFIX, then here."""
    import configparser
    for path, key, section in ((QTVCP_PREFS, 'last_loaded_directory', 'BOOK_KEEPING'),
                               (INI, 'PROGRAM_PREFIX', 'DISPLAY')):
        try:
            # strict=False: the INI repeats keys (POSITION_FEEDBACK, APP,
            # PROGRAM_EXTENSION). interpolation=None: a '%' in any value would
            # otherwise raise, and this is only ever a read.
            parser = configparser.ConfigParser(strict=False, interpolation=None)
            parser.read(path)
            value = parser.get(section, key, fallback='').strip()
            if value and os.path.isdir(value):
                return value
        except Exception:
            continue
    return CONFIG_DIR


# ---------------------------------------------------------------- operator

def describe(record):
    line = int(float(record.get('line', 0) or 0))
    total = int(float(record.get('program_lines', 0) or 0))
    percent = ' (%.0f%%)' % (100.0 * line / total) if total else ''

    if record.get('state') == 'running':
        how = 'The session DIED while this was cutting.'
    elif record.get('at_end') == 'yes':
        how = ('This job appears to have RUN TO THE END - there may be\n'
               'nothing left to cut.')
    else:
        how = 'This job was stopped part way through.'

    where = record.get('position', '').split()
    at = ('    stopped near  X %s  Y %s\n' % (where[0], where[1])
          if len(where) >= 2 else '')

    joints = record.get('joints', '').split()
    torch = ''
    if len(joints) >= 3:
        try:
            if float(joints[2]) < -1.0:
                torch = ('    the torch was DOWN at Z %s when it stopped\n'
                         % joints[2])
        except ValueError:
            pass

    return (
        '%s\n\n'
        '    program       %s\n'
        '    stopped at    line %d of %d%s\n'
        '    recorded      %s\n'
        '%s%s'
        % (how, record.get('program', '?'), line, total, percent,
           record.get('written', '?'), at, torch)
    )


def offset_difference(record, stat):
    """(needs_restore, text). Compares the recorded work offset with the live
    one; only the axes this machine has are worth reporting."""
    wanted = triple(record, 'g5x_offset')
    live = [stat.g5x_offset[0], stat.g5x_offset[1], stat.g5x_offset[2]]
    try:
        rotation = float(record.get('rotation_xy', 0.0))
    except ValueError:
        rotation = 0.0
    differs = (any(abs(a - b) > 0.001 for a, b in zip(wanted, live))
               or abs(rotation - stat.rotation_xy) > 0.001)
    if not differs:
        return False, '    work offset   unchanged, nothing to restore\n'
    text = ('    work offset   G5%d differs from the recording\n'
            '                    now      X %.3f  Y %.3f  Z %.3f\n'
            '                    recorded X %.3f  Y %.3f  Z %.3f\n'
            % (int(record.get('g5x_index', 1)) + 3,
               live[0], live[1], live[2], wanted[0], wanted[1], wanted[2]))
    return True, text


def ask(record, stat, offset_text, offer_offset):
    """Modal form. Returns None to cancel, else the chosen options.

    Tk rather than Qt to keep a second Qt application out of the GUI's process
    tree, as set_zero_here.py does. The QtPlasmaC handler Popen()s this script
    without waiting, so blocking here does not freeze the GUI.
    """
    import tkinter as tk

    result = {}
    root = tk.Tk()
    root.title('RESUME CUT')
    root.attributes('-topmost', True)

    body = describe(record) + offset_text
    tk.Label(root, text=body, justify='left', font='TkFixedFont',
             anchor='w').pack(padx=16, pady=(16, 8), fill='x')

    do_offset = tk.BooleanVar(value=offer_offset)
    if offer_offset:
        tk.Checkbutton(root, text='Restore the recorded work offset (G10 L2)',
                       variable=do_offset, anchor='w').pack(padx=16, fill='x')

    do_leadin = tk.BooleanVar(value=False)
    leadin_length = tk.StringVar(value='4')
    leadin_angle = tk.StringVar(value='0')

    frame = tk.Frame(root)
    frame.pack(padx=16, pady=(4, 8), fill='x')
    tk.Checkbutton(frame, text='Add a leadin to the first pierce',
                   variable=do_leadin, anchor='w').grid(row=0, column=0,
                                                        columnspan=4, sticky='w')
    tk.Label(frame, text='length mm').grid(row=1, column=0, sticky='e')
    tk.Entry(frame, textvariable=leadin_length, width=6).grid(row=1, column=1)
    tk.Label(frame, text='angle deg').grid(row=1, column=2, sticky='e')
    tk.Entry(frame, textvariable=leadin_angle, width=6).grid(row=1, column=3)

    tk.Label(root, justify='left', anchor='w', wraplength=520, fg='#804000',
             text=('Off by default: the resume pierces on the cut line, where '
                   'the kerf just behind it is already open. A leadin moves '
                   'that pierce off the line, which is only right if the '
                   'material on that side is scrap.')
             ).pack(padx=16, pady=(0, 10), fill='x')

    tk.Label(root, justify='left', anchor='w', wraplength=520,
             text=('This only writes a file. Check the preview against the '
                   'plate, and check the consumables, before CYCLE START.')
             ).pack(padx=16, pady=(0, 12), fill='x')

    def go():
        result['do_offset'] = bool(offer_offset and do_offset.get())
        try:
            length = float(leadin_length.get())
            angle = float(leadin_angle.get())
        except ValueError:
            length, angle = 0.0, 0.0
        result['leadin'] = {'do': bool(do_leadin.get()) and length > 0,
                            'length': length, 'angle': angle}
        root.destroy()

    buttons = tk.Frame(root)
    buttons.pack(pady=(0, 16))
    tk.Button(buttons, text='CREATE RESUME FILE', width=22,
              command=go).pack(side='left', padx=8)
    tk.Button(buttons, text='CANCEL', width=12,
              command=root.destroy).pack(side='left', padx=8)

    root.mainloop()
    return result or None


# ---------------------------------------------------------------- safety net

def first_pierce_is_positioned(path):
    """(ok, detail). Is there a positioning move before the first M03?

    A resume that fires the torch without first moving to the start of the cut
    is the worst thing this script could produce: the arc strikes wherever the
    machine was left standing and then travels to the cut, gouging everything
    in between. That is not a hypothetical - it is exactly what
    run_from_line_set() emits when get_rfl_pos() cannot read the coordinates it
    was given, and it emits it silently. custom_filter.py canonicalises axis
    words so get_rfl_pos() can read them, but a generated program is cheap to
    check and the consequence of not checking is a wrecked plate, so check.

    G53 moves do not count: the machine-coordinate Z lift to safe height is
    always there and says nothing about where the torch is in X and Y.
    """
    import re
    motion = re.compile(r'(?<![A-Z0-9_.<#])G0*[0123](?![0-9])')
    positioned = None
    try:
        with open(path) as f:
            for number, line in enumerate(f, 1):
                code = line.split('(')[0].split(';')[0]
                bare = code.replace(' ', '')
                if 'M03' in bare or 'M3$' in bare:
                    if positioned:
                        return True, 'positioned on line %d' % positioned
                    return False, ('the first M03 is on line %d with no XY '
                                   'positioning move before it' % number)
                if 'G53' in bare:
                    continue
                if motion.search(code) and ('X' in code or 'Y' in code):
                    positioned = number
    except Exception as err:
        return False, 'could not be read back: %s' % err
    # No M03 at all: nothing left to cut, which is worth saying rather than
    # letting the operator run an empty program.
    return False, 'it contains no torch-on (M03) at all'


def leaked_annotation(path):
    """(ok, detail). Is there a '|' left in live code?

    '|' is not legal g-code. The only thing that puts one in a file on this
    machine is qtplasmac_gcode's illegal_character(), which comments the line
    out at the same time - so a '|' outside a comment means something
    reassembled that line and dropped the ';'. LinuxCNC's answer is to refuse
    the file with "bad character '\\174' used" at load time, by which point the
    operator has been told the resume is ready. Catch it here instead.
    """
    try:
        with open(path) as f:
            for number, line in enumerate(f, 1):
                if '|' in code_only(line):
                    return False, ("line %d has a '|' in it, which the "
                                   "interpreter will refuse" % number)
    except Exception as err:
        return False, 'could not be read back: %s' % err
    return True, 'no stray annotations'


def notify(title, message):
    try:
        import subprocess
        subprocess.Popen(['notify-send', '-u', 'critical', title, message],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def tell(title, message, icon='info'):
    try:
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showinfo(title, message, icon=icon, parent=root)
        root.destroy()
    except Exception as err:
        log('no dialog available (%s): %s' % (err, message))
    notify(title, message)


# ---------------------------------------------------------------- main

def main():
    log('--- RESUME CUT pressed ---')

    record = find_candidate()
    if not record:
        log('refused: nothing recorded in %s' % RESUME_DIR)
        tell('RESUME CUT',
             'Nothing to resume.\n\n'
             'No job has been recorded yet. cut_recorder.py writes into\n'
             '%s while a program runs; check cut_recorder.log if a job\n'
             'has run since it was installed.' % RESUME_DIR, icon='warning')
        return 1
    log('candidate %s: %s line %s of %s, state=%s, written %s'
        % (os.path.basename(record['_state_file']), record.get('program'),
           record.get('line'), record.get('program_lines'),
           record.get('state'), record.get('written')))

    line = int(float(record.get('line', 0) or 0))
    if line < 2:
        log('refused: recorded line is %d, nothing to resume from' % line)
        tell('RESUME CUT',
             'The recorded line is %d - the job had not started cutting,\n'
             'so there is nothing to resume. Just run the program again.'
             % line, icon='warning')
        return 1

    stat, blocker, limitation = machine_state()
    if blocker:
        log('refused: %s' % blocker)
        tell('RESUME CUT', blocker.capitalize() + '.', icon='warning')
        return 1

    offer_offset, offset_text = offset_difference(record, stat)
    if limitation and offer_offset:
        offer_offset = False
        offset_text += ('                  cannot be restored from here:\n'
                        '                    %s\n' % limitation)
        log('offset restore not offered: %s' % limitation)
    g92 = triple(record, 'g92_offset')
    if any(abs(v) > 0.001 for v in g92):
        offset_text += ('    WARNING       a G92 offset was active and is NOT\n'
                        '                    restored: X %.3f Y %.3f Z %.3f\n'
                        % tuple(g92))
        log('recorded G92 offset is non-zero and will not be restored: %s' % g92)

    choice = ask(record, stat, offset_text, offer_offset)
    if not choice:
        log('operator cancelled')
        return 0

    # Build the remainder with QtPlasmaC's own run-from-line implementation, so
    # the assembled program matches what the GUI's RUN FROM LINE button makes.
    try:
        from plasmac import run_from_line as RFL
    except Exception as err:
        log('cannot import plasmac.run_from_line: %s' % err)
        tell('RESUME CUT', 'Cannot load QtPlasmaC\'s run_from_line module:\n%s'
             % err, icon='error')
        return 1

    # run_from_line only recognises canonical g-code text, and the recorded
    # program is whatever the interpreter was handed - see the header.
    source, changed = normalised_copy(record['_program'])
    log('normalised copy %s (%d of %s lines rewritten)'
        % (source, changed, record.get('program_lines', '?')))

    # run_from_line_get counts from zero; the recorded line is the 1-based line
    # the motion controller was on, and resuming at the START of that line is
    # what gives the overlap onto the interrupted cut.
    start_line = line - 1
    data = RFL.run_from_line_get(source, start_line)
    if data.get('error'):
        if data.get('compError'):
            why = ('cutter compensation (G41/G42) is active at that point.\n'
                   'A resume cannot be built through it.')
        else:
            why = ('that line is inside a subroutine (%s).\n'
                   'A resume cannot be built from inside one.'
                   % ' '.join(data.get('subError') or []))
        log('run_from_line_get refused: %s' % why.replace('\n', ' '))
        tell('RESUME CUT', 'Cannot resume from line %d:\n\n%s' % (line, why),
             icon='error')
        return 1

    try:
        units_per_mm = float(record.get('units_per_mm', 1))
    except ValueError:
        units_per_mm = 1.0

    out_dir = output_directory()
    out_path = os.path.join(out_dir, OUTPUT_NAME)
    # Keep the previous one: a resume that turns out to have started at the
    # wrong place is easier to reason about with the last attempt still on disk.
    if os.path.isfile(out_path):
        try:
            shutil.copyfile(out_path, out_path + '.prev')
        except Exception:
            pass

    # Only pierce at the resume point if the torch was actually cutting there.
    # Stopped between shapes, the last commanded XY is the end of the previous
    # shape, and an M03 there would light the arc and then drag it across the
    # plate on the program's own travel move to the next pierce point.
    lit = torch_was_on(source, line)
    torch_note = ''
    if not lit:
        data['codes']['spindle']['line'] = None
        torch_note = ('\nThe torch was NOT cutting at line %d - it had finished a\n'
                      'shape and was travelling. The resume starts with the\n'
                      'travel move and pierces where the program says.\n' % line)
        log('torch was off at line %d: no pierce added at the resume point'
            % line)
    else:
        log('torch was on at line %d: pierce added at the resume point' % line)

    result = RFL.run_from_line_set(out_path, data, choice['leadin'], units_per_mm)
    dropped = collapse_repeated_torch_on(out_path)
    if dropped:
        log('dropped %d duplicated torch-on line(s)' % dropped)
    leadin_note = ''
    if choice['leadin']['do'] and result.get('error'):
        leadin_note = ('\nThe leadin could not be calculated for this cut, so\n'
                       'the file was written without one.\n')
        log('leadin could not be calculated; written without one')
    elif choice['leadin']['do']:
        leadin_note = ('\nLeadin: %g mm at %g deg.\n'
                       % (choice['leadin']['length'], choice['leadin']['angle']))
    log('wrote %s from line %d' % (out_path, line))

    ok, detail = leaked_annotation(out_path)
    log('annotation check: %s (%s)' % ('ok' if ok else 'FAILED', detail))
    if not ok:
        tell('RESUME CUT',
             'REFUSING TO OFFER THIS RESUME FILE.\n\n'
             'The generated program %s. LinuxCNC would\n'
             'refuse to load it. The file is at\n\n  %s\n\nfor inspection.\n\n'
             'See resume_cut.log.' % (detail, out_path), icon='error')
        return 1

    ok, detail = first_pierce_is_positioned(out_path)
    log('pierce check: %s (%s)' % ('ok' if ok else 'FAILED', detail))
    if not ok:
        tell('RESUME CUT',
             'REFUSING TO OFFER THIS RESUME FILE.\n\n'
             'The generated program was checked and %s.\n\n'
             'Running it would strike the arc wherever the machine is\n'
             'standing now and then drag it to the cut. The file is still\n'
             'at\n\n  %s\n\nfor inspection, but do not run it as it is.\n\n'
             'See resume_cut.log.' % (detail, out_path), icon='error')
        return 1

    offset_note = ''
    if choice['do_offset']:
        try:
            wanted = triple(record, 'g5x_offset')
            rotation = float(record.get('rotation_xy', 0.0))
            index = int(record.get('g5x_index', 1))
            words = restore_offset(index, wanted, rotation)
            offset_note = '\nWork offset restored:\n  %s\n' % words
        except Exception as err:
            log('offset restore failed: %s' % err)
            offset_note = ('\nTHE WORK OFFSET WAS NOT RESTORED: %s\n'
                           'Set it by hand on the offsets page before running.\n'
                           % err)

    tell('RESUME CUT',
         'Resume file written:\n\n'
         '  %s\n\n'
         'It starts at line %d of %s and runs to the end.\n'
         '%s%s%s\n'
         'Open it with the file button, CHECK THE PREVIEW LANDS WHERE THE\n'
         'REMAINING CUT BELONGS, check the consumables, then CYCLE START.'
         % (out_path, line, record.get('program', '?'),
            torch_note, offset_note, leadin_note))
    return 0


if __name__ == '__main__':
    sys.exit(main())
