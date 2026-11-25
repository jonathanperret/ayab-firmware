"""Send commands to the setstate sketch without resetting the board each time.

usage: cmd.py <port> [--reset] "<command>" ...   (prints each reply line)

  port     serial port of the controller (115200 baud)
  --reset  let the board reset when the port is opened, and wait for its READY line
  command  one line for the sketch, sent as is; several can be given and are sent in order

Firmware needed on the board: setstate (../setstate/src/main.cpp). Its commands:
  n XXXX           write the 16-bit state XXXX (hex), one data byte per expander
  m XXXX           same state, written as two bytes [09][data] per expander
  r                read both ports back
  b N XXXX YYYY D  burst: N writes alternating between the two states, D ms apart
In a 16-bit state the low byte goes to expander 0x20 (solenoids 0-7) and the high byte to
0x21 (solenoids 8-15).

Prints one line per command: "<command> -> <reply>". Without --reset the outputs keep the
state left by the previous call, so a state can be set and examined across several runs."""

import sys, time, serial

# Command line: the port comes first; --reset may appear anywhere after it; the remaining
# arguments are the commands.
args = sys.argv[1:]
port = args.pop(0)
reset = "--reset" in args
if reset:
    args.remove("--reset")
# The port object is built without opening it, so that the control lines can be set first.
p = serial.Serial()
p.port = port
p.baudrate = 115200
p.timeout = 0.2
# An Arduino resets when DTR/RTS are asserted as the port opens; keeping both low avoids it.
if not reset:
    p.dtr = False
    p.rts = False  # do not pulse the reset line when opening
p.open()
# With --reset: wait up to 4 s for the sketch's READY line and print its last 40 characters.
if reset:
    t = time.time() + 4
    buf = b""
    while time.time() < t and b"READY" not in buf:
        buf += p.read(64)
    print(buf.decode("ascii", "replace").strip()[-40:])
# Send each command and print its one-line reply.
for c in args:
    p.reset_input_buffer()
    p.write((c + "\n").encode())
    t = time.time() + (60 if c.startswith("b") else 3)  # a burst can take long: 60 s, otherwise 3 s
    buf = b""
    while time.time() < t and b"\n" not in buf:
        buf += p.read(64)
    print(c, "->", buf.decode("ascii", "replace").strip())
