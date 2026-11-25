#!/usr/bin/env python3
"""Every combination of k outputs of one expander, switched off and back on.

Usage: combo_session.py <port> <addr hex> <label> <out.json> [sizes, default 3,4,5]

  port      serial port of the controller (115200 baud)
  addr hex  I2C address of the expander under test: 20 (solenoids 0-7) or 21 (8-15)
  label     free text printed at the start and stored in the JSON file
  out.json  file that receives the results (required)
  sizes     comma-separated numbers of outputs to try, for example 3,4,5

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

For each size k, each of the possible choices of k outputs among the 8 is tested with 10
trials: the outputs are on for 5 ms, are switched off, and the same outputs are switched
back on by the next write (about 0.2 ms later). One line is printed per size, made of
"PP:R" items: PP is the pattern in hex, R the number of trials out of 10 that ended with
the port reading FF (a reset); R is -1 if the firmware's reply could not be read.
The JSON file holds {label, addr, rows}, one row {k, pat, resets, raw} per pattern."""

import sys, time, json, serial, itertools

# Command line. 'sizes' becomes a list of integers.
port, addr, label, outf = sys.argv[1], int(sys.argv[2], 16), sys.argv[3], sys.argv[4]
sizes = [int(x) for x in (sys.argv[5] if len(sys.argv) > 5 else "3,4,5").split(",")]
p = serial.Serial(port, 115200, timeout=0.2)
# Opening the port resets the controller: wait for it to start before sending anything.
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


# Header: label, time of day, read-back of both ports ('r') and controller supply ('v', mV).
print(label, time.strftime("[%H:%M:%S]"), cmd("r", 3), cmd("v", 3))
# One entry per tested pattern, for the JSON file.
res = []
for k in sizes:
    line = []
    # c is a tuple of k output numbers (0-7); pat is the matching bit pattern.
    for c in itertools.combinations(range(8), k):
        pat = sum(1 << b for b in c)
        # Mode 2 with gap 0: write pat, wait 5000 us, write 00, write pat again at once.
        # 10 trials, 30 ms rest between trials. The last field repeats pat as the byte to
        # switch back on (which is also the firmware's default).
        r = cmd("t %02X %02X 00 2 0 5000 10 30 %02X" % (addr, pat, pat))
        f = r.split()
        n = int(f[f.index("resets") + 1]) if "resets" in f else -1  # -1 = no usable reply
        res.append(dict(k=k, pat=pat, resets=n, raw=r))
        line.append("%02X:%d" % (pat, n))
    print("%d outputs (resets out of 10): " % k + " ".join(line), flush=True)
# Leave everything off and show the read-back.
print("all off:", cmd("z", 3), cmd("r", 3))
json.dump(dict(label=label, addr=addr, rows=res), open(outf, "w"), indent=1)
