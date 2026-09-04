#!/usr/bin/env python3
"""
PICK SHAPE - cut one shape out of a loaded job instead of the whole part.

Load a job the usual way (an .ngc, or a .dxf through the DXF button), press
PICK SHAPE, and a window draws the whole toolpath. Step through the shapes with
the arrow keys or click one, choose whether to cut only that shape or to start
there and run to the end, and it writes a new program containing exactly that.

WHAT A SHAPE IS
---------------
One torch-on to torch-off pair: M3 $0 ... M5 $0. That is the only definition
that works on any g-code. Where the file also carries DXF2GCODE's
"(* SHAPE Nr: n *)" comments - everything dxf2ngc.py produces does - the
comment is used as the label, so the numbering in the picker matches the
numbering in the g-code window.

WHAT IT PRODUCES
----------------
SELECTED_SHAPE.ngc, in the directory the job came from, and LOAD INTO QTPLASMAC
hands it straight to the interpreter so the preview comes up and CYCLE START is
the next thing you press.

Loading is done with program_open(), the same way dxf2ngc.py loads a converted
DXF, which means it does not go through [FILTER] ngc = qtplasmac_gcode. Nothing
is lost by that here: what this writes is assembled out of a program the filter
has already been through, so the travel clamp, the material change and the park
call are all already in the lines being copied, and run_from_line adds the safe-Z
lift itself. WRITE FILE ONLY is there for the times you would rather look at the
file first; opening it with the file button afterwards runs the filter over it,
which custom_filter.py is written to survive a second time.

The remainder is assembled by plasmac.run_from_line, the module behind the
GUI's own RUN FROM LINE button, for the reasons set out at the top of
resume_cut.py: re-establishing G20/G21, G64, G90/G91, the torch and THC flags,
the material change and the cut feed rate by hand is a torch firing at the
wrong height when one of them is missed.

WHICH LINE IS HANDED TO run_from_line
-------------------------------------
The M3 line of the chosen shape, and this is not interchangeable with the two
obvious alternatives. run_from_line_set() positions the torch at codes['x1'],
codes['y1'] - the last commanded XY *before* the start line - and does not use
the coordinates found after it unless the first move there is a G00. Nothing on
this machine travels with G00: dxf2ngc.py emits G1 at the travel feed, and
custom_filter.py rewrites any G0 that does appear. So

  start at the shape comment or at its positioning move
      x1/y1 is the END OF THE PREVIOUS SHAPE. The generated program rapids
      back there first, then travels to the pierce point and fires. Safe, but
      it drives the length of the plate for nothing.

  start at the M3 line
      the positioning move is the last thing in preData, so x1/y1 is the pierce
      point. Output is "G00 X.. Y.." then "M3 $0 S1" then the cut. This is the
      one to use.

  start at the line after M3
      the M3 is in neither half. The program travels to the pierce point and
      cuts the shape with the torch off.

CANONICAL G-CODE TEXT
---------------------
run_from_line's get_rfl_pos() gives up on "X 598.409" and returns an empty
string, silently, which is how the third case above ends up looking like the
second, and the rest of run_from_line only ever matches "G01", "G02" and
"M03 $0". qtplasmac_gcode writes all of that, but only into the filtered copy,
and a job loaded by the DXF user button never becomes one: dxf2ngc.py calls
command.program_open() directly and bypasses [FILTER] entirely. So the program
is put into that spelling in a scratch copy, by resume_cut.normalised_copy(),
before run_from_line sees it. The substitution is per line and changes no line
count, so every line number still refers to the same line of the file the
operator is looking at.

BEFORE PRESSING CYCLE START
---------------------------
Check the preview lands where the shape belongs on the plate. Nothing here
knows whether the plate moved, and a single shape cut in the wrong place is
the same wasted plate as a whole job cut in the wrong place.

Wired to a user button in cnc_plasma_cutter.prefs [BUTTONS] as
"%/home/pi/linuxcnc/configs/cnc_plasma_cutter/pick_shape.py". The handler
Popen()s that without reading stdout, so everything here goes to
pick_shape.log instead: a chatty script would eventually block on a full pipe.
"""

import math
import os
import re
import shutil
import sys
import time

CONFIG_DIR = os.path.dirname(os.path.abspath(__file__))
INI = os.path.join(CONFIG_DIR, 'cnc_plasma_cutter.ini')
QTVCP_PREFS = os.path.join(CONFIG_DIR, 'qtvcp.prefs')
LOG_PATH = os.path.join(CONFIG_DIR, 'pick_shape.log')

# One dot only: qtvcp refuses to open a file whose basename has more than one,
# because LinuxCNC cannot.
OUTPUT_NAME = 'SELECTED_SHAPE.ngc'

LOG_LINES_KEPT = 200

# Programs the GUI loads for its own purposes. Picking a shape out of one of
# these is never what was meant.
INTERNAL_PROGRAMS = ('qtplasmac_program_clear', 'single_cut', 'rfl.ngc',
                     'plasmac_axis.ngc')

# Chord length used to draw an arc, in program units. Only the picture is
# approximated - the g-code that gets written keeps the original G2/G3.
ARC_CHORD = 0.8

# A G or M code at a code position: not part of a longer number, not inside a
# parameter name. Same guard custom_filter.py uses.
MOTION = re.compile(r'(?<![A-Z0-9_.<#])G0*([0123])(?![0-9])')
ARC_PLANE_MODE = re.compile(r'(?<![A-Z0-9_.<#])G9([01])\.1(?![0-9])')
# An axis word with a plain numeric value. Values that are parameters or
# expressions are skipped rather than guessed at: they cannot be drawn, and a
# shape that contains one is still perfectly cuttable.
WORD = re.compile(r'(?<![A-Z0-9_.<#\[])([XYZIJKR])\s*(-?\d*\.?\d+)')

# The g-code text helpers, the safety net, the output path and the loader all
# already exist next door, and there should be exactly one implementation of
# each of them on this machine. dxf2ngc.load_into_linuxcnc() carries the
# reasoning about task mode with it; both files are import-safe, everything
# they run is under __main__.
sys.path.insert(0, CONFIG_DIR)
from resume_cut import (TORCH_ON, TORCH_OFF, collapse_repeated_torch_on,  # noqa: E402
                        first_pierce_is_positioned, leaked_annotation,
                        normalised_copy, output_directory, split_comment)
from dxf2ngc import load_into_linuxcnc  # noqa: E402


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


# ---------------------------------------------------------------- the program

def loaded_program(stat):
    """(path, why_not). The program the interpreter has open.

    stat.file is what QtPlasmaC's handler calls lastLoadedProgram - it is set
    from the STATUS file-loaded signal, and it is the file run_from_line has to
    be pointed at, filtered copy or not.
    """
    path = (stat.file or '').strip()
    if not path or not os.path.isfile(path):
        return None, ('No program is loaded.\n\n'
                      'Open the job first - an .ngc with the file button, or a\n'
                      '.dxf with the DXF button - then press PICK SHAPE.')
    if any(name in os.path.basename(path) for name in INTERNAL_PROGRAMS):
        return None, ('The loaded program is %s, which the GUI loaded for its\n'
                      'own purposes. Load the job you want to pick from.'
                      % os.path.basename(path))
    return path, None


# ---------------------------------------------------------------- the shapes

def arc_points(start, end, offset, radius, clockwise):
    """The points of an arc, as chords. offset is (I, J) from the start point;
    radius is the R word. One of the two is given."""
    x0, y0 = start
    x1, y1 = end
    if offset is not None:
        cx, cy = x0 + offset[0], y0 + offset[1]
    else:
        # R format. The chord's perpendicular bisector, offset by the height of
        # the triangle; a negative R asks for the long way round.
        chord = math.hypot(x1 - x0, y1 - y0)
        if not chord or abs(radius) * 2 < chord - 1e-9:
            return [end]
        mid = ((x0 + x1) / 2.0, (y0 + y1) / 2.0)
        height = math.sqrt(max(0.0, radius * radius - (chord / 2.0) ** 2))
        ux, uy = (y1 - y0) / chord, -(x1 - x0) / chord
        sign = 1.0 if (radius > 0) == clockwise else -1.0
        cx, cy = mid[0] + ux * height * sign, mid[1] + uy * height * sign

    r = math.hypot(x0 - cx, y0 - cy)
    if r < 1e-9:
        return [end]
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    sweep = a1 - a0
    if clockwise:
        while sweep >= 0:
            sweep -= 2 * math.pi
    else:
        while sweep <= 0:
            sweep += 2 * math.pi
    # A move that ends where it started is a full circle, not a zero sweep.
    if abs(math.hypot(x1 - x0, y1 - y0)) < 1e-9:
        sweep = -2 * math.pi if clockwise else 2 * math.pi

    steps = max(4, int(abs(sweep) * r / ARC_CHORD) + 1)
    return [(cx + r * math.cos(a0 + sweep * n / steps),
             cy + r * math.sin(a0 + sweep * n / steps))
            for n in range(1, steps + 1)]


def parse_shapes(path):
    """(shapes, travel). Walk the program once, tracking modal state.

    A shape is one M3..M5 pair. Its 'start' is the 1-based line number of the
    M3, which is the line run_from_line is given; see the module docstring for
    why it is that line and not the positioning move above it.
    """
    shapes, travel = [], []
    x = y = 0.0
    motion = None
    arcs_absolute = False
    label = None
    current = None

    with open(path) as f:
        lines = f.readlines()

    for number, raw in enumerate(lines, 1):
        code, comment = split_comment(raw)

        # DXF2GCODE labels its shapes; keep the most recent label seen so the
        # picker can number them the way the g-code window does.
        found = re.search(r'SHAPE\s*Nr[:.\s]*(\d+)', comment, re.I)
        if found:
            label = found.group(1)

        plane = ARC_PLANE_MODE.search(code)
        if plane:
            arcs_absolute = plane.group(1) == '0'

        words = {letter: float(value) for letter, value in WORD.findall(code)}
        move = MOTION.search(code)
        if move:
            motion = int(move.group(1))
        # G53 is a machine-coordinate move, almost always the Z lift to safe
        # height. It says nothing about where the torch is in X and Y, and
        # letting it move the pen would draw a line to the machine origin.
        machine_coords = 'G53' in code.replace(' ', '')

        nx = words.get('X', x)
        ny = words.get('Y', y)
        moved = ('X' in words or 'Y' in words) and motion is not None

        if moved and not machine_coords:
            if motion in (2, 3):
                if 'I' in words or 'J' in words:
                    offset = (words.get('I', 0.0), words.get('J', 0.0))
                    if arcs_absolute:
                        offset = (offset[0] - x, offset[1] - y)
                    points = arc_points((x, y), (nx, ny), offset, None, motion == 2)
                else:
                    points = arc_points((x, y), (nx, ny), None,
                                        words.get('R', 0.0), motion == 2)
            else:
                points = [(nx, ny)]

            if current is not None:
                current['points'].extend(points)
                current['moves'] += 1
            else:
                travel.append(((x, y), (nx, ny)))
            x, y = points[-1] if points else (nx, ny)

        if TORCH_ON.search(code) and current is None:
            # The pierce is wherever the last commanded move left the torch,
            # which is also exactly the point run_from_line will rapid to.
            current = {'label': label, 'start_line': number, 'pierce': (x, y),
                       'points': [(x, y)], 'moves': 0, 'end_line': None}
            continue

        if TORCH_OFF.search(code) and current is not None:
            current['end_line'] = number
            shapes.append(current)
            current = None
            label = None

    # A torch-on with no torch-off after it: the file is malformed, but the
    # shape is still the last thing in it, so offer it and end at EOF.
    if current is not None:
        current['end_line'] = len(lines)
        shapes.append(current)

    for index, shape in enumerate(shapes):
        shape['index'] = index
        if shape['label'] is None:
            shape['label'] = str(index)
        xs = [p[0] for p in shape['points']]
        ys = [p[1] for p in shape['points']]
        shape['extent'] = (min(xs), min(ys), max(xs), max(ys)) if xs else (0, 0, 0, 0)
        shape['closed'] = (len(shape['points']) > 2 and
                           math.hypot(shape['points'][0][0] - shape['points'][-1][0],
                                      shape['points'][0][1] - shape['points'][-1][1]) < 0.05)
    return shapes, travel


def program_tail(lines):
    """Everything after the last torch-off: the return move, the park call and
    the end code. Put back after a single shape so that cutting one shape ends
    the same way cutting the whole job does."""
    last = None
    for number, raw in enumerate(lines):
        if TORCH_OFF.search(split_comment(raw)[0]):
            last = number
    if last is None:
        return ['M2']
    tail = [line.rstrip('\n') for line in lines[last + 1:]]
    return tail if any(line.strip() for line in tail) else ['M2']


# ---------------------------------------------------------------- the picker

# The canvas is as big as what is left of the screen once everything else has
# been measured, up to these. Fixed sizes are what put the buttons off the
# bottom of a 1360x768 panel in the first place.
CANVAS_MAX_W, CANVAS_MAX_H = 900, 520
CANVAS_MIN_H = 200
BACKGROUND = '#1b1b1b'
TRAVEL_COLOUR = '#3a3a3a'
SHAPE_COLOUR = '#8a8a8a'
PICKED_COLOUR = '#ffa020'
PIERCE_COLOUR = '#40c060'


def pick(shapes, travel, program_name):
    """Modal picker. Returns None to cancel, else (shape, mode, load).

    Tk rather than Qt to keep a second Qt application out of the GUI's process
    tree, as resume_cut.py and set_zero_here.py do.

    Everything except the drawing is packed first, and the controls are packed
    against the BOTTOM. Tk gives space to widgets in packing order, so whatever
    does not fit comes off the canvas rather than off the buttons - on a screen
    too short for the lot, the picture shrinks and the window still works.
    """
    import tkinter as tk

    result = {}
    root = tk.Tk()
    root.title('PICK SHAPE')
    root.attributes('-topmost', True)

    width = min(CANVAS_MAX_W, root.winfo_screenwidth() - 60)

    chosen = tk.IntVar(value=0)
    counter = tk.StringVar(value='1')
    mode = tk.StringVar(value='rest')

    tk.Label(root, text=os.path.basename(program_name), anchor='w',
             font='TkFixedFont').pack(padx=12, pady=(10, 4), fill='x')

    buttons = tk.Frame(root)
    buttons.pack(side='bottom', pady=(6, 12))

    tk.Label(root, justify='left', anchor='w', wraplength=width,
             text=('Check the preview lands where the shape belongs on the '
                   'plate before CYCLE START.')
             ).pack(side='bottom', padx=12, pady=(6, 0), fill='x')

    modes = tk.Frame(root)
    modes.pack(side='bottom', padx=12, pady=(8, 0), fill='x')
    tk.Radiobutton(modes, text='This shape, then everything after it',
                   variable=mode, value='rest', anchor='w').pack(fill='x')
    tk.Radiobutton(modes, text='Only this shape',
                   variable=mode, value='one', anchor='w').pack(fill='x')

    stepper = tk.Frame(root)
    stepper.pack(side='bottom', padx=12, pady=(6, 0), fill='x')

    # Three lines of placeholder, so the height measured below is the height
    # this label will actually take once show() fills it in.
    info = tk.Label(root, text='\n\n', justify='left', anchor='w',
                    font='TkFixedFont')
    info.pack(side='bottom', padx=12, pady=(8, 0), fill='x')

    def go(load):
        result['shape'] = shapes[chosen.get()]
        result['mode'] = mode.get()
        result['load'] = load
        root.destroy()

    tk.Button(buttons, text='LOAD INTO QTPLASMAC', width=22,
              command=lambda: go(True)).pack(side='left', padx=8)
    tk.Button(buttons, text='WRITE FILE ONLY', width=18,
              command=lambda: go(False)).pack(side='left', padx=8)
    tk.Button(buttons, text='CANCEL', width=10,
              command=root.destroy).pack(side='left', padx=8)

    # Everything that is not the drawing now exists, so what is left over is
    # what the drawing gets. The 110px is headroom for the title bar, the
    # window border and the panel, none of which winfo_reqheight() knows about.
    root.update_idletasks()
    height = root.winfo_screenheight() - root.winfo_reqheight() - 150
    height = max(CANVAS_MIN_H, min(CANVAS_MAX_H, height))

    canvas = tk.Canvas(root, width=width, height=height, bg=BACKGROUND,
                       highlightthickness=0)
    canvas.pack(side='top', padx=12, fill='both', expand=True)

    # Fit everything drawn - cuts and travel alike - into the canvas, Y up.
    points = [p for shape in shapes for p in shape['points']]
    points += [p for pair in travel for p in pair]
    x0 = min(p[0] for p in points)
    x1 = max(p[0] for p in points)
    y0 = min(p[1] for p in points)
    y1 = max(p[1] for p in points)
    margin = 24
    scale = min((width - 2 * margin) / max(x1 - x0, 1e-6),
                (height - 2 * margin) / max(y1 - y0, 1e-6))
    ox = (width - (x1 - x0) * scale) / 2.0
    oy = (height - (y1 - y0) * scale) / 2.0

    def to_canvas(point):
        return (ox + (point[0] - x0) * scale,
                height - oy - (point[1] - y0) * scale)

    for start, end in travel:
        a, b = to_canvas(start), to_canvas(end)
        canvas.create_line(a[0], a[1], b[0], b[1], fill=TRAVEL_COLOUR, dash=(2, 4))

    # Drawn once; picking only changes colour and width, so stepping through a
    # big job stays instant.
    for shape in shapes:
        flat = []
        for point in shape['points']:
            flat.extend(to_canvas(point))
        shape['_screen'] = [to_canvas(p) for p in shape['points']]
        shape['_item'] = (canvas.create_line(*flat, fill=SHAPE_COLOUR, width=1)
                          if len(flat) >= 4 else
                          canvas.create_oval(flat[0] - 2, flat[1] - 2,
                                             flat[0] + 2, flat[1] + 2,
                                             outline=SHAPE_COLOUR))
    marker = canvas.create_oval(0, 0, 0, 0, outline=PIERCE_COLOUR, width=2)

    def show(*_):
        index = chosen.get()
        for shape in shapes:
            picked = shape['index'] == index
            colour = PICKED_COLOUR if picked else SHAPE_COLOUR
            try:
                canvas.itemconfigure(shape['_item'], fill=colour, width=3 if picked else 1)
            except tk.TclError:      # the single-point oval has no fill
                canvas.itemconfigure(shape['_item'], outline=colour)
            if picked:
                canvas.tag_raise(shape['_item'])
        shape = shapes[index]
        counter.set(str(index + 1))
        px, py = to_canvas(shape['pierce'])
        canvas.coords(marker, px - 6, py - 6, px + 6, py + 6)
        canvas.tag_raise(marker)
        left, bottom, right, top = shape['extent']
        info.configure(text=(
            'shape %s   (%d of %d)      lines %d-%d\n'
            'pierce   X %.3f  Y %.3f\n'
            'size     %.1f x %.1f      %d cut moves, %s'
            % (shape['label'], index + 1, len(shapes),
               shape['start_line'], shape['end_line'],
               shape['pierce'][0], shape['pierce'][1],
               right - left, top - bottom, shape['moves'],
               'closed' if shape['closed'] else 'open')))

    def step(delta):
        chosen.set(max(0, min(len(shapes) - 1, chosen.get() + delta)))
        show()

    def typed():
        try:
            wanted = int(counter.get()) - 1
        except ValueError:
            show()
            return
        chosen.set(max(0, min(len(shapes) - 1, wanted)))
        show()

    def clicked(event):
        best, distance = None, 20.0
        for shape in shapes:
            for sx, sy in shape['_screen']:
                gap = math.hypot(sx - event.x, sy - event.y)
                if gap < distance:
                    best, distance = shape['index'], gap
        if best is not None:
            chosen.set(best)
            show()

    canvas.bind('<Button-1>', clicked)
    root.bind('<Left>', lambda e: step(-1))
    root.bind('<Right>', lambda e: step(1))
    root.bind('<Home>', lambda e: (chosen.set(0), show()))
    root.bind('<End>', lambda e: (chosen.set(len(shapes) - 1), show()))

    tk.Button(stepper, text='<', width=3, command=lambda: step(-1)).pack(side='left')
    tk.Spinbox(stepper, from_=1, to=len(shapes), width=6, justify='center',
               textvariable=counter, command=typed).pack(side='left', padx=6)
    tk.Button(stepper, text='>', width=3, command=lambda: step(1)).pack(side='left')
    tk.Label(stepper, text='  click a shape, or use the arrow keys',
             anchor='w').pack(side='left')

    # Place the window explicitly, near the top. Left to the window manager it
    # landed 70px down a 768px screen, which put the three buttons 8px off the
    # bottom - a window that fits is not the same as a window that is put where
    # it fits. The window manager adds its own title bar height to whatever y is
    # asked for, so ask for the top and let it push the window down.
    root.update_idletasks()
    want_w, want_h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry('%dx%d+%d+%d'
                  % (want_w, want_h,
                     max(0, (root.winfo_screenwidth() - want_w) // 2), 10))

    show()
    root.mainloop()
    return ((result['shape'], result['mode'], result['load'])
            if result else None)


# ---------------------------------------------------------------- generating

def truncate_after_shape(path, tail):
    """(ok, detail). Cut the generated program off after its first torch-off
    and put the program's own ending back.

    run_from_line always builds from the start line to the end of the file, so
    "only this shape" is that output with everything past the shape's M5
    replaced by the tail: the return move, the park call and the end code.
    """
    with open(path) as f:
        lines = f.readlines()
    seen_on = False
    for number, raw in enumerate(lines):
        code = split_comment(raw)[0]
        if TORCH_ON.search(code):
            seen_on = True
        elif seen_on and TORCH_OFF.search(code):
            kept = lines[:number + 1]
            with open(path, 'w') as f:
                f.writelines(kept)
                f.write('\n'.join(tail) + '\n')
            return True, 'truncated after line %d of the generated file' % (number + 1)
    return False, 'the generated program has no torch-off to truncate at'


# ---------------------------------------------------------------- operator

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
    log('--- PICK SHAPE pressed ---')

    try:
        import linuxcnc
    except Exception as err:
        log('linuxcnc module unavailable: %s' % err)
        tell('PICK SHAPE', 'The linuxcnc module is unavailable:\n%s' % err,
             icon='error')
        return 1
    try:
        stat = linuxcnc.stat()
        stat.poll()
    except Exception as err:
        log('LinuxCNC is not running: %s' % err)
        tell('PICK SHAPE', 'LinuxCNC is not running:\n%s' % err, icon='error')
        return 1

    # Writing a file is read-only as far as the machine is concerned, so being
    # unpowered or unhomed does not block; a running program does, because the
    # file this would write is the one the operator is about to load over it.
    if stat.interp_state != linuxcnc.INTERP_IDLE:
        log('refused: a program is running')
        tell('PICK SHAPE', 'A program is running - stop it first.',
             icon='warning')
        return 1

    program, why_not = loaded_program(stat)
    if not program:
        log('refused: %s' % why_not.replace('\n', ' '))
        tell('PICK SHAPE', why_not, icon='warning')
        return 1
    log('program %s' % program)

    source, changed = normalised_copy(program, prefix='pick_shape-')
    log('normalised copy %s (%d lines rewritten)' % (source, changed))

    shapes, travel = parse_shapes(source)
    if not shapes:
        log('refused: no M3/M5 pairs found')
        tell('PICK SHAPE',
             'No shapes found in\n\n  %s\n\n'
             'A shape is a torch-on to torch-off pair (M3 $0 ... M5 $0), and\n'
             'this program contains none.' % os.path.basename(program),
             icon='warning')
        return 1
    log('%d shapes, labels %s..%s'
        % (len(shapes), shapes[0]['label'], shapes[-1]['label']))

    choice = pick(shapes, travel, program)
    if not choice:
        log('operator cancelled')
        return 0
    shape, mode, load = choice
    log('chose shape %s (line %d), mode %s, load %s'
        % (shape['label'], shape['start_line'], mode, load))

    try:
        from plasmac import run_from_line as RFL
    except Exception as err:
        log('cannot import plasmac.run_from_line: %s' % err)
        tell('PICK SHAPE', 'Cannot load QtPlasmaC\'s run_from_line module:\n%s'
             % err, icon='error')
        return 1

    # run_from_line_get counts from zero; start_line is the 1-based M3 line.
    data = RFL.run_from_line_get(source, shape['start_line'] - 1)
    if data.get('error'):
        if data.get('compError'):
            why = ('cutter compensation (G41/G42) is active at that point.\n'
                   'A program cannot be built through it.')
        else:
            why = ('that line is inside a subroutine (%s).\n'
                   'A program cannot be built from inside one.'
                   % ' '.join(data.get('subError') or []))
        log('run_from_line_get refused: %s' % why.replace('\n', ' '))
        tell('PICK SHAPE', 'Cannot start at shape %s:\n\n%s'
             % (shape['label'], why), icon='error')
        return 1

    units_per_mm = 1.0 if stat.linear_units == 1.0 else 0.03937

    out_dir = output_directory()
    out_path = os.path.join(out_dir, OUTPUT_NAME)
    # Keep the previous one: a shape that turns out to have been the wrong one
    # is easier to reason about with the last attempt still on disk.
    if os.path.isfile(out_path):
        try:
            shutil.copyfile(out_path, out_path + '.prev')
        except Exception:
            pass

    # No leadin. The same argument as resume_cut.py: a leadin moves the pierce
    # off the cut line, which is only right when the material on that side is
    # scrap, and nothing here knows which side that is.
    RFL.run_from_line_set(out_path, data, {'do': False, 'length': 0.0,
                                           'angle': 0.0}, units_per_mm)
    dropped = collapse_repeated_torch_on(out_path)
    if dropped:
        log('dropped %d duplicated torch-on line(s)' % dropped)

    if mode == 'one':
        with open(source) as f:
            tail = program_tail(f.readlines())
        ok, detail = truncate_after_shape(out_path, tail)
        log('truncate: %s (%s)' % ('ok' if ok else 'FAILED', detail))
        if not ok:
            tell('PICK SHAPE',
                 'REFUSING TO OFFER THIS FILE.\n\n'
                 'Only shape %s was asked for, but %s, so the file that was\n'
                 'written runs to the end of the job instead. It is at\n\n  %s'
                 '\n\nfor inspection; do not run it expecting one shape.\n\n'
                 'See pick_shape.log.' % (shape['label'], detail, out_path),
                 icon='error')
            return 1

    ok, detail = leaked_annotation(out_path)
    log('annotation check: %s (%s)' % ('ok' if ok else 'FAILED', detail))
    if not ok:
        tell('PICK SHAPE',
             'REFUSING TO OFFER THIS FILE.\n\n'
             'The generated program %s. LinuxCNC would\n'
             'refuse to load it. The file is at\n\n  %s\n\nfor inspection.\n\n'
             'See pick_shape.log.' % (detail, out_path), icon='error')
        return 1

    ok, detail = first_pierce_is_positioned(out_path)
    log('pierce check: %s (%s)' % ('ok' if ok else 'FAILED', detail))
    if not ok:
        tell('PICK SHAPE',
             'REFUSING TO OFFER THIS FILE.\n\n'
             'The generated program was checked and %s.\n\n'
             'Running it would strike the arc wherever the machine is\n'
             'standing now and then drag it to the cut. The file is still\n'
             'at\n\n  %s\n\nfor inspection, but do not run it as it is.\n\n'
             'The input it was built from is at\n\n  %s\n\nSee pick_shape.log.'
             % (detail, out_path, source), icon='error')
        return 1

    what = ('only shape %s' % shape['label'] if mode == 'one'
            else 'shape %s and everything after it' % shape['label'])
    log('wrote %s: %s, from line %d' % (out_path, what, shape['start_line']))

    header = ('Written:\n\n  %s\n\n'
              'It contains %s, out of %s.\n'
              'The first pierce is at X %.3f  Y %.3f.\n\n'
              % (out_path, what, os.path.basename(program),
                 shape['pierce'][0], shape['pierce'][1]))

    if not load:
        tell('PICK SHAPE', header +
             'Open it with the FILE BUTTON - not the DXF button, which skips\n'
             'the filter - then CHECK THE PREVIEW LANDS WHERE THE SHAPE\n'
             'BELONGS ON THE PLATE before CYCLE START.')
        return 0

    try:
        load_into_linuxcnc(out_path)
    except Exception as err:          # ConvertError, or NML refusing
        log('could not load: %s' % err)
        tell('PICK SHAPE', header +
             'It could NOT be loaded:\n\n  %s\n\n'
             'Open it by hand with the file button.' % err, icon='warning')
        return 1

    log('loaded %s' % out_path)
    tell('PICK SHAPE', header +
         'It is loaded and on the preview now.\n\n'
         'CHECK THE PREVIEW LANDS WHERE THE SHAPE BELONGS ON THE PLATE,\n'
         'then CYCLE START.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
