"""Load the sigrok firmware into a Hantek 6022BE that still shows its factory ID (04b4:6022).
usage: scope_loadfw.py <fx2lafw-hantek-6022be.fw>   (for a computer without sigrok-cli, e.g. the Pi)

Needs: the scope on USB, pyusb, libusb at the path hard-coded below, usually root rights, and
the firmware file from the sigrok project. The file is sent as a flat memory image starting at
address 0.
Prints "firmware loaded" once the scope has come back with the sigrok ID (1d50:608e), which is
what scope.py looks for. Exits with a message if the firmware is already loaded, if no scope is
found, or if the scope does not reappear within 10 s. The firmware lives in RAM: this has to be
done again after each power-up of the scope.
"""

import sys, time, usb.core, usb.backend.libusb1 as b

# Where libusb lives: the Homebrew path on a Mac, the Debian arm64 path otherwise (the Pi).
lib = (
    "/opt/homebrew/lib/libusb-1.0.dylib"
    if sys.platform == "darwin"
    else "/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0"
)
be = b.get_backend(find_library=lambda x: lib)
# 1d50:608e = already running the sigrok firmware; nothing to do.
if usb.core.find(idVendor=0x1D50, idProduct=0x608E, backend=be) is not None:
    raise SystemExit("firmware already loaded")
# 04b4:6022 = the ID of the scope as it powers up, before any firmware is loaded.
d = usb.core.find(idVendor=0x04B4, idProduct=0x6022, backend=be)
if d is None:
    raise SystemExit("scope not found")
fw = open(sys.argv[1], "rb").read()
# The scope's processor accepts memory writes through vendor request 0xA0: the value field is
# the address, the data are the bytes to store there. Address 0xE600 is its control register:
# writing 1 stops the processor, writing 0 starts it.
d.ctrl_transfer(0x40, 0xA0, 0xE600, 0, b"\x01", 1000)  # hold the processor in reset
# Send the firmware image 4096 bytes at a time; off is the address of each piece.
for off in range(0, len(fw), 4096):
    d.ctrl_transfer(0x40, 0xA0, off, 0, fw[off : off + 4096], 1000)
d.ctrl_transfer(0x40, 0xA0, 0xE600, 0, b"\x00", 1000)  # let it run
# The scope now drops off the bus and comes back under its new ID. Look for it every 0.2 s,
# for up to 50 tries (10 s).
for _ in range(50):
    time.sleep(0.2)
    if usb.core.find(idVendor=0x1D50, idProduct=0x608E, backend=be) is not None:
        print("firmware loaded")
        break
else:
    raise SystemExit("scope did not come back")
