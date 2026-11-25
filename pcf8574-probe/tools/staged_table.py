"""Staged switch-on table on edgetest (mode 4). usage: staged_table.py <port> [short]

  port   serial port of the controller (115200 baud)
  short  any second argument selects a shorter list of tests

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

Question tested: when several solenoids of expander 0x21 (8-15) are switched off and then
back on, does bringing them back in two stages about 90 microseconds apart, instead of all
at once, change how often the expander resets? Each test is 20 trials: the pattern is on
for 5 ms, then one I2C write carries either [00][pattern] (mode 1, all back at once) or
[00][first stage][pattern] (mode 4).

Prints the firmware's READY line, then one line per test: its name, the byte sequence
(pattern>00>[first stage>]pattern) and resets/20 (or the raw reply if it has no reset
count), and finally the read-back of both ports after switching everything off."""

import sys, serial, time

# Opening the port resets the controller; its READY line is read below.
p = serial.Serial(sys.argv[1], 115200, timeout=0.3)


def rl(t=30):
    """Read one reply line from the firmware.

    t: maximum time to wait, in seconds.
    Returns the text received up to the first line end (empty if nothing came in time)."""
    end = time.time() + t
    b = b""
    while time.time() < end and b"\n" not in b:
        b += p.read(64)
    return b.decode("ascii", "replace").strip()


# The READY line printed by the firmware after its reset, and the time of day.
print(rl(5), time.strftime("%H:%M:%S"))
# Tests: (name, pattern in hex, firmware mode, first-stage byte in hex or None).
# Patterns are bits of expander 0x21: 7E = outputs 1-6 (six), 3E = 1-5 (five),
# 1E = 1-4 (four), 0E = 1-3 (three), 06 = 1-2 (two), 78 = 3-6 (four).
# Mode 1 brings the whole pattern back at once; mode 4 brings the first-stage byte back
# first, then the full pattern. The last entry repeats "4 then 2" as a consistency check.
tests = [
    ("six at once", "7E", 1, None),
    ("3 then 3", "7E", 4, "0E"),
    ("4 then 2", "7E", 4, "1E"),
    ("4 then 2 (other four)", "7E", 4, "78"),
    ("2 then 4", "7E", 4, "06"),
    ("5 then 1", "7E", 4, "3E"),
    ("five: 3 then 2", "3E", 4, "0E"),
    ("four: 3 then 1", "1E", 4, "0E"),
    ("four at once", "1E", 1, None),
    ("three at once", "0E", 1, None),
    ("4 then 2, again", "7E", 4, "1E"),
]
# Short list: both "4 then 2" variants and the repeat, plus three of the reference rows.
if len(sys.argv) > 2:
    tests = [
        t
        for t in tests
        if t[0].startswith("4 then 2") or t[0] in ("six at once", "3 then 3", "three at once")
    ]
for name, pat, mode, mid in tests:
    # 't' command: expander 21, pattern, off byte 00, mode, gap 0 (unused), 5000 us on,
    # 20 trials, 30 ms rest, and the first-stage byte when there is one.
    c = "t 21 %s 00 %d 0 5000 20 30%s" % (pat, mode, " " + mid if mid else "")
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    r = rl()
    f = r.split()
    print(
        "%-26s %s>00>%s%s   %s/20"
        % (
            name,
            pat,
            (mid + ">") if mid else "",
            pat,
            f[f.index("resets") + 1] if "resets" in f else r,
        )
    )
# Switch everything off ('z', reply discarded), then print the read-back of both ports.
p.write(b"z\n")
rl(3)
p.write(b"r\n")
print(rl(3))
