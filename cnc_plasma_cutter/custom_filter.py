"""
Append the park move to the end of every job.

QtPlasmaC runs every loaded file through /usr/bin/qtplasmac_gcode
([FILTER] ngc in the INI). That filter looks for custom_filter.py beside the
INI and, if present, exec()s it before processing the file. We use that hook to
insert "o<park> call" ahead of the program end code, so a completed job always
finishes with the torch lifted to machine Z0 and the gantry back at X0 Y0 --
the same thing the PARK user button does.

The insertion happens in write_gcode(), the filter's final step, rather than in
the per-line custom_post_parse() hook, because write_gcode() sees the whole
output. That covers every way a program can end:

  - M02 / M30 / %          the normal cases
  - the M02 that pierce-only mode appends after process_file()
  - no end code at all     the park call simply lands last
  - an already filtered file, re-loaded (the call is already there; skip it)

Only completed programs park. Aborting or pausing a job leaves the torch where
it stopped, which is what you want when recovering a cut.

Two scoping traps, because the filter exec()s this file inside
Filter.__init__ rather than importing it:

  - A bare "def write_gcode(self)" here lands in that method's local scope and
    never reaches the class, so the patch is assigned onto Filter explicitly.
  - Names defined at the top of this file also land in that local scope, so the
    patched method cannot see them at call time -- its __globals__ is
    qtplasmac_gcode's, which knows nothing about this file. Everything the
    method needs is therefore local to it: the helper is nested, and the
    original method is captured as a default argument (evaluated at def time,
    while Filter is still in scope).
"""


def _park_before_program_end(self, _original=Filter.write_gcode):  # noqa: F821
    park_call = 'o<park> call (park at end of job)'

    def program_end(line):
        """True if this line ends the program. G and M codes are already upper
        case and zero padded by the time they reach write_gcode()."""
        code = line.strip()
        return code[:3] in ('M02', 'M30') or code[:1] == '%'

    if not any('o<park>' in line.lower() for line in self.gcodeList):
        for index in range(len(self.gcodeList) - 1, -1, -1):
            if program_end(self.gcodeList[index]):
                self.gcodeList.insert(index, park_call)
                break
        else:
            self.gcodeList.append(park_call)
    _original(self)


Filter.write_gcode = _park_before_program_end  # noqa: F821
