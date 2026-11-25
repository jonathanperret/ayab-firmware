"""Run one edgetest command on the Mac while the scope on the Pi records (through scope_daemon.py);
fetch the capture.
usage: scope_trial.py <port> <name> <range1> <range2> <MB> <edgetest command...>
Writes captures/<name>.npy (interleaved CH1, CH2 bytes at 16 MS/s) and a quick-look picture
captures/<name>.png for the live page (scope_page.py). Channel labels from the environment: L1, L2.

Arguments: port = serial port of the board running the edgetest firmware (115200 baud);
name = capture name; range1, range2 = scope ranges for CH1 and CH2 (100mV 250mV 500mV 1V);
MB = recording size in units of 2**20 bytes; the remaining words, joined by spaces, are the
command line sent to the board.
Environment: SCOPE = address of scope_daemon.py (default http://raspberrypi.local:8000);
L1, L2 = labels of CH1 and CH2 in the picture (defaults "CH1 yellow", "CH2 blue").
Needs: scope_daemon.py running on the Pi from a folder named "scope" in the home directory of
the account hard-coded in the scp command below, key-based ssh access to it, and
scope_compare.py next to this file. "captures" is the folder beside the tools folder.
Prints: the board's first line, the daemon's answer, the board's reply to the command, and its
replies to "z" and "r", which this script labels "all off" and "read-back". scope_compare.py
adds its own summary lines.
"""

import sys, os, time, subprocess, serial

# Arguments (all kept as text). command = the edgetest command line to send.
port, name, r1, r2, mb = sys.argv[1:6]
command = " ".join(sys.argv[6:])
S = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captures"
)  # durable folder in the project
# p = the board's serial port.
p = serial.Serial(port, 115200, timeout=0.2)


def readline(t):
    """Read from the board until a line end arrives or t seconds have passed.

    Returns everything received, as stripped text (it may be empty, or more than one line).
    """
    end = time.time() + t
    buf = b""
    while time.time() < end:
        buf += p.read(64)
        if b"\n" in buf:
            break
    return buf.decode("ascii", "replace").strip()


# Show the first thing the board sends after the port is opened (waiting up to 5 s), discard
# anything else it sent, and send the command. t0 = the moment the command was sent.
print("controller:", readline(5))
p.reset_input_buffer()
p.write((command + "\n").encode())
t0 = time.time()
time.sleep(0.4)  # let the trials get going
# Ask the daemon to record. The request only returns when the recording is on the Pi's disk
# (or has failed), so the 0.4 s above is all the head start the board's trials get.
import json, urllib.request

PI = os.environ.get("SCOPE", "http://raspberrypi.local:8000")  # scope_daemon.py on the Pi
rec = json.load(
    urllib.request.urlopen(
        "%s/record?name=%s&mb=%s&r1=%s&r2=%s" % (PI, name, mb, r1, r2), timeout=90
    )
)
print("scope: %s (finished %.1f s after the command was sent)" % (rec, time.time() - t0))
# Wait up to 60 s for the board's reply to the command, then send "z" and "r" and show the
# answers.
print("reply:", readline(60), "(%.1f s)" % (time.time() - t0))
p.write(b"z\n")
print("all off:", readline(5))
p.write(b"r\n")
print("read-back:", readline(5))
# Copy the recording from the Pi into the captures folder.
subprocess.run(
    ["scp", "-q", "jonathan@raspberrypi.local:scope/out/%s.npy" % name, "%s/%s.npy" % (S, name)],
    check=True,
)
# Make the quick-look picture with scope_compare.py. Its arguments: output file, title (name,
# time of day, command), the two channel labels, the ranges as "r1,r2", and one capture given as
# "<row label>=<file>", the row label being "<name>: <command>". scope_compare.py splits that
# last argument at its first "=", so a command containing "=" would break it. The result of
# this run is not checked.
here = os.path.dirname(os.path.abspath(__file__))
subprocess.run(
    [
        sys.executable,
        "-I",
        os.path.join(here, "scope_compare.py"),
        "%s/%s.png" % (S, name),
        "%s  [%s]  %s" % (name, time.strftime("%H:%M:%S"), command),
        os.environ.get("L1", "CH1 yellow"),
        os.environ.get("L2", "CH2 blue"),
        "%s,%s" % (r1, r2),
        "%s: %s=%s/%s.npy" % (name, command, S, name),
    ]
)
