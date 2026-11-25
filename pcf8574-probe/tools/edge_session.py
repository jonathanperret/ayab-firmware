#!/usr/bin/env python3
"""Drive the 'edgetest' sketch through one named experiment and print a table.

usage: edge_session.py <port> <experiment> <label> [out.json]

  port        serial port of the controller (115200 baud)
  experiment  one of: edge, threshold, ontime, stagger (anything else runs no trials)
  label       free text printed as the title of the run and stored in the JSON file
  out.json    optional file that receives all the results

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

Every trial switches a pattern of solenoids on, on one expander only, waits, then performs
a switching event (off, off and back on, ...). The firmware reads the port back afterwards;
a read-back of FF that was not asked for counts as a reset of the expander. Each table cell
is "resets/trials", followed by "+X odd" when X trials read back wrong in some other way.

The four experiments:
  edge       which event resets the chip: switching off only, or off and back on after
             various gaps; three patterns on each expander
  threshold  how many solenoids must switch together: 1 to 7 on, on each expander
  ontime     how long the solenoids must have been on before the event (expander 0x21 only)
  stagger    whether switching the solenoids off one at a time, with a gap between them,
             avoids the reset (expander 0x21 only)

Output: the title, the firmware's READY line and supply reading, one table, and a closing
line with the final state. With out.json, a dictionary {experiment, label, rows} is also
written; each row holds the pattern and the list of per-cell result dictionaries."""

import sys, time, json, serial

# Command line: serial port, experiment name, free-text label, optional JSON output file.
port, exp, label = sys.argv[1], sys.argv[2], sys.argv[3]
outf = sys.argv[4] if len(sys.argv) > 4 else None
# Opening the port resets the controller; its READY line is read further down.
# The 0.2 s timeout is only the granularity of the polling loops below.
p = serial.Serial(port, 115200, timeout=0.2)


def readline(t):
    """Read from the serial port until a line end arrives or t seconds have passed.

    t: maximum time to wait, in seconds.
    Returns everything received, as text with surrounding white space removed. It is an
    empty string if nothing arrived, and can hold more than one line if several arrived in
    the same read."""
    end = time.time() + t
    buf = b""
    while time.time() < end:
        buf += p.read(64)
        if b"\n" in buf:
            break
    return buf.decode("ascii", "replace").strip()


def cmd(c, t=60):
    """Send one command line to the firmware and return its reply line.

    c: command text without the line end, for example "v" or "t 21 0F 00 0 0 5000 20 30".
    t: maximum time to wait for the reply, in seconds. A 't' command only answers once all
       its trials are done, hence the long default.
    Anything still waiting in the input buffer is thrown away first."""
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    return readline(t)


def trial(addr, pat, off, mode, gap, on_us, n=20, cool=30):
    """Run n identical trials on one expander with the firmware's 't' command.

    addr:  I2C address of the expander under test, 0x20 (solenoids 0-7) or 0x21 (8-15).
    pat:   byte switched on at the start of each trial (bit k set = output k on).
    off:   byte written at the event to switch off (0x00 = everything off).
    mode:  0 = switch off and leave off; 1 = off and back on within one two-byte write,
           about 90 microseconds apart; 2 = off, wait 'gap', back on (two writes);
           3 = switch the solenoids of the pattern off one at a time, 'gap' apart.
    gap:   gap in microseconds, used by modes 2 and 3 only.
    on_us: time the pattern stays on before the event, in microseconds.
    n:     number of trials.
    cool:  rest between trials with everything off, in milliseconds.

    Returns a dictionary with the counters reported by the firmware: resets (port read FF
    unasked), other (any other wrong read-back), wnak (writes not acknowledged), dirty
    (trials that did not start from all-off), plus n. If the reply cannot be parsed, all
    four counters are -1 and the reply text is kept under 'raw'."""
    r = cmd("t %02X %02X %02X %d %d %d %d %d" % (addr, pat, off, mode, gap, on_us, n, cool))
    f = r.split()
    try:
        return dict(
            resets=int(f[f.index("resets") + 1]),
            other=int(f[f.index("other") + 1]),
            wnak=int(f[f.index("wnak") + 1]),
            dirty=int(f[f.index("dirty") + 1]),
            n=n,
        )
    except ValueError:
        return dict(resets=-1, other=-1, wnak=-1, dirty=-1, n=n, raw=r)


def cell(d):
    """Format one result of trial() as a table cell: "resets/trials".

    d: dictionary returned by trial().
    " +X odd" is appended when X trials read back wrong without being a reset."""
    s = "%d/%d" % (d["resets"], d["n"])
    if d["other"]:
        s += " +%d odd" % d["other"]
    return s


# Header of the run: label and time of day, the READY line the firmware printed after the
# reset caused by opening the port (waited for up to 5 s), and the controller supply (mV).
print("%s  [%s]" % (label, time.strftime("%H:%M:%S")))
print("controller:", readline(5))
print("supply reading:", cmd("v"))
# The two expanders as (I2C address, name used in the tables). 0x21 is tested first.
BANKS = ((0x21, "bank 8-15"), (0x20, "bank 0-7"))
# Everything that goes into the optional JSON file.
res = dict(experiment=exp, label=label, rows=[])


def bits(x):
    """Return the number of bits set in x, that is the number of solenoids a pattern
    switches on."""
    return bin(x).count("1")


if exp == "edge":
    # Which edge resets the chip? Pattern on for 5 ms, then: off only / off and back on after a gap.
    # Columns: (heading, firmware mode, gap in microseconds). The headings give the total
    # time between off and back on; in mode 2 that is the gap plus about 0.2 ms for the
    # write itself. The gap is not used by modes 0 and 1.
    cols = [
        ("off only", 0, 0),
        ("back on ~90us", 1, 0),
        ("~0.3ms", 2, 100),
        ("~1ms", 2, 800),
        ("~3ms", 2, 2800),
        ("~10ms", 2, 9800),
        ("~30ms", 2, 29800),
    ]
    print(
        "resets out of 20 trials; pattern on for 5 ms first\n%-22s" % ""
        + "".join("%-15s" % c[0] for c in cols)
    )
    for addr, bname in BANKS:
        # 0x86 = outputs 1, 2, 7 (3 on); 0xB6 = 1, 2, 4, 5, 7 (5 on);
        # 0xF6 = 1, 2, 4, 5, 6, 7 (6 on). Output numbers count within the expander.
        for pat in (0x86, 0xB6, 0xF6):
            row = "%-22s" % ("%s, %d on (%02X)" % (bname, bits(pat), pat))
            cells = []
            for name, mode, gap in cols:
                # Off byte 00, pattern on for 5000 us, default 20 trials and 30 ms rest.
                d = trial(addr, pat, 0x00, mode, gap, 5000)
                cells.append(d)
                row += "%-15s" % cell(d)
            print(row)
            res["rows"].append(
                dict(bank=bname, pat=pat, on=bits(pat), cols=[c[0] for c in cols], cells=cells)
            )
elif exp == "threshold":
    # How many must switch at once, on each bank? Lowest k outputs of the bank.
    # Columns: (heading, firmware mode). Mode 0 = off only, mode 1 = off and back on in
    # one two-byte write.
    cols = [("off only", 0), ("off, back on ~90us", 1)]
    print(
        "resets out of 20 trials; pattern on for 5 ms first\n%-22s" % ""
        + "".join("%-22s" % c[0] for c in cols)
    )
    for addr, bname in BANKS:
        # 0x01 to 0x7F are the lowest 1 to 7 outputs. 0xFE is outputs 1 to 7: a second
        # 7-output row that leaves out output 0 instead of output 7.
        for pat in (0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFE):
            row = "%-22s" % ("%s, %d on (%02X)" % (bname, bits(pat), pat))
            cells = []
            for name, mode in cols:
                d = trial(addr, pat, 0x00, mode, 0, 5000)
                cells.append(d)
                row += "%-22s" % cell(d)
            print(row)
            res["rows"].append(
                dict(bank=bname, pat=pat, on=bits(pat), cols=[c[0] for c in cols], cells=cells)
            )
elif exp == "ontime":
    # How long must the solenoids have been on?
    # Times the pattern is left on before the event, in microseconds (0.1 ms to 100 ms).
    times = [100, 300, 1000, 2000, 5000, 10000, 30000, 100000]
    print(
        "resets out of 20 trials, bank 8-15, by time the pattern was on before the event\n%-30s"
        % ""
        + "".join("%-9s" % ("%gms" % (t / 1000)) for t in times)
    )
    # Patterns with 5 and 6 outputs on (see the 'edge' experiment), expander 0x21 only.
    for pat in (0xB6, 0xF6):
        for name, mode in (("off only", 0), ("off, back on ~90us", 1)):
            row = "%-30s" % ("%d on (%02X), %s" % (bits(pat), pat, name))
            cells = []
            for t in times:
                # Here the rest between trials is 40 ms instead of the default 30 ms.
                d = trial(0x21, pat, 0x00, mode, 0, t, cool=40)
                cells.append(d)
                row += "%-9s" % cell(d)
            print(row)
            res["rows"].append(dict(pat=pat, on=bits(pat), mode=name, times=times, cells=cells))
elif exp == "stagger":
    # Does switching off one solenoid at a time avoid it, and how far apart must they be?
    # Extra wait after each single switch-off, in microseconds (mode 3).
    gaps = [0, 200, 500, 1000, 2000, 5000]
    print(
        "resets out of 20 trials, bank 8-15: solenoids switched off one at a time, by extra gap between them\n(each write itself takes about 0.2 ms)\n%-16s"
        % ""
        + "%-12s" % "all at once"
        + "".join("%-9s" % ("+%gms" % (g / 1000)) for g in gaps)
    )
    # 0xB6 = 5 on, 0xF6 = 6 on, 0xFE = outputs 1 to 7 (7 on).
    for pat in (0xB6, 0xF6, 0xFE):
        # First cell: everything off in a single write (mode 0), for comparison.
        d0 = trial(0x21, pat, 0x00, 0, 0, 5000)
        row = "%-16s%-12s" % ("%d on (%02X)" % (bits(pat), pat), cell(d0))
        cells = [d0]
        for g in gaps:
            # Mode 3: one write per solenoid, g microseconds apart.
            d = trial(0x21, pat, 0x00, 3, g, 5000)
            cells.append(d)
            row += "%-9s" % cell(d)
        print(row)
        res["rows"].append(dict(pat=pat, on=bits(pat), gaps=gaps, cells=cells))
# Leave everything off, then show the read-back of both ports (should be 0000) and the
# supply once more.
print("all off:", cmd("z"), "| read-back:", cmd("r"), "| supply reading:", cmd("v"))
if outf:
    json.dump(res, open(outf, "w"), indent=1)
