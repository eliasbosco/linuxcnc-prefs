# Mild steel material set - where these numbers came from

Generated 2026-08-13. Keep this file: QtPlasmaC REWRITES
`cnc_plasma_cutter_material.cfg` whenever you save a material in the GUI, and
it strips comments, so the provenance cannot live in the cfg itself.

## Source

Hypertherm **Powermax65/85/105 SYNC Cut Charts Guide 810500MU rev 4**, metric
machine-torch tables:

- *Mild Steel - 65 A - Air*, "Best Quality" columns
- *Mild Steel - 45 A - Air*, "Best Quality" columns

These are **not** HBC65 data. No cut chart is published for the HBC65. The
Hypertherm figures are used as a structured starting point because the
amperage classes are comparable; a generic 65 A machine will usually cut a
little slower and with a wider kerf than Hypertherm at the same current.
**Every number below is a starting point to be tuned, not a target.**

## The binding constraint: 3000 mm/min

`[JOINT_0]` and `[JOINT_1]` MAX_VELOCITY = 50 mm/s = **3000 mm/min**. That is
the machine's hard ceiling for X/Y, and it is lower than most of the chart's
thin-material speeds:

| mm | Hypertherm 45 A best quality | reachable here? |
|----|------------------------------|-----------------|
| 1  | 8890 mm/min                  | no - 34% of it  |
| 2  | 6600 mm/min                  | no - 45% of it  |
| 3  | 3630 mm/min                  | no - 83% of it  |
| 4  | 2260 mm/min                  | yes             |
| 6  | 1240 mm/min                  | yes             |

Consequence for 1-3 mm: the correct response to being speed-limited is to
**lower the amperage**, not to run chart amps slowly. Chart amps at a speed
you cannot reach dumps too much heat into thin sheet and gives a wide kerf,
heavy dross and a bevelled edge. Entries 1-3 are therefore set to reduced
amps at just under the ceiling (2900, leaving a little headroom for corner
deceleration), and those amps are **extrapolated, not chart values**.

If thin sheet still cuts poorly, the real fix is FineCut consumables, which
are designed for exactly this case.

## Cut height stays at 1.0 mm - deliberately

The Hypertherm charts specify 3.2 mm cut height. That is **not** copied here.
It is matched to Hypertherm shielded consumables, and cut height is the main
driver of arc voltage - copying it would invalidate every CUT_VOLTS value.
1.0 mm is the value already proven on this machine.

If you ever change CUT_HEIGHT, **all the CUT_VOLTS values shift** and must be
re-measured. Higher torch = higher voltage.

## CUT_VOLTS - anchored on one real measurement

Only one point is measured: **4 mm at 40 A read 126.1 V** (thcad_arc_log.sh,
2026-08-13 17:23, 41 samples above 100 V, range 114-132 V while the cut
settled). The Hypertherm 65 A chart lists 128 V at 4 mm - a 1.5% agreement
that independently corroborates the THCAD calibration.

Everything thicker uses that 126 V anchor plus the chart's thickness delta
(65 A column: 8 mm +2, 10 mm +4, 12 mm +6, 16 mm +12, 20 mm +18).

Entries 1-3 are set flat at 126 V because there is no basis to taper them -
those are placeholders, not estimates.

**CUT_VOLTS only matters when auto-volts is OFF.** `Use auto volts = True` in
the prefs right now, so plasmac samples the real arc voltage after the arc
establishes and uses that as the THC target. Before you ever turn auto-volts
off, measure each material with `./thcad_arc_log.sh` and put the real number
in - a wrong CUT_VOLTS drives the torch at 0.1 mm per volt of error, so being
26 V out commands a 2.6 mm height change into a 1.0 mm cut height.

## KERF_WIDTH - measure it, do not trust it

Scaled from the chart but narrowed, because a generic nozzle at these amps
cuts a narrower kerf than Hypertherm's. Kerf directly sets part dimensions
via the CAM offset, so measure it: cut a 100 mm square, measure it, and the
difference from 100 is the kerf error.

## Pierce heights

Chart uses 120% of cut height (200% for 16 mm+). At a 1.0 mm cut height that
would be 1.2 mm, which is too low to keep blowback off the shield, so 3.0 mm
is kept - the value already in use here - rising to 3.5/4.0 for 12-20 mm.

## Per-entry notes

| # | material | amps | speed | source |
|---|----------|------|-------|--------|
| 0 | Basic default | 40 | 3000 | your existing tuned entry, untouched |
| 1 | MS 1 mm | 30 | 2900 | **extrapolated** - speed limited |
| 2 | MS 2 mm | 35 | 2900 | **extrapolated** - speed limited |
| 3 | MS 3 mm | 40 | 2900 | **extrapolated** - speed limited |
| 4 | MS 4 mm | 45 | 2600 | chart 45 A = 2260 best / 3400 production |
| 5 | MS 6 mm | 55 | 2000 | between chart 45 A (1240) and 65 A (2570) |
| 6 | MS 8 mm | 65 | 1550 | chart 65 A best quality |
| 7 | MS 10 mm | 65 | 1040 | chart 65 A best quality |
| 8 | MS 12 mm | 65 | 840 | chart 65 A best quality |
| 9 | MS 16 mm | 65 | 560 | chart 65 A, pierce is marginal at this thickness |
| 10 | MS 20 mm | 65 | 380 | chart 65 A - **EDGE START ONLY, do not pierce** |

16 mm is near the practical pierce limit for a 65 A machine. 20 mm is beyond
it: the chart specifies edge start, so lead in from the edge of the plate.
Piercing 20 mm floods the shield with molten metal and destroys consumables.

## Tuning order

1. Set amps to the **nozzle rating**, not the plate. A 45 A nozzle at 65 A
   erodes fast, widens the kerf and wanders.
2. Adjust speed by dross: a fine bead that snaps off is right; thick clingy
   dross underneath means too slow; the cut trailing behind or not breaking
   through means too fast.
3. Then measure kerf and correct the CAM offset.
4. Then measure CUT_VOLTS with thcad_arc_log.sh if you intend to disable
   auto-volts.
