"""Minimal control of an ALIENTEK DP100 (ATK-MDP100) bench supply over USB HID.

Protocol as reverse-engineered by the open-source DP100 projects: 64-byte HID
reports, frame = [0xFB, opcode, 0x00, length, data..., CRC16-Modbus (low, high)].
Replies start with 0xFA.

  dp100.py status                 read input/output voltage, current, settings
  dp100.py set <volts> <amps>     change the set-points, leaving on/off as it is
  dp100.py on | off               switch the output

With no argument the command is "status". Every command ends by printing one status line:
output on/off, set voltage (V) and current limit (A), measured output voltage (V) and
current (A), input voltage (V), the supply's mode and state numbers, the over-voltage and
over-current protection levels, and the number of the active settings group.

Needs the "hid" Python package (hidapi) and permission to open the USB device. The
variant dp100_hidraw.py does the same on Linux with the standard library only.

Any other first argument is treated like "status". A missing or non-numeric argument to
"set" stops the script with a Python error.
"""

import sys, struct, time, hid

# USB vendor and product identifiers of the DP100.
VID, PID = 0x2E3C, 0xAF01
# Opcodes used here: 0x30 reads the live measurements, 0x35 reads or writes a settings group.
OP_BASIC_INFO, OP_BASIC_SET = 0x30, 0x35


def crc16(b):
    """Return the CRC-16/Modbus of the bytes b as an integer (0..0xFFFF).

    Start value 0xFFFF, bits processed least significant first, polynomial 0xA001
    (the bit-reversed form of 0x8005).
    """
    c = 0xFFFF
    for x in b:
        c ^= x
        for _ in range(8):
            # Shift right one bit; if the bit shifted out was 1, apply the polynomial.
            c = (c >> 1) ^ 0xA001 if c & 1 else c >> 1
    return c


class DP100:
    """An open connection to the first DP100 found on USB."""

    def __init__(self):
        """Open the HID device with the DP100's vendor and product identifiers."""
        self.h = hid.device()
        self.h.open(VID, PID)

    def xfer(self, op, data=b""):
        """Send one request and return the data bytes of the matching reply.

        op:   opcode (one byte).
        data: payload bytes of the request (may be empty).
        Returns the payload of the reply (bytes), without header and CRC.
        Raises IOError if the reply has a wrong CRC, or if none of the next 20 reads
        (each waiting up to 500 ms, so about 10 s in all) gives a reply to this opcode.
        """
        # Request frame: 0xFB, opcode, a byte that is always 0 here, payload length, payload.
        f = bytes([0xFB, op, 0x00, len(data)]) + data
        # The CRC covers everything before it and is sent low byte first.
        f += struct.pack("<H", crc16(f))
        # The leading zero byte is the HID report number; the frame is padded with zeros
        # to a full 64-byte report.
        self.h.write(b"\x00" + f.ljust(64, b"\x00"))
        for _ in range(20):
            r = bytes(self.h.read(64, 500))  # up to 64 bytes, waiting at most 500 ms
            # Skip anything that is not a reply (0xFA) to the opcode just sent.
            if len(r) >= 6 and r[0] == 0xFA and r[1] == op:
                n = r[3]  # payload length
                body = r[4 : 4 + n]
                # The two bytes after the payload are the CRC of header plus payload.
                if struct.unpack("<H", r[4 + n : 6 + n])[0] != crc16(r[: 4 + n]):
                    raise IOError("bad CRC in reply")
                return body
        raise IOError("no reply to opcode 0x%02X" % op)

    def info(self):
        """Read the live measurements.

        Returns a dict: vin (input voltage, V), vout (output voltage, V), iout (output
        current, A), vout_max (highest output voltage available, V), temp1 and temp2
        (two temperature readings, sent in tenths of a degree), usb5v (5 V rail, V),
        mode and state (raw numbers; their meaning is not evident from this script).
        """
        b = self.xfer(OP_BASIC_INFO)
        # 16 bytes, little-endian: seven 16-bit values then two single bytes.
        # Voltages are in millivolts, the current in milliamps.
        vin, vout, iout, vomax, t1, t2, v5, mode, st = struct.unpack("<HHHHHHHBB", b[:16])
        return dict(
            vin=vin / 1000,
            vout=vout / 1000,
            iout=iout / 1000,
            vout_max=vomax / 1000,
            temp1=t1 / 10,
            temp2=t2 / 10,
            usb5v=v5 / 1000,
            mode=mode,
            state=st,
        )

    def settings(self):
        """Read the active settings group.

        Returns a dict: index (group number), on (output switched on, bool), vset (set
        voltage, V), iset (current limit, A), ovp (over-voltage protection level, V),
        ocp (over-current protection level, A).
        """
        b = self.xfer(OP_BASIC_SET, bytes([0x80]))  # 0x80: read the active group
        # 10 bytes, little-endian: group number, on/off, then four 16-bit values in
        # millivolts or milliamps.
        idx, on, vset, iset, ovp, ocp = struct.unpack("<BBHHHH", b[:10])
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
        # Same layout as the reply decoded in settings(): group, on/off, set voltage (mV),
        # current limit (mA), OVP (mV), OCP (mA).
        d = struct.pack(
            "<BBHHHH",
            # Low 4 bits: group number. The 0x20 bit makes this a write (the read in
            # settings() uses 0x80 instead).
            (s["index"] & 0x0F) | 0x20,
            1 if on else 0,
            int(round(vset * 1000)),
            int(round(iset * 1000)),
            int(round(s["ovp"] * 1000)),
            int(round(s["ocp"] * 1000)),
        )
        return self.xfer(OP_BASIC_SET, d)


def show(p):
    """Read measurements and settings from the supply p (a DP100) and print one line."""
    i, s = p.info(), p.settings()  # i: measurements, s: settings
    print(
        "output %s | set %.3f V, limit %.3f A | measured %.3f V, %.3f A | input %.2f V | mode %d state %d | OVP %.2f V OCP %.2f A | group %d"
        % (
            "ON" if s["on"] else "off",
            s["vset"],
            s["iset"],
            i["vout"],
            i["iout"],
            i["vin"],
            i["mode"],
            i["state"],
            s["ovp"],
            s["ocp"],
            s["index"],
        )
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
    # Every command, including "status" and anything unrecognised, ends with a status line.
    show(p)
