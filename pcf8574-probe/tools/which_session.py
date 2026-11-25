#!/usr/bin/env python3
"""Which outputs must be switched back on to reset the expander.

Usage: which_session.py <port> <label> [out.json]

  port      serial port of the controller (115200 baud)
  label     free text printed at the start and stored in the JSON file
  out.json  optional file that receives the results

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

Runs a fixed list of sequences on expander 0x21 (solenoids 8-15), 20 trials each. A
sequence is: a start byte left on for 5 ms, then an 'off' byte, then, for most rows, a
'back' byte written straight after (about 0.2 ms later). The rows vary how many outputs
go off, how many come back, and whether they are the same ones. One line is printed per
row: description, the three bytes as start>off>back, and the number of trials out of 20
that ended with the port reading FF (a reset); "other N" is added when N trials read back
wrong in another way, and the raw reply when it could not be parsed (shown as -1/20).
The JSON file holds {label, rows}, one row {desc, pat, off, back, resets, other, raw}."""

import sys, time, json, serial

port, label = sys.argv[1], sys.argv[2]
outf = sys.argv[3] if len(sys.argv) > 3 else None
# Opening the port resets the controller: wait for it to start, then drop its READY line.
p = serial.Serial(port, 115200, timeout=0.2)
time.sleep(2.5)
p.reset_input_buffer()


def cmd(c, t=60):
    """Send one command line to the firmware and return its reply line.

    c: command text without the line end.
    t: maximum time to wait for the reply, in seconds.
    Pending input is discarded first. Returns the text received up to the first line end
    (empty if nothing came in time)."""
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    end = time.time() + t
    b = b""
    while time.time() < end and b"\n" not in b:
        b += p.read(64)
    return b.decode("ascii", "replace").strip()


# The sequences. Bytes are bit patterns on expander 0x21: bit k set = output k on.
# 0x0F = outputs 0-3, 0xF0 = outputs 4-7, 0x7F = outputs 0-6, 0x7E = outputs 1-6.
# "toggled" rows switch some outputs off and back on while the others stay on throughout:
# for example 7F > 78 > 7F switches outputs 0-2 off and on again while 3-6 stay on.
# "from cold" rows start with nothing on, so the 'back' write is a plain switch-on.
# "one write" rows have no 'back' byte: the change is made by the 'off' write alone and
# the port is left there.
rows = [  # description, start, off, back (None = leave at 'off')
    ("4 off, same 4 back on", 0x0F, 0x00, 0x0F),
    ("4 off, other 4 on", 0x0F, 0x00, 0xF0),
    ("4 off, 1 back on", 0x0F, 0x00, 0x01),
    ("4 off, 2 back on", 0x0F, 0x00, 0x03),
    ("4 off, 3 back on", 0x0F, 0x00, 0x07),
    ("4 off, 5 on (4 same + 1 new)", 0x0F, 0x00, 0x1F),
    ("7 off, 4 back on", 0x7F, 0x00, 0x0F),
    ("7 off, 3 back on", 0x7F, 0x00, 0x07),
    ("3 toggled, 3 held on", 0x7E, 0x70, 0x7E),
    ("3 toggled, 4 held on", 0x7F, 0x78, 0x7F),
    ("4 toggled, 3 held on", 0x7F, 0x70, 0x7F),
    ("2 toggled, 5 held on", 0x7F, 0x7C, 0x7F),
    ("1 toggled, 6 held on", 0x7F, 0x7E, 0x7F),
    ("from cold: 4 on", 0x00, 0x00, 0x0F),
    ("from cold: 7 on", 0x00, 0x00, 0x7F),
    ("one write: 4 off + other 4 on", 0x0F, 0xF0, None),
    ("one write: 4 on, 3 more added", 0x0F, 0x7F, None),
]
# Header: label, time of day, read-back of both ports and controller supply in mV.
print(label, time.strftime("[%H:%M:%S]"))
print("controller state:", cmd("r", 3), cmd("v", 3))
print(
    "bank 8-15, resets out of 20; start pattern on 5 ms, then off byte, then (0.2 ms later) back byte\n%-32s%-14s%s"
    % ("", "start>off>back", "resets")
)
# Results for the optional JSON file.
res = dict(label=label, rows=[])
for d, pat, off, back in rows:
    # Build the 't' command: expander 21, start byte, off byte, mode, gap 0, 5000 us on,
    # 20 trials, 30 ms rest. Mode 2 (off, then 'back' as a second write) when there is a
    # back byte, which is then appended as the ninth field; mode 0 (off and leave) if not.
    c = "t 21 %02X %02X %d 0 5000 20 30" % (pat, off, 0 if back is None else 2) + (
        "" if back is None else " %02X" % back
    )
    r = cmd(c)
    f = r.split()
    # n = resets, o = other wrong read-backs; both -1 if the reply lacks those fields.
    try:
        n = int(f[f.index("resets") + 1])
        o = int(f[f.index("other") + 1])
    except ValueError:
        n = o = -1
    print(
        "%-32s%-14s%d/20%s"
        % (
            d,
            "%02X>%02X>%s" % (pat, off, "--" if back is None else "%02X" % back),
            n,
            "  other %d" % o if o else "",
        )
        + ("  " + r if n < 0 else ""),
        flush=True,
    )
    res["rows"].append(dict(desc=d, pat=pat, off=off, back=back, resets=n, other=o, raw=r))
# Leave everything off and show the read-back.
print("all off:", cmd("z", 3), cmd("r", 3))
if outf:
    json.dump(res, open(outf, "w"), indent=1)
