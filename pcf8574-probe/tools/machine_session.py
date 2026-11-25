#!/usr/bin/env python3
"""Laptop-only test session for the AYAB interface on the machine.
Needs only pyserial and the 'machine' sketch flashed on the controller.

  machine_session.py <serial port> [--quick] [--soak N]

  serial port  port of the controller (115200 baud)
  --quick      100 writes per table cell instead of 300
  --soak N     number of writes in the final soak run (default 3000)

It writes a timestamped log next to itself and prints a summary table:
for several numbers of energised solenoids, and several ways of writing
(native, and two-byte with different first bytes, 09 being what the AYAB
firmware sends), how many writes read back wrong.
Solenoids are energised in bursts of a couple of seconds with pauses between.

More precisely, the log file machine_session_<date>_<time>.log is created in the current
working directory. It receives everything printed plus every command sent and every reply.

Firmware needed on the board: machine (../machine/src/main.cpp). The script uses its
commands 'r' (read both ports), 'v' (controller supply in mV) and
'b N AAAA BBBB D S PP' (burst of N writes alternating between the 16-bit states AAAA and
BBBB, D ms apart, read back after each write; S=0 one data byte per expander, S=1 two
bytes [PP][data]). In a 16-bit state the low byte goes to expander 0x20 (solenoids 0-7)
and the high byte to 0x21 (solenoids 8-15).

The script stops early, with exit status 1, if the sketch does not answer or if the two
expanders are not both found on the bus."""

import sys, time, datetime, serial

# Command line. 'soak' is the number of writes of the final soak run; N is the number of
# writes in each cell of the table.
port = sys.argv[1]
quick = "--quick" in sys.argv
soak = int(sys.argv[sys.argv.index("--soak") + 1]) if "--soak" in sys.argv else 3000
N = 100 if quick else 300
log = open("machine_session_%s.log" % datetime.datetime.now().strftime("%Y%m%d_%H%M%S"), "w")


def out(s=""):
    """Print a line and append it to the log file.

    s: the text, without line end (default: an empty line)."""
    print(s)
    log.write(s + "\n")
    log.flush()


# Opening the port resets the controller; its READY line is read further down.
p = serial.Serial(port, 115200, timeout=0.2)
# (command, reply) pairs for every reply that contained READY, see cmd().
restarts = []


def readline(t):
    """Read from the serial port until a line end arrives or t seconds have passed.

    t: maximum time to wait, in seconds.
    Returns the text received, with surrounding white space removed (empty if nothing)."""
    end = time.time() + t
    buf = b""
    while time.time() < end:
        buf += p.read(64)
        if b"\n" in buf:
            break
    return buf.decode("ascii", "replace").strip()


def cmd(c, t=5):
    """Send one command line to the sketch, log it with its reply, and return the reply.

    c: command text without the line end.
    t: maximum time to wait for the reply, in seconds.
    A reply containing "READY" means the controller restarted instead of answering; it is
    remembered in 'restarts' for the summary."""
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    r = readline(t)
    log.write("%s  > %s\n%s  < %s\n" % (time.strftime("%H:%M:%S"), c, time.strftime("%H:%M:%S"), r))
    log.flush()
    if "READY" in r:
        restarts.append((c, r))
    return r


def field(r, name, default=-1):
    """Extract the integer that follows a keyword in a reply line.

    r:       reply line from the sketch, for example "OK b writes 300 mismatches 2 ...".
    name:    the keyword, for example "mismatches".
    default: value returned when the keyword is absent (-1 unless given)."""
    f = r.split()
    return int(f[f.index(name) + 1]) if name in f else default


# Start of the session: title, then the READY line of the sketch (waited for up to 5 s).
out(
    "AYAB interface machine session, %s, port %s"
    % (datetime.datetime.now().isoformat(timespec="seconds"), port)
)
ready = readline(5)
out("controller: " + ready)
if "READY" not in ready:
    out('No READY line: is the "machine" sketch flashed?')
    sys.exit(1)
# The READY line lists, between the words "acks" and "init", the I2C addresses that
# answered the bus scan. Both expanders, 20 and 21, and nothing else are expected.
f = ready.split()
acks = f[f.index("acks") + 1 : f.index("init")] if "acks" in f and "init" in f else []
out("  I2C addresses answering: %s   (expected: 20 21)" % (" ".join(acks) or "none"))
out("  read-back with all off: " + cmd("r"))
out("  controller supply: " + cmd("v") + " mV")
if acks != ["20", "21"]:
    out("STOPPING: the two PCF8574s were not both found.")
    sys.exit(1)

# 16-bit states to test, by increasing number of solenoids on:
#   8000 = solenoid 15 (1 on)             8002 = 1 and 15 (2 on)
#   8606 = 1, 2, 9, 10, 15 (5 on)         B636 = 1, 2, 4, 5, 9, 10, 12, 13, 15 (9 on)
#   F676 = B636 plus 6 and 14 (11 on)     FFFF = all 16
# Solenoid 0 is off in all but the last because each burst toggles it (see below).
patterns = [0x8000, 0x8002, 0x8606, 0xB636, 0xF676, 0xFFFF]
# Ways of writing: (column heading, S field of the 'b' command, first byte in hex).
# "native" is a single data byte per expander. The others send two bytes per expander, the
# first byte being 00, 09, 11 or FF and the second the data.
styles = [
    ("native", 0, 0x00),
    ("[00][data]", 1, 0x00),
    ("[09][data] AYAB", 1, 0x09),
    ("[11][data]", 1, 0x11),
    ("[FF][data]", 1, 0xFF),
]
out(
    "\nEach cell: writes that read back wrong, out of %d (in brackets: how many showed a whole port at FF)."
    % N
)
out("%-22s" % "solenoids on" + "".join("%-20s" % s[0] for s in styles))
# total_bad: wrong read-backs over the whole session. worst: the cell with the most wrong
# read-backs, as (count, solenoids on, style name, reply line), or None.
total_bad = 0
worst = None
for a in patterns:
    # k = number of solenoids on in state a (the row label).
    k = bin(a).count("1")
    row = "%-22s" % ("%2d  (state %04X)" % (k, a))
    for name, two, pfx in styles:
        # Burst of N writes alternating between state a and the same state with solenoid 0
        # toggled (a ^ 0x0001), 5 ms apart. The reply can take a while: 30 s timeout.
        r = cmd("b %d %04X %04X 5 %d %02X" % (N, a, a ^ 0x0001, two, pfx), 30)
        # bad = writes that read back wrong; ah = how many ports read FF when something
        # else was written; wn, rn = writes and reads not acknowledged. -1 = field absent.
        bad, ah, wn, rn = (
            field(r, "mismatches"),
            field(r, "portAllHigh"),
            field(r, "writeNak"),
            field(r, "readNak"),
        )
        cell = "?" if bad < 0 else "%d (%d)" % (bad, ah)
        if wn > 0 or rn > 0:
            cell += " nak %d/%d" % (wn, rn)
        row += "%-20s" % cell
        if bad > 0:
            total_bad += bad
            if worst is None or bad > worst[0]:
                worst = (bad, k, name, r)
        # Pause between bursts, in seconds, with everything off (a burst ends all off).
        time.sleep(0.6)
    out(row)
# Soak: one long burst, two-byte writes with first byte 09, alternating between F676 and
# F677 (11 or 12 solenoids on, solenoid 0 toggling), 3 ms apart, up to 120 s for the reply.
out("\nSoak: %d writes of [09][data] with 11 solenoids on ..." % soak)
r = cmd("b %d F676 F677 3 1 09" % soak, 120)
out("  " + r)
# A missing "mismatches" field (-1) is counted as 0 here.
total_bad += max(0, field(r, "mismatches"))
out("  controller supply afterwards: " + cmd("v") + " mV;  read-back: " + cmd("r"))
# Summary, also written to the log.
out("\nSUMMARY")
out("  wrong read-backs in total: %d" % total_bad)
if worst:
    out("  worst cell: %d wrong with %d solenoids on, style %s\n    %s" % worst)
out("  controller restarts seen during the session: %d" % len(restarts))
for c, r in restarts:
    out('    after "%s": %s' % (c, r))
out("  log saved as " + log.name)
