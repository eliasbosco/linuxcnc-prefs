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

## Cut height: 2.5 mm everywhere (changed 2026-08-23) - SUPERSEDED

Twice over: by the 5.3 mm anchor of 2026-09-05, then by the float-travel fix
later the same day that made heights physical. Cut height is now 2.0 mm real.

Went 1.0 -> 2.0 -> 2.5 mm across 2026-08-23, on every entry. The Hypertherm
charts specify 3.2 mm, which is still **not** copied here - that figure is
matched to Hypertherm shielded consumables - but 2.5 mm is now most of the way
there.

Cut height is the main driver of arc voltage, so **every CUT_VOLTS value below
is now stale**. They were measured or derived at 1.0 mm, and at 0.1 mm per volt
the 1.5 mm rise is roughly +15 V. Nothing is broken today because
`Use auto volts = True` makes plasmac sample the real arc voltage and ignore
CUT_VOLTS entirely. Re-measure every entry with `./thcad_arc_log.sh` before you
ever turn auto-volts off, or the THC will drive the torch about 1 mm low.

## CUT_VOLTS - anchored on one real measurement - ANCHOR RETRACTED

The measurement below predates the real float switch by a day; see the final
2026-09-05 entry. Read this section as history, not as a calibration.

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

## Pierce heights: 4.0 mm everywhere (changed 2026-08-23) - SUPERSEDED

See both 2026-09-05 entries. Pierce height is now 2.5 mm real.

Chart uses 120% of cut height (200% for 16 mm+), which even at the new 2.5 mm
cut height would be 3.0 mm - too low to keep blowback off the shield. A flat
4.0 mm is now used on every entry, replacing the old 3.0 mm with 3.5/4.0 for
12-20 mm. PIERCE_DELAY is unchanged and was tuned at 3.0 mm, so the thin
entries (1-3 mm, at 0.1-0.3 s) have the least margin: a higher pierce takes
slightly longer to transfer, so watch for motion starting before breakthrough.

## Per-entry notes

| # | material | amps | speed | source |
|---|----------|------|-------|--------|
| 0 | Basic default | 40 | 3000 | your existing tuned entry, untouched |
| 1 | MS 1 mm | 30 | 2900 | **extrapolated** - still at the X/Y ceiling |
| 2 | MS 2 mm | 35 | 2900 | **extrapolated** - still at the X/Y ceiling |
| 3 | MS 3 mm | 40 | 2900 | **extrapolated** - still at the X/Y ceiling |
| 4 | MS 4 mm | 45 | 1625 | chart 2600 x 0.625 - likely slow, see tuning log |
| 5 | MS 6 mm | 55 | 1250 | **measured on this machine** - the anchor |
| 6 | MS 8 mm | 65 | 970 | chart 1550 x 0.625 |
| 7 | MS 10 mm | 65 | 650 | chart 1040 x 0.625 |
| 8 | MS 12 mm | 65 | 525 | chart 840 x 0.625 |
| 9 | MS 16 mm | 65 | 350 | chart 560 x 0.625, pierce marginal at this thickness |
| 10 | MS 20 mm | 65 | 240 | chart 380 x 0.625 - **EDGE START ONLY, do not pierce** |
| 11 | AL 0.5 mm | 25 | 2900 | **extrapolated** - ceiling, turn the dial down |
| 12 | AL 1 mm | 30 | 2900 | **extrapolated** - ceiling, turn the dial down |
| 13 | AL 2 mm | 35 | 2900 | **extrapolated** - X/Y ceiling |
| 14 | AL 3 mm | 40 | 2900 | **extrapolated** - X/Y ceiling |
| 15 | AL 4 mm | 45 | 1625 | = MS 4 mm |
| 16 | AL 5 mm | 50 | 1440 | interpolated between MS 4 mm and MS 6 mm |
| 17 | AL 6 mm | 55 | 1250 | = MS 6 mm |
| 18 | AL 8 mm | 65 | 970 | = MS 8 mm |
| 19 | AL 10 mm | 65 | 650 | = MS 10 mm |

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

## Aluminium (entries 11-19, added 2026-08-23)

**Every aluminium number here is extrapolated from the mild steel set. None of
it is chart data** - no aluminium air cut chart was used, because none was to
hand that matches this torch.

Speeds are set to the **mild steel speed for the same thickness**, with no speed
bonus, and 5 mm is interpolated between MS 4 mm and MS 6 mm. Aluminium usually
cuts at or slightly above the mild steel speed for the same thickness, so these
are deliberately on the slow side: too slow gives dross, which is recoverable,
while too fast fails to sever, which is the expensive mistake. Walk each one up
in 100 mm/min steps and stop one step before the cut starts trailing.

Derived from the mild steel entries as follows:

- **KERF_WIDTH** = MS kerf + 0.1 mm. A guess. Measure it - cut a 100 mm square
  and the difference from 100 is the kerf error.
- **PIERCE_DELAY** a clean monotonic ramp 0.1 s to 1.0 s. Note this does *not*
  copy the MS ramp, which is non-monotonic (8 mm sits at 0.5 s, below 6 mm's
  0.6 s) - that looks like an artefact in the steel set rather than intent.
- **CUT_VOLTS** = MS + 10 V, because aluminium runs a higher arc voltage at the
  same standoff. **Placeholder only.** Every CUT_VOLTS in this file is already
  stale (see the cut height section), and these were never measured at all.
- **CUT_AMPS** mirrors the MS entry, and is inert either way - see the note on
  the dial below.

Two aluminium-specific things:

**Puddle jump is the first thing to try if pierces splash the shield.** It is
disabled (0.0) on every entry here, matching the rest of the file. The plasmac
component's pin metadata defines `puddle_jump_height` as a **percentage of
pierce height**, not a distance - so with pierce height at 4.0 mm and cut height
at 2.5 mm, anything at or below 62.5% lands at or under the cut height and does
nothing. Start around 85% (3.4 mm) with a short `PUDDLE_JUMP_DELAY`.

**Ohmic probing does not work on aluminium** - the oxide layer is an insulator.
Not an issue today (`Ohmic probe enable = False`, float switch only), but do not
enable ohmic sensing and expect it to find aluminium.

## Tuning log

### 2026-08-23 - MS 6mm calibrated at 1250 mm/min, table rescaled twice

First cuts in real 6 mm mild steel. At the original 2000 mm/min the arc reached
only 3-4 mm of the 6 mm and sparks blew back over the top of the plate - the
signature of not enough energy per unit length. That 2000 was never a chart
value: it was a linear interpolation between the 45 A (1240) and 65 A (2570)
columns at a nominal 55 A, and interpolating across amperage classes is
optimistic for a torch that is not a Hypertherm.

Hand tuning at the machine went 2000 -> 900 (severed, too slow) -> **1250**,
which is where it stands. Pierce height 4.0 mm was set on every entry along the
way, and cut height went 1.0 -> 2.0 -> 2.5 mm. The chart-derived speeds were
rescaled by the anchor's correction factor:

    1250 / 2000 = 0.625

| # | thickness | chart | now |
|---|-----------|-------|------|
| 4 | 4 mm      | 2600  | 1625 |
| 6 | 8 mm      | 1550  |  970 |
| 7 | 10 mm     | 1040  |  650 |
| 8 | 12 mm     |  840  |  525 |
| 9 | 16 mm     |  560  |  350 |
| 10| 20 mm     |  380  |  240 |

Entries 0-3 are **not** scaled, deliberately. Their speeds are not cutting
speeds - they are the X/Y velocity ceiling of 3000 mm/min (2900 with corner
headroom), because the chart wants 3630-8890 mm/min there and the gantry cannot
deliver it. Multiplying a ceiling by 0.625 would just dump 60% more heat per
millimetre into thin sheet at a fixed dial current, which is the exact failure
the "binding constraint" section above warns about.

### The anchor now matches the 45 A chart almost exactly

Worth noticing: the calibrated 1250 mm/min sits within **1%** of the Hypertherm
45 A best-quality figure for 6 mm, which is 1240. Ratio 1.008.

That is a useful result. It says the torch is behaving like the 45 A column, so
for 1-6 mm the 45 A chart can be read more or less directly instead of being
scaled, and it corroborates the dial sitting near 45 A.

It also flags **MS 4 mm as probably too slow**. The proportional scaling gives
1625, but the 45 A chart says 2260 for 4 mm, which at the 1.008 ratio is about
2280 - some 40% faster. The scaled value is conservative because the original
2600 had been pushed above the chart's best-quality figure toward the production
figure of 3400, so scaling it down inherited that distortion. Test 4 mm nearer
2280.

An earlier version of this log suggested testing 3 mm at ~2600. **That is
superseded.** It was derived from the 900 mm/min anchor; at 1250 the 45 A chart
figure of 3630 scales to about 3660, which is above the 3000 mm/min ceiling, so
3 mm is genuinely still speed limited at 2900.

The 8 mm and thicker entries came from the **65 A** column, so scaling them by a
factor measured against a 45 A-behaving torch is a proxy, not a derivation.
Published 45 A charts stop well before 20 mm, so there was nothing better to
use. Treat 8 mm and up as the least trustworthy numbers in the file.

**CUT_AMPS is display-only on this machine.** In qtplasmac_handler.py the
`cut_amps` widget is wired solely to the `pmx485_*` Powermax RS-485 pins and its
tooltip is literally "Powermax cutting current". `[POWERMAX] Port` is empty, so
nothing reads CUT_AMPS except the statistics text. The real current is the
**dial on the HBC65 front panel**, and the 0.625 factor is only valid for
whatever the dial was set to during the 6 mm calibration. Move the dial and the
whole table needs rescaling.

**The anchor was measured at a 2.0 mm cut height, then the whole table moved to
2.5 mm.** The 1250 was not re-verified at the taller standoff. A 0.5 mm rise
spreads the arc column a little further before it reaches the plate, so if 6 mm
stops severing cleanly the anchor needs re-measuring and every scaled speed
moves with it. Re-cut the 6 mm test piece first, before trusting anything
derived from it.

Next: test MS 4 mm near 2280, then cut test pieces in 8 and 12 mm and adjust by
dross - a fine bead that snaps off is right, thick clingy dross underneath means
too slow, a cut that trails or does not break through means too fast.

### 2026-09-05 - anchor re-tuned to 950 mm/min, heights flattened to the anchor

MS 6 mm was re-tuned at the machine to **cut height 5.3 mm, pierce height
5.3 mm, 950 mm/min**. The whole table was then rebuilt on that anchor.

**Heights are now flat at 5.3 / 5.3 on all 20 entries**, superseding the
2.5 mm cut / 4.0 mm pierce of 2026-08-23. Note this makes pierce height equal
to cut height everywhere - the extra pierce standoff that the 4.0 mm flat was
introduced to provide is gone. See the warning at the end of this entry.

Every CUT_VOLTS is stale again, and more so than before: the 2.8 mm rise from
2.5 to 5.3 mm is roughly +28 V at 0.1 mm/V. Still inert while
`Use auto volts = True`. Do not disable auto-volts without re-measuring.

**CUT_SPEED** - the anchor moved 1000 -> 950, so the chart-derived speeds took
an additional x0.95. Full factor chain from chart is now 0.625 x 0.8 x 0.95 =
**0.475**.

| # | material | was | now | basis |
|---|----------|-----|-----|-------|
| 6 | MS 8 mm  | 776 | 737 | x0.95 |
| 7 | MS 10 mm | 520 | 494 | x0.95 |
| 8 | MS 12 mm | 420 | 399 | x0.95 |
| 9 | MS 16 mm | 280 | 266 | x0.95 |
| 10| MS 20 mm | 192 | 182 | x0.95 |
| 17| AL 6 mm  |1000 | 950 | = MS 6 mm, per the aluminium rule |
| 18| AL 8 mm  | 776 | 737 | = MS 8 mm |
| 19| AL 10 mm | 520 | 494 | = MS 10 mm |

Entries 0-4 and 11-16 were **not** scaled. They sit at the 1000 mm/min X-screw
ceiling, not at cutting speeds, for the reason given in the 2026-08-23 entry.
AL 6 mm did move, because it is not ceiling-limited - it tracks the MS 6 mm
anchor by the aluminium derivation rule, and only looked like a ceiling value
before because the anchor happened to equal the ceiling.

**PIERCE_DELAY** - now a clean **0.1 s per mm** off the anchor (6 mm = 0.6 s),
which fixes the non-monotonic artefacts flagged in the aluminium section:

| # | material | was | now |
|---|----------|-----|-----|
| 6 | MS 8 mm  | 0.5 | 0.8 |
| 7 | MS 10 mm | 0.7 | 1.0 |
| 9 | MS 16 mm | 2.0 | **1.6** |
| 11| AL 0.5 mm| 0.1 | 0.05 |

**KERF_WIDTH** - kerf did not move at the anchor (still 1.7 at 6 mm), so
proportional scaling leaves the ramp alone. Literal proportionality was **not**
applied: 1.7 at 6 mm scaled linearly would give 0.28 mm at 1 mm and 5.7 mm at
20 mm, which is not how kerf behaves. The existing sub-linear ramp was kept and
only its one flat spot corrected - **MS 8 mm 1.7 -> 1.8**, which had been equal
to the 6 mm value. AL kerf still follows MS + 0.1 and is unchanged throughout.

CUT_AMPS and CUT_VOLTS were deliberately left alone. Both are inert here - amps
is display-only (the real current is the HBC65 front dial) and volts is ignored
while auto-volts is on.

Entry 0 "Basic default Material" got the heights but not the other three: it
has no thickness, so there is nothing to scale proportionally.

**Two things to watch on the next cuts:**

1. **Pierce height now equals cut height on every entry.** Every pierce happens
   at the cutting standoff with no extra clearance. This is what the flat
   4.0 mm pierce existed to prevent - blowback onto the shield. Watch the
   consumables on 12-20 mm especially, where pierce is already marginal.
2. **MS 16 mm pierce delay dropped 2.0 -> 1.6 s.** That entry is named "pierce
   limit" for a reason and the 2.0 was probably deliberate padding. If motion
   starts before breakthrough, put it back to 2.0 - proportionality is the
   weaker argument at the pierce limit.

### 2026-09-05 (later) - float travel was wrong; heights are now real millimetres

**Everything above this entry that quotes a cut or pierce height in mm is in
"indicated" units, not physical standoff.** `Float Switch Travel` in
`cnc_plasma_cutter.prefs` was left at the QtPlasmaC default of 1.5 mm while the
torch's sprung slide actually travels **~5.15 mm** before the switch trips.
QtPlasmaC takes the material surface to be `Z_at_trip + Float Travel`, so an
under-declared travel parks the torch low by the difference:

    physical standoff = CUT_HEIGHT + declared_travel - actual_travel
            1.65 mm   =    5.3     +      1.5        -    5.15

That is how the anchor came to be "5.3 mm": it was the number that put a real
1.5-1.8 mm of air under the nozzle. The 3.65 mm error is mechanical, not probe
overshoot - at Probe Feed Rate 350 mm/min into 800 mm/s^2 the stopping distance
is 0.02 mm, and `db_float.delay = 5` adds 0.03 mm.

**Float Travel is now set to 5.15**, so cut height means millimetres again, and
all 20 entries were reset to the measured optimum:

| | was (indicated) | now (real mm) |
|---|---|---|
| CUT_HEIGHT    | 5.3 | **2.0** |
| PIERCE_HEIGHT | 5.3 | **2.5** |

Both halves of this change must move together. Setting Float Travel without
rescaling the heights, or vice versa, puts the torch 3.65 mm out.

Pierce is now 1.25x cut height rather than the ~2x convention. That was tuned at
the machine on thin plate and is fine there; if 12-20 mm pierces splash the
shield, raise PIERCE_HEIGHT on those entries specifically rather than the whole
table, and try puddle jump (see the aluminium section - it is a *percentage of
pierce height*, so with 2.5/2.0 anything at or below 80% does nothing).

**The ohmic trap this was hiding is now closed.** Ohmic probing detects the
surface exactly and gets no float-travel correction, so under the old 1.5 mm
declaration enabling ohmic would have commanded 5.3 + 1.5 = 6.8 mm of real
standoff - far too high for the arc to transfer. With Float Travel correct,
the float and ohmic paths now agree and `Ohmic Probe Offset = 0.0` is right.

### The nozzle is 1.0 mm - this torch is a 45 A torch

Measured on a **new** nozzle, 2026-09-05. Orifice diameter sets the current
rating at roughly 55-60 A/mm^2, and 1.0 mm is exactly Hypertherm's 45 A orifice
(65 A is 1.1 mm, 85 A is 1.2 mm, 105 A is 1.3 mm).

This is hardware confirmation of the inference in the 2026-08-23 entry, which
reached "the torch is behaving like the 45 A column" from the speed ratio alone.
Consequences:

1. **Cap the HBC65 front dial at ~45 A**, 50 A absolute. Past that the orifice
   erodes into a bell mouth in minutes - wide kerf, wandering arc, double-arcing
   onto the shield. This is tuning rule #1 with a number attached.
2. **Entries 6-10 (MS 8/10/12/16/20 mm) need a bigger nozzle.** Their speeds are
   scaled from the Hypertherm *65 A* column and their CUT_AMPS say 65. At 45 A
   the real limits are ~6-8 mm quality and ~12 mm sever; 16 and 20 mm are out of
   reach. Fit a 1.1 mm nozzle for thick work or treat those entries as unusable.
   Same for AL 8/10 mm (18-19).
3. **The thin-end KERF_WIDTH values are below the physical floor.** Kerf bottoms
   out around 1.3-1.6x the orifice, so ~1.3 mm minimum here; entries 1 and 2
   claim 1.1 and 1.3. Low impact today - `dxf2ngc.py` does no kerf compensation
   at all, so KERF_WIDTH only feeds QtPlasmaC's conversational shapes and stats.

### The CUT_VOLTS anchor is not corroborated after all

The 126.1 V measurement (`thcad_arc_26-08-13_17-23-13.log`) was taken on
**2026-08-13**. The real float switch went live in commit `cee3c33` on
**2026-08-14** - one day later. That reading was therefore taken with the
bench-test float simulation active, which probed to a virtual material top, so
the physical standoff during that cut is unknown.

The "1.5% agreement with the Hypertherm 65 A chart" claimed in the CUT_VOLTS
section above is coincidence, not corroboration - it cannot confirm the THCAD
calibration, because the height it was measured at is not known. There is
currently **no trustworthy voltage anchor in this file.** Still inert while
`Use auto volts = True`; re-measure every entry with `./thcad_arc_log.sh` at the
new 2.0 mm cut height before ever turning auto-volts off.
