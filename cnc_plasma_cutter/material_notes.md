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

### 2026-09-07 - anchor re-tuned to 1200 mm/min at 1.5/3.5 mm, whole table rescaled

MS 6 mm was re-tuned at the machine to **kerf 1.5, cut height 1.5, pierce
height 3.5, pierce delay 0.5 s, 1200 mm/min, 120 V**. That entry is the anchor
and was left byte-identical; every other entry is derived from it below.

`Float Switch Travel` also moved **5.15 -> 5.70** in the prefs at the same time,
so the physical standoff barely changed even though CUT_HEIGHT dropped:

    real standoff (old) = 2.0 + 5.15 - 5.70 = 1.45 mm
    real standoff (new) = 1.5 + 5.70 - 5.70 = 1.50 mm

In other words the 2.0 mm of the previous entry was never 2.0 mm of air - it
was 1.45 - and the new 1.5 mm mostly just writes down what was already being
cut. Declared travel now equals measured travel, so cut height is standoff.

**PIERCE_HEIGHT is the real height change: 1.95 mm real -> 3.5 mm.** Pierce is
back to 2.33x cut height, which finally answers the warning left open on
2026-09-05 that pierce had collapsed onto the cutting standoff with no blowback
clearance. Flat 3.5 on all 20 entries.

#### CUT_SPEED - factor chain from the chart is now a round 0.60

The anchor moved 950 -> 1200, an extra **x1.2632**, and the chain collapses to
something suspiciously tidy:

    0.625 x 0.8 x 0.95 x 1.2632 = 0.60      (chart 6 mm 2000 x 0.60 = 1200)

| # | material | chart | was | now |
|---|----------|-------|-----|-----|
| 6 | MS 8 mm  | 1550  | 737 | 930 |
| 7 | MS 10 mm | 1040  | 494 | 624 |
| 8 | MS 12 mm |  840  | 399 | 504 |
| 9 | MS 16 mm |  560  | 266 | 336 |
| 10| MS 20 mm |  380  | 182 | 228 |
| 17| AL 6 mm  |   -   | 950 |1200 | = MS 6 mm, per the aluminium rule
| 18| AL 8 mm  |   -   | 737 | 930 | = MS 8 mm
| 19| AL 10 mm |   -   | 494 | 624 | = MS 10 mm

**The speed-limited entries went 1000 -> 1200, which is new.** Since 2026-09-04
entries 0-4 and 11-16 have been pinned at 1000 mm/min because that is the
X-screw ceiling, not a cutting speed. The anchor is now *above* that ceiling,
so leaving them at 1000 would command thin sheet **slower** than 6 mm plate -
backwards, and exactly the "more heat per millimetre into thin sheet at a fixed
dial current" failure the binding-constraint section warns about. So every entry
whose chart-derived speed exceeds 1200 is now set to 1200, the same
over-command the anchor carries. MS 4 mm (chart 2600 x 0.6 = 1560) and AL 5 mm
(interpolated 1380) fall in that group too.

Entry 0 keeps 1000. It has no thickness, so there is nothing to scale, and 1000
is the speed the machine can actually guarantee in any direction.

#### 1200 mm/min is not reachable along X - read this before trusting the anchor

`[JOINT_0] MAX_VELOCITY = 16.666667` mm/s = **1000 mm/min**, and the comment
above it is emphatic about why (X screw whip, three reverted attempts). Y is not
limited - `[JOINT_1]` is 100 mm/s. So LinuxCNC clamps an F1200 cut to 1000
mm/min on any X-dominant segment and runs the full 1200 on Y-dominant ones. On a
45-degree move the vector tops out near 1414 mm/min but X still caps its own
component.

Two consequences:

1. **Whether the 1200 anchor is real depends on the direction of the test cut.**
   If the 6 mm test piece was cut along X, the torch was actually moving at
   1000 mm/min and "1200" is the number that was typed, not the number that
   severed. If it was along Y, or a circle, 1200 is real for part of the path.
   Re-cut the 6 mm test along X and along Y and compare the dross - if they
   differ, the anchor is a Y-only figure and the honest anchor is 1000.
2. **Direction-dependent cut quality is now baked into the whole thin end.**
   Every entry from 1200 down to MS 8 mm's 930 is at or above the X ceiling or
   close under it, so the same part will cut hotter on its X edges than its Y
   edges. Nothing in the config can fix this; only the mechanical fixes listed
   in the `[JOINT_0]` comment can.

Note also that `Arc Fail Timeout` went 3.0 -> 10.0 in the prefs at the same
time. That is a long time to sit with the torch firing and no arc detected -
it papers over transfer failures rather than reporting them. Worth putting back
to 3.0 once pierce height 3.5 has proved itself.

#### PIERCE_DELAY - 0.0833 s per mm

The anchor took 0.6 -> 0.5 s at 6 mm, so the previous clean 0.1 s/mm ramp
becomes **0.5/6 = 0.0833 s/mm**, applied by thickness:

| mm | 0.5 | 1 | 2 | 3 | 4 | 6 | 8 | 10 | 12 | 16 | 20 |
|----|-----|---|---|---|---|---|---|----|----|----|----|
| s  |0.05 |0.08|0.17|0.25|0.33|**0.5**|0.67|0.83|1.0|1.33|1.67|

AL uses the same ramp as MS now, since both are pure functions of thickness.

**MS 16 mm went 1.6 -> 1.33 s.** This is the second time proportionality has
eroded that entry's padding (it was 2.0 originally). It is named "pierce limit"
for a reason. If motion starts before breakthrough, put it back to 2.0 - and
note that with a 1.0 mm nozzle this entry is unusable anyway (see the nozzle
finding), so the delay is academic until a 1.1 mm nozzle is fitted.

#### KERF_WIDTH - scaled x0.882 and floored at the orifice

Kerf moved 1.7 -> 1.5 at the anchor, a factor of 0.882. As on 2026-09-05,
literal proportionality against thickness is not used - the sub-linear ramp is
scaled as a whole and then clipped at the physical floor from the nozzle
finding, ~1.3x a 1.0 mm orifice = **1.3 mm minimum**:

| mm  | 1 | 2 | 3 | 4 | 6 | 8 | 10 | 12 | 16 | 20 |
|-----|---|---|---|---|---|---|----|----|----|----|
| was |1.1|1.3|1.5|1.6|1.7|1.8|1.9 |2.0 |2.3 |2.5 |
| x.882|0.97|1.15|1.32|1.41|1.50|1.59|1.68|1.76|2.03|2.21|
| now |**1.3**|**1.3**|1.3|1.4|**1.5**|1.6|1.7 |1.8 |2.0 |2.2 |

The flat spot at 1-3 mm is deliberate and is a fix, not an artefact: the
2026-09-05 nozzle finding flagged entries 1 and 2 (1.1 and 1.3) as below the
width a 1.0 mm orifice can physically cut. They are now at the floor.

AL still follows **MS + 0.1** by thickness: 1.4 up to 3 mm, then 1.5, 1.6, 1.6,
1.7, 1.8. Entry 0 keeps its 1.0, which is also below the floor - it is left
alone by the same rule that leaves its speed alone, and it is a default, not a
material. `dxf2ngc.py` still does no kerf compensation, so none of this column
reaches a cut path today.

#### CUT_VOLTS - the column rebased 126 -> 120, and it very nearly checks out

Every non-anchor MS value was "126 V anchor + the chart's thickness delta". The
anchor is now 120, so the whole column drops 6 V and keeps its deltas:

| mm | 1-4 | 6 | 8 | 10 | 12 | 16 | 20 |
|----|-----|---|---|----|----|----|----|
| delta from anchor | 0 | 0 | +2 | +4 | +6 | +12 | +18 |
| now | 120 |**120**| 122 | 124 | 126 | 132 | 138 |

Worth noticing: cut height dropped 0.5 mm real (1.95 -> 1.50 by the standoff
arithmetic above is pierce; cut went 1.45 -> 1.50, but the *declared* height
went 2.0 -> 1.5), and at `Height Per Volt = 0.1` a 0.5 mm reduction is -5 V.
126 - 5 = 121, against a hand-tuned 120. That is the first time a voltage
number in this file has agreed with anything by construction rather than by
coincidence. It is **not** a calibration - see the retraction above, there is
still no measured voltage anchor - but the direction and magnitude are right.

AL keeps **MS + 10 V**: 130 through 6 mm, then 132 and 134.

Still inert while `Use auto volts = True`. Unchanged advice: re-measure with
`./thcad_arc_log.sh` at the new 1.5 mm cut height before disabling auto-volts.

#### CUT_AMPS - untouched, again

Display-only on this machine (the real current is the HBC65 front dial), the
anchor did not move it, and the nozzle finding says the 65 A entries are
aspirational regardless. Nothing to scale.

#### Puddle jump has room to work now

`puddle_jump_height` is a **percentage of pierce height**. At 3.5 pierce and
1.5 cut, anything at or below **43%** lands under the cut height and does
nothing - against 80% under the old 2.5/2.0 pair. So the useful band is much
wider than it was: start near 70% (2.45 mm) with a short delay if pierces
splash the shield.

#### Test order for this table

1. **Re-cut 6 mm along X and along Y.** This is the one that decides whether
   1200 is a real anchor or a Y-only number. Everything else here is scaled
   from it.
2. 8 mm at 930, by dross.
3. 4 mm at 1200 - and note the 2026-08-23 log wanted 4 mm tested near 2280,
   which the X ceiling still forbids.
4. Only then kerf, and only then voltage.

### 2026-09-07 (later) - MS 3 mm measured at 2000 mm/min; there are now TWO anchors

MS 3 mm was tuned at the machine to **kerf 1.2, pierce height 3.0, pierce delay
0.3 s, cut height 1.5, 2000 mm/min, 38 A**. Entries 1, 2, 4 mm were re-derived
from it and a new **MS 5 mm (MATERIAL_NUMBER_20)** was added. MS 6 mm and
everything above it was left alone.

`Arc Fail Timeout` is back to 3.0 - the 10 s of the previous entry is gone.

#### The two anchors disagree, and the chart loses

This file has measured two thicknesses on this machine now, and they do not
agree on any single scale factor against the Hypertherm 45 A column:

| anchor | measured | chart | ratio |
|--------|----------|-------|-------|
| 3 mm   | 2000     | 3630  | 0.551 |
| 6 mm   | 1200     | 1240  | 0.968 |

Scaling the chart by the new 3 mm factor - the obvious reading of "rescale
proportionally" - would put 6 mm at **683 mm/min**, against 1200 measured. That
is not a small discrepancy, it is a factor of 1.76, so the chart's *shape*
across 3-6 mm is simply wrong for this torch. The 2026-08-23 note that "the
torch is behaving like the 45 A column" held at 6 mm and does **not** hold at
3 mm; the real machine falls off much faster with thickness than Hypertherm
does.

So speed is no longer chart-derived at all in the 1-6 mm band. It is a power
law fitted through the two measured points:

    speed(t) = 2000 x (t/3)^-0.737          (-0.737 = log2(1200/2000))

which reproduces both anchors exactly by construction and needs no factor
chain. The 0.60 chart factor from the earlier entry today now applies only to
8 mm and up, which has never been measured.

| mm | power law | chart x 0.551 would give | set to |
|----|-----------|--------------------------|--------|
| 1  | 4494      | 4898                     | **2000** (capped) |
| 2  | 2697      | 3636                     | **2000** (capped) |
| 3  | 2000      | 2000                     | **2000** (anchor) |
| 4  | 1618      | 1245                     | **1618** |
| 5  | 1373      | -                        | **1373** |
| 6  | 1200      | 683                      | 1200 (anchor, untouched) |

For comparison, a constant-power model (speed x thickness = const) predicts
1000 at 6 mm from the 3 mm anchor - closer than the chart, but still 17% under
the measurement. The two-point fit is the only derivation that respects both
numbers actually cut on this machine.

#### The speed cap is 2000, and the X ceiling problem is now much worse

Derived 1 mm is 4494 mm/min. It is set to **2000** instead - the anchor's own
figure, because nothing on this machine has been proven to cut above 2000 and
guessing 4494 for the thinnest, least forgiving material is the wrong direction
to guess in.

`[JOINT_0] MAX_VELOCITY` is **still 1000 mm/min** (unchanged; the screw-whip
comment in the ini stands). So the mismatch flagged in the earlier entry today
has doubled:

| entry | commanded | actual on X | actual on Y | ratio |
|-------|-----------|-------------|-------------|-------|
| MS 1/2/3 mm | 2000 | 1000 | 2000 | **2:1** |
| MS 4 mm     | 1618 | 1000 | 1618 | 1.6:1 |
| MS 5 mm     | 1373 | 1000 | 1373 | 1.4:1 |
| MS 6 mm     | 1200 | 1000 | 1200 | 1.2:1 |

`[JOINT_1]` is 100 mm/s = 6000 mm/min, so the Y figures are all genuinely
reachable - this is a real 2:1 speed difference between the X and Y edges of
the same part at 1-3 mm, not a theoretical one. **A square cut in 3 mm will
have two good edges and two edges cut at half the intended speed.** Expect
noticeably heavier dross on the X-direction edges.

**This means the 2000 anchor is almost certainly a Y-direction measurement.**
If the 3 mm test cut ran along X, the torch was moving at 1000 mm/min and 2000
is just the number in the box. Either way the derivation above is anchored on
whatever really happened, so: re-cut 3 mm as an L or a square and compare the
X edge against the Y edge. If they match, X is not actually clamping and the
ini needs looking at. If they differ, the honest table for X-dominant work
tops out at 1000 and the only fix is mechanical (anti-whip follower, bigger
screw, or belt/rack on X - see the `[JOINT_0]` comment).

#### The other columns

Below the 3 mm anchor the anchor's own flat/ramp rules apply. For 4 and 5 mm,
which are *bracketed* by two measurements, values are interpolated between the
two anchors rather than extrapolated from one - that is what keeps 4 mm from
contradicting 6 mm the way the chart did.

| | 1 mm | 2 mm | 3 mm | 4 mm | 5 mm | 6 mm |
|---|---|---|---|---|---|---|
| KERF_WIDTH    | 1.1 | 1.1 | **1.2** | 1.3 | 1.4 | **1.5** |
| PIERCE_HEIGHT | 3.0 | 3.0 | **3.0** | 3.2 | 3.3 | **3.5** |
| PIERCE_DELAY  | 0.1 | 0.2 | **0.3** | 0.37| 0.43| **0.5** |
| CUT_HEIGHT    | 1.5 | 1.5 | **1.5** | 1.5 | 1.5 | **1.5** |
| CUT_AMPS      | 28  | 33  | **38**  | 44  | 49  | **55**  |

(bold = measured at the machine)

**KERF_WIDTH** - the measured 1.2 at 3 mm **retracts the 1.3 mm floor** asserted
in the 2026-09-05 nozzle finding. That floor was inferred from "kerf bottoms out
at ~1.3x the orifice"; a real 1.2 mm kerf on a 1.0 mm nozzle says the multiplier
is nearer 1.2x here. 1 and 2 mm are set to 1.1 (1.1x orifice), which is about as
low as kerf can physically go, rather than the sub-1.0 values literal scaling
would give. Still unmeasured, still uncompensated - `dxf2ngc.py` does no kerf
offset.

**PIERCE_HEIGHT** - the anchor took it 3.5 -> 3.0, so the flat 3.5 set this
morning is no longer flat. It now ramps 3.0 (1-3 mm) to 3.5 (6 mm+). That is
defensible - thin plate needs less blowback clearance - but note that **only
entries 1-4 and the new 5 mm moved.** 8-20 mm and all of aluminium are still at
3.5 on this morning's flat rule, which was itself untested. If you want the
whole table on a 3 mm-anchored ramp, say so and it can go through in one pass.

**PIERCE_DELAY** - 0.1 s/mm at the thin end, which is exactly the ramp this file
carried before this morning, so the 3 mm anchor has effectively restored it.
4 and 5 mm interpolate to the anchor's slower 0.0833 s/mm at 6 mm.

**CUT_AMPS is display-only** (the real current is the HBC65 front dial), so
these are a record of the dial, not a command. Two things to note anyway: the
anchor moved 40 -> 38 at 3 mm, and **the interpolated 5 mm value of 49 A
exceeds the ~45 A cap** the nozzle finding set for a 1.0 mm orifice. Run 5 mm
at 45 A on the dial regardless of what the entry says, or fit a 1.1 mm nozzle.

**CUT_VOLTS** - 120 at both anchors, so flat 120 across 1-6 mm, unchanged. Still
inert while `Use auto volts = True`, still no measured voltage anchor.

Also normalised `PIERCE_HEIGHT = 3.0000000000000107` on the anchor to `3.0`.
That is a QtPlasmaC spinbox float artefact, not a tuned value - same class of
noise as the `Arc Fail Timeout = 3.0000000000000204` in the prefs.

#### MS 5 mm is MATERIAL_NUMBER_20, so it sorts last in the GUI

There was no free slot between MS 4 mm (4) and MS 6 mm (5) - the MS set owns
0-10 and aluminium owns 11-19 - so the new entry went on the end at 20.
Consequence: **it appears after AL 10mm in the material dropdown, not between
4 mm and 6 mm.** Renumbering to put it in thickness order would shift every
aluminium entry and break any `M190 P<n>` already sitting in saved G-code, so it
was not done. 21 sections, numbers 0-20, parses clean.

#### Test order

1. **3 mm as an L or a square** - X edge against Y edge. This decides whether
   2000 is real or a Y-only figure, and every speed from 1 to 5 mm hangs off it.
2. 5 mm at 1373, dial at 45 A - it is the only entirely new entry here.
3. 4 mm at 1618. The 2026-08-23 log wanted 4 mm near 2280; the two-point fit
   says 1618 and the fit is now better evidence than the chart was.
4. 1 mm at 2000 last, and watch for the arc trailing - 2000 is a cap, not a
   derivation, and the power law wanted more than twice that.
