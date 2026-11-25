"""Print what a board sends on its serial port, each line preceded by its arrival time.

usage: readserial_ts.py <serial port> <seconds>
Env: BAUD (baud rate, default 115200).

Works with any sketch that prints text lines. Opening the port resets the board, so the
output normally starts with the sketch's first lines. Listening stops after <seconds>, or
as soon as a line containing "DONE" arrives; the ident, busdiag, pinhealth and
mcp-readback sketches end their report with such a line.

Each non-empty line is printed as "<seconds since the port was opened>  <text>", with
the text cut to 1200 characters."""

import sys, time, serial

p = serial.Serial(sys.argv[1], int(__import__("os").environ.get("BAUD", "115200")), timeout=0.05)
# t0: time origin of the printed timestamps; end: when to give up.
t0 = time.time()
end = t0 + float(sys.argv[2])
buf = b""
done = False
while time.time() < end and not done:
    buf += p.read(4096)
    while b"\n" in buf:
        line, buf = buf.split(b"\n", 1)
        s = line.decode("ascii", "replace").rstrip()
        if s:
            print("%7.2f  %s" % (time.time() - t0, s[:1200]))
        if "DONE" in s:
            done = True
