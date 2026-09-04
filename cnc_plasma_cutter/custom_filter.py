"""
Canonicalise axis words, hold non-cutting travel to 1000 mm/min, and append the
park move to every job.

QtPlasmaC runs every loaded file through /usr/bin/qtplasmac_gcode
([FILTER] ngc in the INI). That filter looks for custom_filter.py beside the
INI and, if present, exec()s it before processing the file. We use that hook
three times, all in write_gcode(), the filter's final step:

  0. "X 598.409" becomes "X598.409". LinuxCNC does not care - whitespace inside
     a word is legal g-code and the interpreter reads either spelling - but
     QtPlasmaC's own RUN FROM LINE does. It finds the last commanded position
     with plasmac/run_from_line.py's get_rfl_pos(), which walks the line
     character by character and gives up the moment the character after the
     axis letter is not part of a number:

         get_rfl_pos("G01 X598.409 Y73.409 F1000", "", "X") -> "598.409"
         get_rfl_pos("G01 X 598.409 Y  73.409 F1000", "", "X") -> ""

     An empty answer is not reported as an error. run_from_line_set() simply
     omits the "G00 X.. Y.." that positions the torch at the start of the
     resumed cut, so the generated program fires M03 wherever the machine
     happens to be standing and then arcs away from there. A leadin cannot be
     calculated either - float("") raises, which is the only symptom that ever
     reaches the operator.

     dxf2ngc.py column-aligns its output ("X 598.409", "I   1.591"), and
     qtplasmac_gcode preserves that spacing, so every DXF-derived job on this
     machine hit this. The alignment is worth keeping in the .ngc that is
     written to disk and read by a human; it is not worth keeping in the
     filtered copy that only the interpreter and run_from_line ever see. So the
     space between an axis letter and its value is removed here, which fixes
     the GUI's RUN FROM LINE button and resume_cut.py at the same time.

  1. Rapids become feed moves at 1000 mm/min. LinuxCNC has no rapid feed rate
     setting - G0 runs at whatever the participating joints allow, which here
     is 1500 mm/min on X and 6000 on Y and Z. Lowering those limits is not an
     option: they also cap cutting, and the material file asks for up to 3000
     mm/min. So each G0 is rewritten as G1 F1000, the same trick park.ngc uses
     and the same 1000 mm/min as the jog rate in [DISPLAY]. Cutting moves are
     untouched. The feed override slider scales travel now that it is a feed
     move, as it does any G1.

     This only covers travel that comes through the filter, which is the XY
     traverse between cuts and the initial move to safe Z. The Z drop to pierce
     height is not a G0 at all - plasmac owns it, at Setup Feed Rate - and the
     GUI's own framing and "go to origin" buttons issue G0 by MDI, bypassing
     the filter, so those still run at the joint limits.

  2. "o<park> call" is inserted ahead of the program end code, so a completed
     job finishes with the torch lifted to machine Z0 and the gantry back at
     X0 Y0 - the same thing the PARK user button does.

All three run in write_gcode() rather than the per-line custom_post_parse()
hook because write_gcode() sees the whole output. For the park call that covers
every way a program can end:

  - M02 / M30 / %          the normal cases
  - the M02 that pierce-only mode appends after process_file()
  - no end code at all     the park call simply lands last
  - an already filtered file, re-loaded (the call is already there; skip it)

Only completed programs park. Aborting or pausing a job leaves the torch where
it stopped, which is what you want when recovering a cut.

For the travel rewrite it means the parsed output is what gets rewritten, and
that output is well behaved in two ways this relies on: parse_code() prefixes a
bare coordinate line with the modal G code, so every motion line carries an
explicit G00 or G01 and no modal state has to be tracked here; and G codes are
zero padded. The one rapid that skips parse_code() is set_first_move()'s
"G53 G0 Z[...]", so both spellings are matched. A gcodeList entry can also hold
embedded newlines, so entries are split before being examined.

Modal feed is restored after a travel move, lazily: the saved F word is
re-emitted just before the next move that would otherwise inherit F1000, and
only when that move does not set its own feed. Without it, a cut following a
travel would run at 1000 mm/min instead of the material's cut speed, since
CUT_SPEED reaches the g-code as a modal F word
(F#<_hal[plasmac.cut-feed-rate]>) that a G1 travel move would consume. Files
already filtered once are passed through unchanged by process_file(), and a
rewritten line has no G0 left to match, so both passes are idempotent.

Two scoping traps, because the filter exec()s this file inside
Filter.__init__ rather than importing it:

  - A bare "def write_gcode(self)" here lands in that method's local scope and
    never reaches the class, so the patch is assigned onto Filter explicitly.
  - Names defined at the top of this file also land in that local scope, so the
    patched method cannot see them at call time -- its __globals__ is
    qtplasmac_gcode's, which knows nothing about this file. Everything the
    method needs is therefore local to it: helpers and constants are nested,
    and the original method is captured as a default argument (evaluated at def
    time, while Filter is still in scope).
"""


def _slow_travel_and_park(self, _original=Filter.write_gcode):  # noqa: F821
    import re

    # Travel feed, mm/min. Kept equal to the jog rate in [DISPLAY] and to
    # park.ngc's park_feed, so every non-cutting move on this machine runs at
    # the same speed.
    travel_feed = 1000

    park_call = 'o<park> call (park at end of job)'

    # A G code at a code position: not part of a longer number and not inside a
    # parameter name. G0 and G00 are rapids; G1 G2 G3 and their padded forms
    # move at the modal feed.
    rapid_code = re.compile(r'(?<![A-Z0-9_.<#])G0*0(?![0-9])')
    feed_code = re.compile(r'(?<![A-Z0-9_.<#])G0*[123](?![0-9])')
    # An F word: a literal, a parameter such as F#<_hal[plasmac.cut-feed-rate]>,
    # or a bracketed expression.
    feed_word = re.compile(r'F\s*(?:#<[^>]*>|\[[^\]]*\]|[0-9.]+)')
    # Whitespace between a word letter and the number that follows it. The
    # lookahead is deliberately limited to the start of a plain number: a value
    # that begins with '#' or '[' is a parameter or an expression, which
    # get_rfl_pos() reads correctly with or without the space, and joining
    # those up would gain nothing while touching more lines than necessary.
    # '$' is excluded for the same reason, which is what keeps plasmac's
    # "M03 $0 S1" tool syntax exactly as it was.
    padded_word = re.compile(r'(?<![A-Z0-9_.<#])([A-Z])[ \t]+(?=[-+.0-9])')

    def split_comment(line):
        """Split a line into its code and its trailing comment, at whichever
        comment character comes first."""
        cut = len(line)
        for tag in ';(':
            found = line.find(tag)
            if found != -1:
                cut = min(cut, found)
        return line[:cut], line[cut:]

    def canonical_words(lines):
        """Close up "X 598.409" to "X598.409", in the code half of each line.

        Only the code half: a comment such as "(* SHAPE Nr: 9 *)" is left
        alone, and so is anything after a ';'.
        """
        out = []
        for line in lines:
            code, comment = split_comment(line)
            fixed = padded_word.sub(r'\1', code)
            out.append(fixed + comment if fixed != code else line)
        return out

    def slow_travel(lines):
        out = []
        last_feed = None
        restore_pending = False
        for line in lines:
            code, comment = split_comment(line)
            feed = feed_word.search(code)
            if feed:
                # The program sets the modal feed itself here, so nothing is
                # owed even if a travel move came before it.
                last_feed = feed.group(0)
                restore_pending = False
            moves = any(axis in code for axis in 'XYZABCUVW')
            if rapid_code.search(code) and moves:
                code = rapid_code.sub('G01', code, count=1)
                code = feed_word.sub('', code).rstrip()
                gap = ' ' if comment else ''
                out.append(f'{code} F{travel_feed}{gap}{comment}')
                restore_pending = last_feed is not None
                continue
            if restore_pending and feed_code.search(code) and moves:
                if not feed:
                    out.append(f'{last_feed} (restore feed after travel)')
                restore_pending = False
            out.append(line)
        return out

    def append_park(lines):
        def program_end(line):
            """True if this line ends the program. G and M codes are already
            upper case and zero padded by the time they reach write_gcode()."""
            code = line.strip()
            return code[:3] in ('M02', 'M30') or code[:1] == '%'

        if any('o<park>' in line.lower() for line in lines):
            return lines
        for index in range(len(lines) - 1, -1, -1):
            if program_end(lines[index]):
                lines.insert(index, park_call)
                break
        else:
            lines.append(park_call)
        return lines

    lines = []
    for entry in self.gcodeList:
        lines.extend(entry.split('\n'))
    self.gcodeList = append_park(slow_travel(canonical_words(lines)))
    _original(self)


Filter.write_gcode = _slow_travel_and_park  # noqa: F821
