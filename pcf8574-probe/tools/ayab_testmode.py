#!/usr/bin/env python3
"""Stand in for the AYAB desktop app's hardware test window: open the port,
ask the firmware to enter test mode, and print every text message it sends,
with the time each line arrived.

usage: ayab_testmode.py <serial port> [seconds to listen]

  serial port        port of the controller (115200 baud)
  seconds to listen  maximum listening time, default 40

Firmware needed on the board: the AYAB firmware with the port expander probe
(../../src/ayab/pcfprobe.cpp), which runs when test mode is entered.

Stops early, half a second after a line containing "=== TEST FINISHED" has arrived.

Prints one line per text line received, preceded by the time in seconds since the test
mode request was sent, plus a line when the firmware confirms test mode (or a final line
saying that it never did)."""

import sys, time, serial

# SLIP framing bytes of the AYAB serial protocol: END closes a packet; inside a packet END
# is sent as ESC EEND and ESC as ESC EESC.
END, ESC, EEND, EESC = 0xC0, 0xDB, 0xDC, 0xDD
# Opening the port resets the board.
p = serial.Serial(sys.argv[1], 115200, timeout=0.05)
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 40


def send(*b):
    """Send one packet to the firmware.

    b: the bytes of the packet (message type first), given as separate arguments.
    The bytes are SLIP-escaped and followed by the END byte."""
    o = bytearray()
    for x in b:
        o += bytes([ESC, EEND]) if x == END else bytes([ESC, EESC]) if x == ESC else bytes([x])
    p.write(bytes(o) + bytes([END]))


# Wait for the bootloader and the firmware to start, drop what they sent, and request test
# mode. t0 is the time origin of the printed timestamps.
time.sleep(2.5)
p.reset_input_buffer()
t0 = time.time()
send(0x04)  # reqTest
rx = bytearray()  # bytes received but not yet split into packets
cur = ""  # text received but not yet ended by a line feed
end = time.time() + secs
cnf = None  # (seconds since t0, error code) of the confirmation
while time.time() < end:
    rx += p.read(256)
    # Take complete packets out of rx one at a time and undo the SLIP escaping.
    while END in rx:
        i = rx.index(END)
        pkt = (
            bytes(rx[:i])
            .replace(bytes([ESC, EEND]), bytes([END]))
            .replace(bytes([ESC, EESC]), bytes([ESC]))
        )
        rx = rx[i + 1 :]
        if not pkt:
            continue
        # 0xC4 = cnfTest, the reply to the request; its second byte is an error code.
        if pkt[0] == 0xC4:
            cnf = (time.time() - t0, pkt[1])
            print(
                "%6.2f  [test mode confirmed, error code %d: the app opens its test window here]"
                % cnf
            )
        # 0xEE = testRes: a piece of text. Pieces are joined and printed line by line.
        elif pkt[0] == 0xEE:
            cur += pkt[1:].decode("ascii", "replace")
            while "\n" in cur:
                l, cur = cur.split("\n", 1)
                print("%6.2f  %s" % (time.time() - t0, l))
                # Last line of the probe: listen for half a second more, then stop.
                if "=== TEST FINISHED" in l:
                    end = min(end, time.time() + 0.5)
if not cnf:
    print("[no confirmation of test mode received]")
