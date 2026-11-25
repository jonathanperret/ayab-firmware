"""Reset rate of chosen edgetest sequences, in blocks.

usage: rate.py <port> <blocks> <trials per block> SPEC...
SPEC = name:PP:mode[:BB], e.g. 4then2:7E:4:1E

  port              serial port of the controller (115200 baud)
  blocks            how many times the whole list of sequences is run
  trials per block  trials of each sequence in each block
  SPEC              name = free label for the output; PP = pattern in hex; mode = edgetest
                    mode number; BB = optional extra byte in hex (mode 2: the byte switched
                    back on; mode 4: the first stage of the switch-on)

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

All sequences run on expander 0x21 (solenoids 8-15), with the pattern on for 5 ms, off
byte 00 and 30 ms rest between trials. The sequences are interleaved (every block runs
each of them once) so that a slow change during the session affects them all alike.
Prints the firmware's READY line, then per sequence the resets counted in each block and
the total out of blocks x trials, then the final read-back of both ports."""

import sys, serial, time

# Opening the port resets the controller; its READY line is read below.
p = serial.Serial(sys.argv[1], 115200, timeout=0.3)
blocks, N = int(sys.argv[2]), int(sys.argv[3])  # N = trials per block
specs = [s.split(":") for s in sys.argv[4:]]  # each spec: [name, PP, mode] or [name, PP, mode, BB]


def rl(t=60):
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
# Per sequence name: total number of resets, and the list of resets in each block.
tot = {s[0]: 0 for s in specs}
rows = {s[0]: [] for s in specs}
for b in range(blocks):
    for s in specs:
        # 't' command: expander 21, pattern, off byte 00, mode, gap 0, 5000 us on, N trials,
        # 30 ms rest, then BB if the spec has one.
        c = "t 21 %s 00 %s 0 5000 %d 30%s" % (s[1], s[2], N, " " + s[3] if len(s) > 3 else "")
        p.reset_input_buffer()
        p.write((c + "\n").encode())
        f = rl().split()
        # There is no check here: a reply without "resets" stops the script with an error.
        r = int(f[f.index("resets") + 1])
        tot[s[0]] += r
        rows[s[0]].append(r)
for s in specs:
    print(
        "%-22s per block of %d: %s   total %d/%d"
        % (s[0], N, " ".join(map(str, rows[s[0]])), tot[s[0]], blocks * N)
    )
# Switch everything off ('z', reply discarded), then print the read-back of both ports.
p.write(b"z\n")
rl(3)
p.write(b"r\n")
print(rl(3), time.strftime("%H:%M:%S"))
