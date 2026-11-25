#!/usr/bin/env python3
"""How late can outputs come back on and still reset the expander.

Usage: window_session.py <port> <label> <out.json>

  port      serial port of the controller (115200 baud)
  label     free text printed at the start
  out.json  file that receives the results (required)

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

On expander 0x21 (solenoids 8-15): a pattern is left on for a given time, switched off,
and switched back on after an extra gap of 0 to 10 ms (the write itself adds about
0.2 ms). 10 trials per cell. Prints one row per (pattern, on time) and one column per gap;
each cell is the number of trials that ended with the port reading FF (a reset), or -1 if
the firmware's reply could not be read.
The JSON file is a list of {pat, on_us, gaps, resets}, one per row."""

import sys, time, json, serial

port, label, outf = sys.argv[1:4]
# Opening the port resets the controller: wait for it to start before sending anything.
p = serial.Serial(port, 115200, timeout=0.2)
time.sleep(2.5)


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


# Extra wait between the switch-off and the switch-on, in microseconds (table columns).
gaps = [0, 100, 300, 600, 1000, 1500, 2000, 3000, 5000, 10000]
print(label, time.strftime("[%H:%M:%S]"), cmd("r", 3))
print(
    "0x21, resets out of 10, by extra gap before back-on (add about 0.2 ms for the write)\n%-22s"
    % ""
    + "".join("%-8s" % ("%gms" % (g / 1000)) for g in gaps)
)
out = []
# Rows: (pattern, time the pattern is on before the switch-off in microseconds).
# 0x03, 0x07, 0x0F, 0x7F = the lowest 2, 3, 4, 7 outputs of the expander.
for pat, on in (
    (0x03, 5000),
    (0x07, 5000),
    (0x0F, 100),
    (0x0F, 5000),
    (0x0F, 50000),
    (0x7F, 100),
    (0x7F, 5000),
    (0x7F, 50000),
):
    row = []
    for g in gaps:
        # Mode 2: write pat, wait 'on' us, write 00, wait g us, write pat. 10 trials,
        # 30 ms rest between trials.
        r = cmd("t 21 %02X 00 2 %d %d 10 30" % (pat, g, on))
        f = r.split()
        row.append(int(f[f.index("resets") + 1]) if "resets" in f else -1)
    print(
        "%-22s" % ("%02X, on %g ms" % (pat, on / 1000)) + "".join("%-8d" % n for n in row),
        flush=True,
    )
    out.append(dict(pat=pat, on_us=on, gaps=gaps, resets=row))
# Leave everything off and show the read-back.
print("all off:", cmd("z", 3), cmd("r", 3))
json.dump(out, open(outf, "w"), indent=1)
