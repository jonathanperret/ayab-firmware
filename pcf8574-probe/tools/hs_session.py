#!/usr/bin/env python3
"""Does putting the expander in its high-speed mode change how often it resets?

Usage: hs_session.py <port> <label> <out.json> [blocks, default 6] [trials per cell, default 10]

Firmware needed on the board: edgetest with modes 5 to 8 (../edgetest/src/main.cpp).

Each sequence switches coils of expander 0x21 on for 5 ms, off, and back on about 90 us later,
either all at once or in two stages. It is run three ways:
  hardware     the write sent by the controller's I2C hardware (modes 1 and 4)
  bit-banged   the same write bit-banged through the pins (modes 5 and 7)
  high-speed   bit-banged, after the high-speed code that sets the expander's bus input
               filters to their fast setting for the length of the write (modes 6 and 8)
Borderline sequences reset less often after a minute of continuous switching (journal entry 186),
so the run is made of blocks: everything off for 20 s, then every sequence each way, with the
order of the three ways rotated from block to block.
Prints resets out of all trials per sequence and way, and the per-block counts for the borderline
ones; writes everything to the JSON file."""
import sys, time, json, serial

port, label, outf = sys.argv[1:4]
blocks = int(sys.argv[4]) if len(sys.argv) > 4 else 6
n = int(sys.argv[5]) if len(sys.argv) > 5 else 10
# Opening the port resets the controller: wait for its READY line.
p = serial.Serial(port, 115200, timeout=0.3)


def readline(t=60):
    """One line from the firmware, or what arrived within t seconds."""
    end = time.time() + t
    b = b""
    while time.time() < end and b"\n" not in b:
        b += p.read(64)
    return b.decode("ascii", "replace").strip()


def trial(pat, mode, first=None):
    """Run n trials of one sequence; returns (resets, unacknowledged writes), or (-1, -1)."""
    c = "t 21 %s 00 %d 0 5000 %d 30%s" % (pat, mode, n, " " + first if first else "")
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    f = readline().split()
    try:
        return int(f[f.index("resets") + 1]), int(f[f.index("wnak") + 1])
    except ValueError:
        return -1, -1


# name, pattern, first stage (None = all at once)
SEQUENCES = [("one coil", "02", None), ("three at once", "0E", None), ("four at once", "1E", None), ("six at once", "7E", None),
             ("six as 3 then 3", "7E", "0E"), ("six as 4 then 2", "7E", "1E"), ("five as 3 then 2", "3E", "0E")]
WAYS = [("hardware", 1, 4), ("bit-banged", 5, 7), ("high-speed", 6, 8)]
print("%s  [%s]" % (label, time.strftime("%H:%M:%S")))
print("controller:", readline(5))
counts = {(s[0], w[0]): [] for s in SEQUENCES for w in WAYS}
naks = {(s[0], w[0]): 0 for s in SEQUENCES for w in WAYS}
for b in range(blocks):
    p.write(b"z\n"); readline(3)
    time.sleep(20)                                   # rest, everything off
    order = WAYS[b % 3:] + WAYS[:b % 3]              # rotate which way goes first
    for name, pat, first in SEQUENCES:
        for way, at_once, staged in order:
            r, k = trial(pat, staged if first else at_once, first)
            counts[(name, way)].append(r); naks[(name, way)] += max(k, 0)
    print("block %d of %d done [%s]" % (b + 1, blocks, time.strftime("%H:%M:%S")), flush=True)
p.write(b"z\n"); readline(3); p.write(b"r\n"); print("all off, read-back:", readline(3))
total = blocks * n
print("\nresets out of %d, coils on 5 ms first, back on about 90 us after the switch-off" % total)
print("%-18s %-12s %-12s %-12s" % ("", *[w[0] for w in WAYS]))
for name, pat, first in SEQUENCES:
    print("%-18s %-12s %-12s %-12s" % (name, *["%d" % sum(counts[(name, w[0])]) if min(counts[(name, w[0])]) >= 0 else "error" for w in WAYS]))
print("\nper block, for the sequences that were neither never nor always:")
for name, pat, first in SEQUENCES:
    if any(0 < sum(counts[(name, w[0])]) < total for w in WAYS):
        for w in WAYS: print("  %-18s %-11s %s" % (name, w[0], " ".join("%2d" % c for c in counts[(name, w[0])])))
json.dump(dict(label=label, blocks=blocks, trials=n, counts={"%s|%s" % k: v for k, v in counts.items()}, unacknowledged={"%s|%s" % k: v for k, v in naks.items()}), open(outf, "w"), indent=1)
