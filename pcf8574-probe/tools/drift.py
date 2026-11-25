"""Does the reset rate of a marginal sequence drift with use? Rest, then repeated short blocks.

usage: drift.py <port> <rest seconds> <blocks> <trials per block> [load]
('load' = keep six coils on between blocks)

  port              serial port of the controller (115200 baud)
  rest seconds      how long everything stays off before the blocks start
  blocks            number of blocks run after the rest
  trials per block  trials of each sequence in a block

Note: the 'load' argument described above is not read anywhere in this script; giving it
has no effect.

Firmware needed on the board: edgetest (../edgetest/src/main.cpp).

All sequences use expander 0x21 (solenoids 8-15) and edgetest mode 4: pattern 7E (outputs
1-6) on for 5 ms, then one write [00][first stage][7E], that is off, then back on in two
stages about 90 microseconds apart. Three first stages are used:
  4then2(1E)  outputs 1-4 first, then 5 and 6
  4then2(3C)  outputs 2-5 first, then 1 and 6
  3then3      outputs 1-3 first (0E), then 4-6

Prints the READY line, the reset counts of the two "4 then 2" sequences before the rest,
then, after the rest, one time-stamped line per block with resets/trials for the three
sequences, and finally the read-back of both ports."""

import sys, serial, time

# Opening the port resets the controller; its READY line is read below.
p = serial.Serial(sys.argv[1], 115200, timeout=0.3)
rest, blocks, N = int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])  # N = trials per block


def rl(t=60):
    """Read one reply line from the firmware.

    t: maximum time to wait, in seconds.
    Returns the text received up to the first line end (empty if nothing came in time)."""
    end = time.time() + t
    b = b""
    while time.time() < end and b"\n" not in b:
        b += p.read(64)
    return b.decode("ascii", "replace").strip()


def trial(c):
    """Send one 't' command and return the number of resets it reports.

    c: the complete command line, without the line end.
    Returns the count after the word "resets" in the reply, or -1 if there is none."""
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    f = rl().split()
    return int(f[f.index("resets") + 1]) if "resets" in f else -1


# The READY line printed by the firmware after its reset, and the time of day.
print(rl(5), time.strftime("%H:%M:%S"), flush=True)
# Reference measurement before the rest: N trials of each "4 then 2" sequence.
print(
    "before the rest: 4then2(1E) %d/%d, 4then2(3C) %d/%d"
    % (trial("t 21 7E 00 4 0 5000 %d 30 1E" % N), N, trial("t 21 7E 00 4 0 5000 %d 30 3C" % N), N),
    flush=True,
)
# Everything off ('z', reply discarded), then do nothing for 'rest' seconds.
p.write(b"z\n")
rl(3)
print("all off, resting %d s" % rest, time.strftime("%H:%M:%S"), flush=True)
time.sleep(rest)
# After the rest: the three sequences one after the other, N trials each, block after
# block without a pause, so that any change of the reset rate with use shows up over time.
for b in range(blocks):
    t = time.strftime("%H:%M:%S")
    a = trial("t 21 7E 00 4 0 5000 %d 30 1E" % N)  # a: first stage 1E (outputs 1-4)
    c = trial("t 21 7E 00 4 0 5000 %d 30 3C" % N)  # c: first stage 3C (outputs 2-5)
    d = trial("t 21 7E 00 4 0 5000 %d 30 0E" % N)  # d: first stage 0E (outputs 1-3)
    print(
        "%s  4then2(1E) %2d/%d   4then2(3C) %2d/%d   3then3 %d/%d" % (t, a, N, c, N, d, N),
        flush=True,
    )
# Switch everything off ('z', reply discarded), then print the read-back of both ports.
p.write(b"z\n")
rl(3)
p.write(b"r\n")
print(rl(3), time.strftime("%H:%M:%S"), flush=True)
