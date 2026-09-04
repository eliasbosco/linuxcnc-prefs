# Recovering from a power cut or a crash mid-cut

Written 2026-09-04, after an outage left the torch resting on the plate with
Z reading 0 and PARK unable to move.

Two separate problems get tangled together when the power goes out during a
cut. Untangle them in this order, because the first one blocks the second.

1. **The machine cannot move.** The torch is sitting on the material, so the
   float switch is closed, so jogging is inhibited; and LinuxCNC may believe Z
   is at the top of travel when it is not, in which case Z+ is also against a
   soft limit.
2. **The job is unfinished.** Where in the program it stopped is not something
   the machine remembers by itself.

---

## Part 1 - get the torch off the plate

### Why it is stuck

**The float switch.** `custom.hal` nets the real switch on gpio.015 into
`plasmac:float-switch`, and that feeds `plasmac:jog-inhibit`. With the torch
pressed down on the plate the switch is closed, so QtPlasmaC refuses every jog.
The escape hatch is the **OVERRIDE JOG** checkbox, which enables itself
whenever the float, ohmic or breakaway input is active. Tick it and jogging
works again. Settings now also has *Override jog inhibit via Z+* turned on, so
a Z+ jog ticks it for you - Z+ is the only direction that gets the override,
because it is the only direction that is unconditionally away from the
material.

**The Z soft limit.** `[AXIS_Z] MAX_LIMIT = 0` - machine Z0 is the *top* of
travel, not the plate. A power cut leaves the torch down near Z -38 but,
because this machine homes immediately from the INI, HOME ALL declares Z to be
whatever `[JOINT_2] HOME` says. If that is 0, LinuxCNC now believes the torch is
already at the top: Z+ is refused as a limit violation, PARK's `G53 G1 Z0` is a
no-op, and the X/Y half of PARK then drags the torch across the plate. That is
the failure this file exists because of.

`save_position.py` now saves while the machine is moving, so after an outage
`[JOINT_2] HOME` holds roughly the real Z and this does not happen again. It
can still happen for a cut that predates that change, or if the machine was
pushed by hand with the drives off.

### The procedure

**Do not press HOME ALL.** Soft limits only apply to a joint that is homed, so
an unhomed machine can be jogged out of a place a homed one cannot.

1. Clear E-stop, power on. Leave the machine **unhomed**.
2. Tick **OVERRIDE JOG** (or just jog Z+, which now ticks it).
3. Jog **Z+** until the torch is back at the top of its travel. By eye - the
   machine has no switch to tell you. Stop before the mechanical stop.
4. Jog **X** and **Y** to the corner you call machine zero.
5. Press **SET ZERO HERE**. It writes zeros into all four `HOME`/`HOME_OFFSET`
   values, clears the stored work offsets and restarts QtPlasmaC.
6. Press **HOME ALL**. The machine is honest again.

If step 3 will not move even with the override ticked, the machine got homed
before you started. Restart QtPlasmaC and do not home it this time.

---

## Part 2 - resume the job

### Automatically: the RESUME CUT button

`cut_recorder.py` runs from `[APPLICATIONS]` and, while a program is in AUTO,
writes into `resume/` every half second:

| file | what it is |
|------|------------|
| `live_state` | the executing line number, the work offset, the joint positions, a timestamp |
| `live_program.ngc` | a copy of the **filtered** program the interpreter is running |
| `interrupted_state`, `interrupted_program.ngc` | the above, snapshotted at startup if the last session died mid-job, so a probe test afterwards cannot overwrite it |

The program copy is not optional. QtPlasmaC runs the *output* of
`qtplasmac_gcode`, from a temp directory under `/tmp`, which is tmpfs here and
is deleted on exit anyway. A line number means nothing except against that
exact file.

Then, after part 1 is done and the machine is homed:

1. Press **RESUME CUT**.
2. It shows which program, which line of how many, when, where the torch
   stopped, and whether the recorded work offset differs from the live one.
   Let it restore the offset - a power cut loses the touch-off, because
   LinuxCNC only writes `linuxcnc.var` when milltask exits cleanly.
3. It writes **`RESUME_LAST_CUT.ngc`** into the directory the job came from,
   containing only the uncut remainder.
4. Open that file. **Check the preview lands where the remaining cut belongs**
   before you do anything else - nothing in software knows whether the plate
   moved.
5. Check the consumables. The torch sat in the puddle with no post-flow.
6. CYCLE START.

The resume restarts at the *beginning* of the line that was executing, so the
partly cut segment is cut again from its start. That overlap is wanted: it gives
the new pierce some already-open kerf to join onto. Leadin is off by default for
the same reason - a leadin moves the pierce off the cut line, which is only
right if the material on that side is scrap.

RESUME CUT works just as well after an aborted cycle, a lost arc, or a job that
was paused and abandoned. It is not only for outages.

### By hand: RUN FROM LINE

For a job that was cut before `cut_recorder.py` was installed there is no
recording, so RESUME CUT has nothing to offer. Load the original file, find the
last shape that finished in the G-code window, click the line after it, and
press **RUN FROM LINE**.

That button was quietly broken on this machine until 2026-09-04. `dxf2ngc.py`
column-aligns its output as `X 598.409`, and QtPlasmaC's `get_rfl_pos()` returns
an empty string for anything with a space between the axis letter and its value.
An empty result is not treated as an error: the generated program simply has no
`G00 X.. Y..` before its `M03`, so the arc strikes wherever the machine is
standing and travels to the cut from there. `custom_filter.py` now closes those
spaces up in the filtered copy. `resume_cut.py` also refuses to hand over any
resume file whose first `M03` is not preceded by a positioning move, so that
class of fault cannot reach the torch silently again.

The filter fix does not reach every job. `run_from_line` is pointed at
`stat.file`, which is the filtered copy only when the file was opened through
the file manager. The **DXF** user button is not: `dxf2ngc.py` calls
`command.program_open()` directly, which bypasses `[FILTER]` entirely, so a job
loaded that way still has its `X 598.409` spacing and the GUI's RUN FROM LINE
button is still broken on it. `pick_shape.py` works around this by normalising
the program into a scratch copy of its own before `run_from_line` sees it -
line for line, so line numbers still match what is on screen. Doing the same
for the GUI's button would mean either dropping the column alignment in
`dxf2ngc.py`'s output or making the DXF button load through the filter.

---

## Cutting one shape instead of the whole part

**PICK SHAPE** (user button, `pick_shape.py`) is the same machinery pointed at
a job that has not gone wrong. It draws the loaded program's toolpath, you step
through the shapes with the arrow keys or click one, and it writes
`SELECTED_SHAPE.ngc` containing either that shape alone or that shape and
everything after it. A shape is one `M3 $0` ... `M5 $0` pair, labelled with the
`(* SHAPE Nr: n *)` comment when the file has them.

**LOAD INTO QTPLASMAC** hands the file straight to `program_open()`, the same
loader the DXF button uses, so the preview comes up and CYCLE START is the next
thing you press. That skips `[FILTER]`, which costs nothing here: the file is
assembled out of lines the filter has already been through, so the travel
clamp, the material change and the park call are already in them, and
`run_from_line` adds the safe-Z lift itself. **WRITE FILE ONLY** leaves it on
disk to be opened by hand instead.

It hands `run_from_line` the **M3 line**, not the positioning move above it.
`run_from_line_set()` rapids to the last commanded XY *before* the start line
and only uses the coordinates after it when the first move there is a `G00` -
which never happens here, because all travel on this machine is `G1` at 1000
mm/min. Starting at the positioning move therefore rapids back to the previous
shape's end point before travelling to the pierce; starting one line later
loses the `M3` and cuts the shape with the torch off. Starting at the `M3`
itself puts the pierce point in `codes['x1']`/`['y1']`, which is what is wanted.

Same rule as a resume before CYCLE START: check the preview lands where the
shape belongs on the plate.

---

## What none of this fixes

A UPS on the Pi and the Mesa card is the real answer to the outage itself. Even
a small one, holding up only the control side, turns a power cut into a clean
pause: the drives lose their enable and stop, LinuxCNC stays up, and the
resume comes from RAM instead of from a recording.

The other permanent gap is the lack of home switches. Everything in part 1 is
"jog to a corner and declare it" precisely because the machine has no absolute
reference of its own. Switches on X, Y and Z would remove the whole of part 1.
