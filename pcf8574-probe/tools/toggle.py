"""Exercise the solenoids through the hardware-test mode of the AYAB firmware.

usage: toggle.py <serial port>

Firmware needed on the board: the AYAB firmware (not one of the probe sketches). The
script speaks its serial protocol at 115200 baud: SLIP-framed packets whose first byte is
the message type. It asks for test mode (reqTest, 0x04), waits for the confirmation
(cnfTest, 0xC4) and then sends setSingle (0x28: solenoid number, 0 or 1) and setAll
(0x29: 16-bit state, high byte first) commands in four phases:
  1. each solenoid 0..15 on for 0.25 s then off, twice over
  2. solenoids switched on one after the other until all 16 are on, then off one after
     the other, twice over
  3. six rounds of whole-state patterns AAAA, 5555, FFFF, 0000, FF00, 00FF
  4. state F6F6 held while solenoid 0 is toggled 300 times, 20 ms apart
It then holds F6F6 for 3 s so that what is lit can be checked by eye, and switches everything off.

Prints the confirmation packet, one line per phase, a count of each distinct text reply
of the firmware (testRes packets, 0xEE) and a count of any other packet types received.
Exits with status 1 if test mode is not confirmed."""

import sys, time, serial

# SLIP framing bytes: END closes a packet; inside a packet END is sent as ESC EEND and ESC
# as ESC EESC.
END, ESC, EEND, EESC = 0xC0, 0xDB, 0xDC, 0xDD
# Opening the port resets the board. The 50 ms timeout sets how often pump() polls.
p = serial.Serial(sys.argv[1], 115200, timeout=0.05)
rx = bytearray()  # bytes received but not yet split into packets
log = []  # every packet received so far, unescaped


def send(*b):
    """Send one packet to the firmware.

    b: the bytes of the packet (message type first), given as separate arguments.
    The bytes are SLIP-escaped and followed by the END byte."""
    out = bytearray()
    for x in b:
        out += bytes([ESC, EEND]) if x == END else bytes([ESC, EESC]) if x == ESC else bytes([x])
    p.write(bytes(out) + bytes([END]))


def pump(t):
    """Receive for t seconds and append every complete packet to 'log'.

    t: how long to keep reading, in seconds.
    This is also how the script waits: each command is followed by a pump() of the wanted
    duration. Empty packets (two END bytes in a row) are dropped."""
    global rx
    end = time.time() + t
    while time.time() < end:
        rx += p.read(256)
        while END in rx:
            i = rx.index(END)
            pkt = (
                bytes(rx[:i])
                .replace(bytes([ESC, EEND]), bytes([END]))
                .replace(bytes([ESC, EESC]), bytes([ESC]))
            )
            rx = rx[i + 1 :]
            if pkt:
                log.append(pkt)


time.sleep(2.5)  # bootloader + firmware init
pump(0.2)
# Ask for test mode, wait half a second, and look for the confirmation packet (type 0xC4).
# Its second byte is an error code; anything but 0 stops the script.
send(0x04)  # reqTest
pump(0.5)
cnf = [x for x in log if x[0] == 0xC4]
print("cnfTest:", cnf[0].hex() if cnf else "NONE")
if not cnf or cnf[0][1] != 0:
    print("raw:", [x[:20] for x in log])
    sys.exit(1)
# Packets received from here on are the replies to the commands below.
n0 = len(log)


def single(n, s, wait):
    """Switch one solenoid and wait.

    n:    solenoid number, 0 to 15.
    s:    1 = on, 0 = off.
    wait: time to keep receiving afterwards, in seconds."""
    send(0x28, n, s)
    pump(wait)


def allset(v, wait):
    """Set all 16 solenoids at once and wait.

    v:    16-bit state, bit n = solenoid n; it is sent high byte first.
    wait: time to keep receiving afterwards, in seconds."""
    send(0x29, v >> 8, v & 0xFF)
    pump(wait)


print("phase 1: walking single solenoid 0..15 (one at a time), x2")
for _ in range(2):
    for n in range(16):
        # 0.25 s on, then 0.1 s off before the next solenoid.
        single(n, 1, 0.25)
        single(n, 0, 0.1)
print("phase 2: cumulative on 0..15, then cumulative off, x2")
for _ in range(2):
    # 0.2 s between steps.
    for n in range(16):
        single(n, 1, 0.2)
    for n in range(16):
        single(n, 0, 0.2)
print("phase 3: setAll alternating patterns")
for _ in range(6):
    # AAAA = odd solenoids, 5555 = even solenoids, FF00 = solenoids 8-15, 00FF = 0-7;
    # each pattern is held for 0.25 s.
    for v in (0xAAAA, 0x5555, 0xFFFF, 0x0000, 0xFF00, 0x00FF):
        allset(v, 0.25)
print("phase 4: 300 fast single toggles with solenoids 1,2,4-7,9,10,12-15 held on")
# F6F6 = outputs 1, 2, 4, 5, 6, 7 of each expander, that is the solenoids named in the
# message above.
allset(0xF6F6, 0.3)
for i in range(300):
    # (i & 1) ^ 1: on for even i, off for odd i, so the first toggle switches solenoid 0 on.
    single(0, i & 1 ^ 1, 0.02)
single(0, 0, 0.1)
print("holding 0xF6F6 for 3 s -- both banks should show 6 of 8 lit (0 and 3 off)")
pump(3)
allset(0x0000, 0.3)
# Text replies of the firmware (packets of type 0xEE, text after the type byte), counted
# by content, then the other packet types received, counted by type byte.
texts = [x[1:].decode("ascii", "replace").strip() for x in log[n0:] if x[0] == 0xEE]
from collections import Counter

print("firmware replies:", dict(Counter(texts)))
print("other packets:", Counter(x[0] for x in log[n0:] if x[0] != 0xEE))
print("all off")
