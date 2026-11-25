#!/usr/bin/env python3
"""ALIENTEK DP100 control through Linux hidraw, no extra packages needed.
Run as root (the hidraw node is root-only by default):
  sudo python3 dp100_hidraw.py status
  sudo python3 dp100_hidraw.py set <volts> <amps>
  sudo python3 dp100_hidraw.py on | off
  sudo python3 dp100_hidraw.py watch [<seconds> [<interval seconds>]]
Same protocol as dp100.py.

Linux only: it finds the supply by looking through /sys/class/hidraw and talks to the
matching /dev/hidrawN node directly. The "psu" script in this folder runs it on a
Raspberry Pi over ssh.

status (the default when no argument is given), set, on and off each end by printing one
line: output on/off, set voltage (V) and current limit (A), measured output voltage (V)
and current (A), input voltage (V).

watch prints one line per reading, "<seconds since start> <volts> <amps>", for <seconds>
(default 10), pausing <interval seconds> (default 0.1) between readings, then exits
without the status line.

Frame format (see dp100.py for more): 64-byte HID reports holding
[0xFB, opcode, 0x00, length, data..., CRC16-Modbus (low, high)]; replies start with 0xFA.
"""

import sys, os, glob, struct, time, select


def crc16(b):
    """Return the CRC-16/Modbus of the bytes b as an integer (0..0xFFFF).

    Start value 0xFFFF, bits processed least significant first, polynomial 0xA001.
    """
    c = 0xFFFF
    for x in b:
        c ^= x
        for _ in range(8):
            # Shift right one bit; if the bit shifted out was 1, apply the polynomial.
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


def find():
    """Return the device path ("/dev/hidrawN") of the DP100, or exit if there is none.

    Each hidraw device has a "uevent" text file in sysfs whose HID_ID line gives
    bus:vendor:product, vendor and product as 8 hexadecimal digits. The DP100 is vendor
    2E3C, product AF01.
    """
    for h in glob.glob("/sys/class/hidraw/hidraw*"):
        try:
            if "00002E3C:0000AF01" in open(h + "/device/uevent").read().upper():
                return "/dev/" + os.path.basename(h)
        except OSError:
            # A device whose uevent file cannot be read is skipped.
            pass
    sys.exit("DP100 not found")


class DP100:
    """An open connection to the DP100 through its hidraw device node."""

    def __init__(self):
        """Find the supply and open its device node for reading and writing."""
        self.fd = os.open(find(), os.O_RDWR)

    def xfer(self, op, data=b""):
        """Send one request and return the data bytes of the matching reply.

        op:   opcode (one byte): 0x30 reads the measurements, 0x35 reads or writes settings.
        data: payload bytes of the request (may be empty).
        Returns the payload of the reply (bytes), without header and CRC.
        Raises IOError on a wrong CRC, or if no matching reply arrives within 2 seconds.
        """
        # Request frame: 0xFB, opcode, a byte that is always 0 here, payload length, payload.
        f = bytes([0xFB, op, 0x00, len(data)]) + data
        # The CRC covers everything before it and is sent low byte first.
        f += struct.pack("<H", crc16(f))
        # hidraw wants the report number first (0 here), then the 64-byte report; the frame
        # is padded with zeros to that size.
        os.write(self.fd, b"\x00" + f.ljust(64, b"\x00"))
        end = time.time() + 2  # give up 2 seconds from now
        while time.time() < end:
            # Wait up to 0.5 s for the device to have something to read.
            if not select.select([self.fd], [], [], 0.5)[0]:
                continue
            r = os.read(self.fd, 64)
            # Skip anything that is not a reply (0xFA) to the opcode just sent.
            if len(r) >= 6 and r[0] == 0xFA and r[1] == op:
                n = r[3]  # payload length
                # The two bytes after the payload are the CRC of header plus payload.
                if struct.unpack("<H", r[4 + n : 6 + n])[0] != crc16(r[: 4 + n]):
                    raise IOError("bad CRC")
                return r[4 : 4 + n]
        raise IOError("no reply")

    def info(self):
        """Read the live measurements (opcode 0x30).

        Returns a dict: vin (input voltage, V), vout (output voltage, V), iout (output
        current, A), mode and state (raw numbers; their meaning is not evident here).
        """
        # 16 bytes, little-endian: seven 16-bit values then two single bytes. Voltages are
        # in millivolts, the current in milliamps. vomax, t1, t2 and v5 (highest output
        # voltage, two temperatures, 5 V rail: see dp100.py) are decoded but not returned.
        vin, vout, iout, vomax, t1, t2, v5, mode, st = struct.unpack(
            "<HHHHHHHBB", self.xfer(0x30)[:16]
        )
        return dict(vin=vin / 1000, vout=vout / 1000, iout=iout / 1000, mode=mode, state=st)

    def settings(self):
        """Read the active settings group (opcode 0x35 with payload 0x80).

        Returns a dict: index (group number), on (output switched on, bool), vset (set
        voltage, V), iset (current limit, A), ovp (over-voltage protection level, V),
        ocp (over-current protection level, A).
        """
        # 10 bytes, little-endian: group number, on/off, then four 16-bit values in
        # millivolts or milliamps.
        idx, on, vset, iset, ovp, ocp = struct.unpack(
            "<BBHHHH", self.xfer(0x35, bytes([0x80]))[:10]
        )
        return dict(
            index=idx,
            on=bool(on),
            vset=vset / 1000,
            iset=iset / 1000,
            ovp=ovp / 1000,
            ocp=ocp / 1000,
        )

    def apply(self, on=None, vset=None, iset=None):
        """Change the output state and/or the set-points of the active group.

        on:   True or False to switch the output, None to leave it as it is.
        vset: set voltage in volts, None to leave it.
        iset: current limit in amps, None to leave it.
        The current settings are read first, so that everything not given (including the
        protection levels) is written back unchanged.
        Returns the payload of the supply's reply.
        """
        s = self.settings()
        on = s["on"] if on is None else on
        vset = s["vset"] if vset is None else vset
        iset = s["iset"] if iset is None else iset
        return self.xfer(
            0x35,
            # Same layout as the reply decoded in settings(): group, on/off, set voltage
            # (mV), current limit (mA), OVP (mV), OCP (mA).
            struct.pack(
                "<BBHHHH",
                # Low 4 bits: group number. The 0x20 bit makes this a write (the read in
                # settings() uses 0x80 instead).
                (s["index"] & 0x0F) | 0x20,
                1 if on else 0,
                round(vset * 1000),
                round(iset * 1000),
                round(s["ovp"] * 1000),
                round(s["ocp"] * 1000),
            ),
        )


def show(p):
    """Read measurements and settings from the supply p (a DP100) and print one line."""
    i, s = p.info(), p.settings()  # i: measurements, s: settings
    print(
        "output %s | set %.3f V, limit %.3f A | measured %.3f V, %.3f A | input %.2f V"
        % ("ON" if s["on"] else "off", s["vset"], s["iset"], i["vout"], i["iout"], i["vin"])
    )


if __name__ == "__main__":
    p = DP100()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "set":
        p.apply(vset=float(sys.argv[2]), iset=float(sys.argv[3]))
        # Pause 0.4 s before the status read-back below.
        time.sleep(0.4)
    elif cmd in ("on", "off"):
        p.apply(on=(cmd == "on"))
        # Pause 0.6 s before the status read-back below.
        time.sleep(0.6)
    elif cmd == "watch":
        # watch <seconds> [interval]: one line per reading, "<seconds since start> <volts> <amps>"
        t0 = time.time()  # start time
        dur = float(sys.argv[2]) if len(sys.argv) > 2 else 10  # how long to watch, seconds
        step = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1  # pause between readings, s
        while time.time() - t0 < dur:
            i = p.info()
            # flush so that each line arrives at once when the output is piped (as via ssh).
            print("%.3f %.3f %.3f" % (time.time() - t0, i["vout"], i["iout"]), flush=True)
            time.sleep(step)
        sys.exit()
    # Every other command, including "status" and anything unrecognised, ends with a
    # status line.
    show(p)
