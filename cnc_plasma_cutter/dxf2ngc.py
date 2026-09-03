#!/usr/bin/env python3
"""
DXF -> QtPlasmaC G-code, using the dxf2gcode project.

TWO ENTRY POINTS, ONE FILE:

  dxf2ngc.py                GUI mode, used by the DXF user button. Asks for a
                            DXF, converts it, writes the .ngc beside the DXF
                            and loads it into QtPlasmaC.
                            Wired up in cnc_plasma_cutter.prefs [BUTTONS] as
                            "%<this path>" - the leading % is what makes
                            QtPlasmaC treat a button as an external command.

  dxf2ngc.py FILE.dxf       Filter mode, writes G-code to stdout. This is what
                            LinuxCNC's [FILTER] mechanism wants, so a DXF can
                            also be opened straight from the normal Open
                            dialog. Registered in the ini as "dxf = <path>".

WHY THIS SCRIPT EXISTS AT ALL

dxf2gcode (Debian package dxf2gcode, the sourceforge project) is a MILLING
program. Left alone it emits precisely what a plasma table must never run.
The unmodified output for a plate with one hole was:

    G0 Z  15.000            <- above this machine's Z MAX_LIMIT of 0
    T1 M6 / S6000           <- tool change and spindle speed
    M3 M8 ... M9 M5         <- spindle and coolant, not the torch
    G1 Z  -1.500            <- plunges the torch into the plate
    G1 Z  -3.000            <- ...and again, it does two depth passes

So this script owns four jobs:

  1. It installs a plasma postprocessor into ~/.config/dxf2gcode. That path is
     hardcoded in /usr/bin/dxf2gcode (g.folder), so the config CANNOT live in
     this repo - instead the profile is defined in PLASMA_POSTPRO below and
     applied idempotently on every run. Only the keys listed there are
     touched, so a dxf2gcode upgrade that bumps config_version still works.
     Every Z template is blanked, so no Z word is generated at all (QtPlasmaC
     owns Z via THC), and pre/post shape cut become M3 $0 S1 / M5 $0.

  2. It adds the QtPlasmaC program header, mainly the feed rate. Feed comes
     from #<_hal[plasmac.cut-feed-rate]>, which is the material selected in
     the QtPlasmaC GUI. No M190 is emitted on purpose: hardcoding a material
     would override the operator's choice with someone else's amps and
     pierce height.

  3. It holds travel between shapes to TRAVEL_FEED mm/min, by rewriting each
     G0 as a feed move. Nothing this script produces goes through
     /usr/bin/qtplasmac_gcode, so custom_filter.py - which does the same
     rewrite for every other kind of job - never sees a DXF. Without this, a
     DXF job would be the only kind whose travel still runs at the joint
     limits, which is 1500 mm/min on X and 6000 on Y.

  4. It REFUSES to emit G-code containing a Z move, a tool change or a
     spindle/coolant word. That check is the point of this script, not
     decoration - see the list above for what it is guarding against.

WHAT THIS IS NOT

dxf2gcode is not plasma CAM. There are no lead-ins, no lead-outs and no kerf
compensation, so the torch pierces on the contour itself. Expect a small
divot at each pierce point and a part that is one kerf-width oversize on
inside cuts and undersize on outside cuts. For accurate parts, add lead-ins
in CAD or enable cutter compensation per shape in the dxf2gcode GUI (run
"dxf2gcode" from a terminal to get it).

Anything printed to stdout in GUI mode is lost - QtPlasmaC runs the button
with Popen and never reads the pipe - so progress and errors also go to
dxf2ngc.log beside this script, and to a dialog box.
"""

import os
import re
import subprocess
import sys
import tempfile
import time

CONFIG_HOME = os.path.expanduser('~/.config/dxf2gcode')
POSTPRO_CFG = os.path.join(CONFIG_HOME, 'postpro_config/postpro_config.cfg')
MAIN_CFG = os.path.join(CONFIG_HOME, 'config/config.cfg')

HERE = os.path.dirname(os.path.abspath(__file__))
LOG_PATH = os.path.join(HERE, 'dxf2ngc.log')
LOG_LINES_KEPT = 200

# Where the file chooser opens, and where output goes if the DXF's own
# directory is not writable.
START_DIR = os.path.expanduser('~/cuts')
FALLBACK_OUT_DIR = '/home/pi/linuxcnc/nc_files'

CONVERT_TIMEOUT = 300           # seconds; a big DXF on a Pi 4 is not quick

# The plasma postprocessor. Blank string = emit nothing for that template.
PLASMA_POSTPRO = {
    'General': {
        'output_text': 'QtPlasmaC',
        'output_format': '.ngc',
        'output_type': 'g-code',
        'abs_export': 'True',                # G90, absolute
        'export_arcs_as_lines': 'False',     # keep real arcs, they cut better
        'repeat_drill_move': 'False',
        'code_begin_units_mm': 'G21 (metric)',
        'code_begin_prog_abs': 'G90 (absolute)',
        'code_begin': 'G64 P0.25 (path tolerance) G17 G40 G49 G80 G91.1 G94 G97',
        'code_end': 'M2',
    },
    'Program': {
        'tool_change': '',                   # no T/M6/S - there is no tool
        'feed_change': '',                   # feed comes from the material
        'rap_pos_depth': '',                 # no Z rapids
        'lin_mov_depth': '',                 # no Z plunges
        'lin_mov_drill': '',
        'lin_ret_drill': '',
        'pre_shape_cut': 'M3 $0 S1%nl',      # torch on
        'post_shape_cut': 'M5 $0%nl',        # torch off
    },
}

# Depth stepping must produce exactly ONE pass. start=0 with mill=slice=-1
# gives a single pass; 0/0 risks a zero-size step. The depth is then never
# emitted anyway because the Z templates above are blank, but a single pass
# is what stops each shape being cut twice.
PLASMA_DEPTHS = {
    'axis3_retract': '0.0',
    'axis3_safe_margin': '0.0',
    'axis3_start_mill_depth': '0.0',
    'axis3_slice_depth': '-1.0',
    'axis3_mill_depth': '-1.0',
}

# Travel feed, mm/min. Kept equal to the jog rate in [DISPLAY], park.ngc's
# park_feed and custom_filter.py's travel_feed, so every non-cutting move on
# this machine runs at the same speed.
TRAVEL_FEED = 1000

# Inserted before the first motion line. G21/G90/G64 already come from
# code_begin above; these are the plasma-specific additions.
PLASMA_HEADER = [
    'M52 P1 (enable reverse-run)',
    'F#<_hal[plasmac.cut-feed-rate]> (feed rate from the selected material)',
]

# A throwaway DXF used only to make dxf2gcode generate its default config.
# "dxf2gcode -q" with no file crashes on an unbound retval, so it needs
# something to convert.
SEED_DXF = ('0\nSECTION\n2\nENTITIES\n0\nLINE\n8\n0\n'
            '10\n0.0\n20\n0.0\n11\n1.0\n21\n0.0\n0\nENDSEC\n0\nEOF\n')


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
        pass                                 # logging must never break a cut


class ConvertError(Exception):
    """Anything the operator needs to be told about."""


def _run(argv, timeout):
    """dxf2gcode always builds a QApplication, even with -q, so give it the
    offscreen platform: that works with or without a display and never pops
    a window.

    Run it niced. This is launched from a button on a machine that is live,
    and the -o travel optimisation is the heaviest thing in the pipeline; the
    servo thread should always win. isolcpus keeps the realtime cores clear
    anyway, so this is only about the userspace cores it does share.
    """
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    return subprocess.run(['nice', '-n', '10'] + argv, env=env, timeout=timeout,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ensure_plasma_profile():
    """Install/refresh the plasma postprocessor. Idempotent."""
    from configobj import ConfigObj      # a dxf2gcode dependency, always present

    if not (os.path.isfile(POSTPRO_CFG) and os.path.isfile(MAIN_CFG)):
        log('seeding dxf2gcode default config')
        with tempfile.TemporaryDirectory() as tmp:
            seed = os.path.join(tmp, 'seed.dxf')
            with open(seed, 'w') as f:
                f.write(SEED_DXF)
            _run(['dxf2gcode', '-q', '-e', os.path.join(tmp, 'seed.ngc'), seed], 120)
        if not (os.path.isfile(POSTPRO_CFG) and os.path.isfile(MAIN_CFG)):
            raise ConvertError('dxf2gcode did not create its config in\n%s'
                               % CONFIG_HOME)

    changed = []
    pp = ConfigObj(POSTPRO_CFG)
    for section, values in PLASMA_POSTPRO.items():
        if section not in pp:
            raise ConvertError('no [%s] in %s' % (section, POSTPRO_CFG))
        for key, want in values.items():
            if pp[section].get(key) != want:
                pp[section][key] = want
                changed.append('%s/%s' % (section, key))
    if changed:
        pp.write()

    cf = ConfigObj(MAIN_CFG)
    for key, want in PLASMA_DEPTHS.items():
        if cf['Depth_Coordinates'].get(key) != want:
            cf['Depth_Coordinates'][key] = want
            changed.append('Depth_Coordinates/%s' % key)
    # Never let the shared config force stdout; this script controls output.
    if cf['General'].get('write_to_stdout') != 'False':
        cf['General']['write_to_stdout'] = 'False'
        changed.append('General/write_to_stdout')
    if changed:
        cf.write()
        log('plasma profile applied (%d key(s)): %s'
            % (len(changed), ', '.join(changed[:8])))


MOTION_RE = re.compile(r'^\s*(?:G0|G1|G2|G3|M3)\b')


def add_plasma_header(text):
    """Insert the plasma header after dxf2gcode's own preamble and before
    anything moves."""
    lines = text.splitlines()

    first_motion = next((i for i, l in enumerate(lines) if MOTION_RE.match(l)),
                        None)
    if first_motion is None:
        raise ConvertError('the converted file has no motion in it - is the '
                           'DXF empty, or are all its entities on a disabled '
                           'layer?')

    # Land straight after the last preamble G-word rather than immediately
    # before the first move, which would otherwise drop the header inside the
    # first "(* SHAPE Nr: 0 *)" block.
    preamble = [i for i, l in enumerate(lines[:first_motion])
                if re.match(r'^\s*G\d', l)]
    at = preamble[-1] + 1 if preamble else first_motion
    return '\n'.join(lines[:at] + PLASMA_HEADER + lines[at:]) + '\n'


RAPID_RE = re.compile(r'(?<![A-Z0-9_.<#])G0*0(?![0-9])')
FEED_MOVE_RE = re.compile(r'(?<![A-Z0-9_.<#])G0*[123](?![0-9])')
# An F word: a literal, a parameter such as F#<_hal[plasmac.cut-feed-rate]>,
# or a bracketed expression.
FEED_WORD_RE = re.compile(r'F\s*(?:#<[^>]*>|\[[^\]]*\]|[0-9.]+)')


def slow_travel(text):
    """Rewrite every rapid as a feed move at TRAVEL_FEED, the way
    custom_filter.py does for jobs that go through qtplasmac_gcode.

    LinuxCNC has no rapid feed rate setting - a G0 runs at whatever the
    participating joints allow. Lowering those limits is not an option: they
    also cap cutting, and the material file asks for up to 3000 mm/min. So the
    travel moves themselves are turned into G1 F<TRAVEL_FEED>.

    The modal feed is then restored, lazily: PLASMA_HEADER sets the feed once
    from the selected material and every cut relies on it, so without putting
    that F word back the first cut after a travel would run at TRAVEL_FEED
    instead of the material's cut speed. The saved F word is re-emitted just
    before the next move that would otherwise inherit the travel feed, and
    skipped when that move sets its own feed. A rewritten line has no G0 left
    to match, so a second pass changes nothing.
    """
    def split_comment(line):
        """Code, then trailing comment, split at whichever comment character
        comes first. dxf2gcode uses (...), but ; is legal too."""
        cut = len(line)
        for tag in ';(':
            found = line.find(tag)
            if found != -1:
                cut = min(cut, found)
        return line[:cut], line[cut:]

    out = []
    last_feed = None
    restore_pending = False
    for line in text.splitlines():
        code, comment = split_comment(line)
        feed = FEED_WORD_RE.search(code)
        if feed:
            # The program sets the modal feed itself here, so nothing is owed
            # even if a travel move came before it.
            last_feed = feed.group(0)
            restore_pending = False
        moves = any(axis in code for axis in 'XYZABCUVW')
        if RAPID_RE.search(code) and moves:
            code = RAPID_RE.sub('G1', code, count=1)
            code = FEED_WORD_RE.sub('', code).rstrip()
            gap = ' ' if comment else ''
            out.append('%s F%g%s%s' % (code, TRAVEL_FEED, gap, comment))
            restore_pending = last_feed is not None
            continue
        if restore_pending and FEED_MOVE_RE.search(code) and moves:
            if not feed:
                out.append('%s (restore feed after travel)' % last_feed)
            restore_pending = False
        out.append(line)
    return '\n'.join(out) + '\n'


def add_park(text):
    """Append the park move, the way custom_filter.py does for every other job.

    custom_filter.py hooks /usr/bin/qtplasmac_gcode, and NEITHER route this
    script uses goes through that filter: the [FILTER] dxf entry replaces it,
    and GUI mode hands the file straight to program_open. Without this, a DXF
    job would be the only kind that does not park at the end.

    custom_filter.py skips insertion when an o<park> call is already present,
    so a file produced here still gets exactly one park if it is later
    re-opened as an .ngc through the normal filter.
    """
    park = 'o<park> call (park at end of job)'
    if 'o<park>' in text.lower():
        return text
    lines = text.splitlines()
    for i in range(len(lines) - 1, -1, -1):
        code = lines[i].strip()
        if re.match(r'^M0*(?:2|30)\b', code) or code[:1] == '%':
            lines.insert(i, park)
            break
    else:
        lines.append(park)
    return '\n'.join(lines) + '\n'


def extents(text):
    """Conservative bounding box of the program, as (xmin, xmax, ymin, ymax).

    Arcs are bounded by centre +/- radius, i.e. as if each were a full circle.
    That over-estimates a short arc, which is the right way to be wrong for a
    limits warning.
    """
    xs, ys = [], []
    x = y = 0.0
    for raw in text.splitlines():
        line = re.sub(r'\([^)]*\)', '', raw)
        if not MOTION_RE.match(line):
            continue
        word = lambda ax: (lambda m: float(m.group(1)) if m else None)(
            re.search(r'\b%s\s*(-?\d+\.?\d*)' % ax, line))

        start_x, start_y = x, y
        nx, ny = word('X'), word('Y')
        if nx is not None:
            x = nx
        if ny is not None:
            y = ny
        xs.append(x)
        ys.append(y)

        i, j = word('I'), word('J')
        if i is not None and j is not None:
            cx, cy = start_x + i, start_y + j
            r = (i * i + j * j) ** 0.5
            xs.extend((cx - r, cx + r))
            ys.extend((cy - r, cy + r))

    if not xs:
        raise ConvertError('could not read any coordinates from the G-code')
    return min(xs), max(xs), min(ys), max(ys)


def limit_warnings(text, ini_limits):
    """Compare the program's extents with the machine's soft limits.

    Negative coordinates are not automatically wrong - a program normally sits
    in work coordinates and the operator touches off where the plate is - but
    with the work offsets at zero, machine coordinates ARE program
    coordinates, so it is worth saying out loud.
    """
    xmin, xmax, ymin, ymax = extents(text)
    (xlo, xhi), (ylo, yhi) = ini_limits
    width, height = xmax - xmin, ymax - ymin
    travel_x, travel_y = xhi - xlo, yhi - ylo
    notes = ['Size %.1f x %.1f mm   (X %.1f..%.1f, Y %.1f..%.1f)'
             % (width, height, xmin, xmax, ymin, ymax)]

    if width > travel_x or height > travel_y:
        # A long thin part often overruns one axis while fitting comfortably
        # across the other, so say whether rotating it would solve the problem
        # rather than just refusing it.
        note = ('DOES NOT FIT as drawn: the table is %.0f x %.0f mm'
                % (travel_x, travel_y))
        if height <= travel_x and width <= travel_y:
            note += (', but %.0f x %.0f would fit if you rotate the drawing 90 '
                     'degrees.' % (height, width))
        else:
            note += (', and it is too big either way round - %.0f mm of X and '
                     '%.0f mm of Y is all there is.' % (travel_x, travel_y))
        notes.append(note)
    elif xmin < xlo or ymin < ylo:
        notes.append('This drawing is not zeroed at its corner, so it needs a '
                     'work offset of at least X%.1f Y%.1f. With the offsets '
                     'at zero it will hit the soft limits (X min %.0f, Y min '
                     '%.0f) as soon as it runs.'
                     % (max(0.0, xlo - xmin), max(0.0, ylo - ymin), xlo, ylo))
    elif xmax > xhi or ymax > yhi:
        notes.append('Beyond the far soft limits (X max %.0f, Y max %.0f) at '
                     'the current work offset.' % (xhi, yhi))
    return notes


def machine_limits():
    """X and Y soft limits from the ini, so this never drifts out of step with
    the machine. Falls back to the values commented in the ini."""
    fallback = ((0.0, 1280.0), (0.0, 890.0))
    ini_path = os.environ.get('INI_FILE_NAME') or os.path.join(
        HERE, 'cnc_plasma_cutter.ini')
    try:
        import configparser
        cp = configparser.ConfigParser(strict=False, inline_comment_prefixes=None)
        cp.read(ini_path)
        return ((float(cp['AXIS_X']['MIN_LIMIT']),
                 float(cp['AXIS_X']['MAX_LIMIT'])),
                (float(cp['AXIS_Y']['MIN_LIMIT']),
                 float(cp['AXIS_Y']['MAX_LIMIT'])))
    except Exception as err:
        log('could not read soft limits from %s (%s), using %s'
            % (ini_path, err, fallback))
        return fallback


def strip_comments(text):
    """G-code comments: (...) and everything after a ;."""
    return re.sub(r';.*', '', re.sub(r'\([^)]*\)', '', text))


def validate(text):
    """Refuse anything that would hurt the torch or the plate. See the module
    docstring for what unmodified dxf2gcode output looks like."""
    problems = []
    code = strip_comments(text)

    if re.search(r'\bZ\s*[-+.\d]', code):
        problems.append('contains a Z move - QtPlasmaC owns Z via THC, and Z0 '
                        'is the TOP of this machine\'s travel')
    if re.search(r'\bM0*6\b', code) or re.search(r'\bT\d+', code):
        problems.append('contains a tool change (T/M6)')
    if re.search(r'\bM0*[789]\b', code):
        problems.append('contains a coolant word (M7/M8/M9)')

    # Torch on must always be the QtPlasmaC form. A bare M3/M4 is a spindle.
    for n, line in enumerate(code.splitlines(), 1):
        if re.search(r'\bM0*[34]\b', line) and '$0' not in line:
            problems.append('line %d is a spindle start, not a torch start: %r'
                            % (n, line.strip()))
            break

    if not re.search(r'\bM0*3\b', code):
        problems.append('nothing is ever cut - no torch-on command')

    return problems


def convert(dxf_path):
    """DXF path -> QtPlasmaC G-code text. Raises ConvertError."""
    if not os.path.isfile(dxf_path):
        raise ConvertError('no such file:\n%s' % dxf_path)

    ensure_plasma_profile()

    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'out.ngc')
        argv = ['dxf2gcode', '-q', '-o',
                '-p', 'QtPlasmaC (*.ngc)',   # postprocessor, matched by name
                '-e', out, dxf_path]
        log('converting %s' % dxf_path)
        try:
            done = _run(argv, CONVERT_TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ConvertError('dxf2gcode timed out after %d s on\n%s'
                               % (CONVERT_TIMEOUT, os.path.basename(dxf_path)))
        except FileNotFoundError:
            raise ConvertError('dxf2gcode is not installed.\n'
                               'Install it with:  sudo apt install dxf2gcode')

        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            # dxf2gcode reports most failures on stderr and still exits 0.
            detail = (done.stderr or b'').decode('utf-8', 'replace').strip()
            detail = '\n'.join(detail.splitlines()[-4:]) or 'no output produced'
            raise ConvertError('dxf2gcode could not convert\n%s\n\n%s'
                               % (os.path.basename(dxf_path), detail))
        with open(out) as f:
            text = f.read()

    text = add_park(slow_travel(add_plasma_header(text)))

    problems = validate(text)
    if problems:
        log('REFUSED: ' + '; '.join(problems))
        raise ConvertError(
            'The converted G-code is not safe to cut and was NOT loaded:\n\n'
            + '\n'.join('  - ' + p for p in problems)
            + '\n\nThis usually means the dxf2gcode plasma profile in\n'
              '%s\nhas been changed. Delete that directory and press DXF '
              'again to rebuild it.' % CONFIG_HOME)

    log('converted OK, %d lines' % len(text.splitlines()))
    return text


def output_path_for(dxf_path):
    """Beside the DXF if possible. LinuxCNC rejects a filename containing more
    than one '.', so any extra dots in the stem are flattened."""
    directory, name = os.path.split(os.path.abspath(dxf_path))
    stem = os.path.splitext(name)[0].replace('.', '_')
    if not os.access(directory, os.W_OK):
        directory = FALLBACK_OUT_DIR
    return os.path.join(directory, stem + '.ngc')


def load_into_linuxcnc(path):
    """Hand the file to a running LinuxCNC. Refuses if the machine is busy."""
    import linuxcnc

    stat = linuxcnc.stat()
    stat.poll()

    if stat.interp_state != linuxcnc.INTERP_IDLE:
        raise ConvertError('The G-code was written to\n%s\n\nbut NOT loaded: '
                           'the machine is running a program. Load it by hand '
                           'when the job finishes.' % path)

    # Do NOT touch the task mode. program_open does not need AUTO, and asking
    # for AUTO is asking for coordinated mode, which requires every joint to be
    # homed - on an unhomed machine that is rejected with "all joints must be
    # homed before going into coordinated mode" on every single load. qtvcp's
    # own ACTION.OPEN_PROGRAM calls program_open with no mode change either.
    command = linuxcnc.command()
    command.program_open(path)
    command.wait_complete()
    log('loaded %s' % path)


def gui_main():
    """Button mode: choose a DXF, convert it, load it."""
    from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication(sys.argv)

    start = START_DIR if os.path.isdir(START_DIR) else os.path.expanduser('~')
    dxf_path, _ = QFileDialog.getOpenFileName(
        None, 'Select a DXF to convert', start,
        'DXF drawings (*.dxf *.DXF);;All files (*)')
    if not dxf_path:
        return 0                             # cancelled, nothing to say

    try:
        text = convert(dxf_path)
        out = output_path_for(dxf_path)
        with open(out, 'w') as f:
            f.write(text)
        load_into_linuxcnc(out)
    except ConvertError as err:
        log('error: %s' % str(err).replace('\n', ' ')[:200])
        QMessageBox.critical(None, 'DXF conversion failed', str(err))
        return 1
    except Exception as err:                 # never die silently behind a button
        log('unexpected %s: %s' % (type(err).__name__, err))
        QMessageBox.critical(None, 'DXF conversion failed',
                             'Unexpected %s:\n%s\n\nSee %s'
                             % (type(err).__name__, err, LOG_PATH))
        return 1

    notes = '\n\n'.join(limit_warnings(text, machine_limits()))
    log('extents: %s' % notes.replace('\n', ' '))
    QMessageBox.information(
        None, 'DXF converted',
        'Loaded:\n%s\n\n%s\n\nNo lead-ins and no kerf compensation - the '
        'torch pierces on the line itself. Check the preview and the '
        'material selection before cutting.' % (out, notes))
    return 0


def filter_main(dxf_path):
    """[FILTER] mode: G-code to stdout, errors to stderr.

    The extents notes go out as G-code comments rather than on stderr, where a
    filter's output tends to be reported to the operator as a failure.
    """
    try:
        text = convert(dxf_path)
        notes = limit_warnings(text, machine_limits())
        log('extents: %s' % ' '.join(notes))
        header = ''.join('(%s)\n' % n.replace('(', '[').replace(')', ']')
                         for note in notes for n in note.splitlines())
        sys.stdout.write(header + text)
    except ConvertError as err:
        sys.stderr.write('%s\n' % err)
        return 1
    return 0


if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    sys.exit(filter_main(args[0]) if args else gui_main())
