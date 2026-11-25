"""Minimal Hantek 6022BE capture (sigrok fx2lafw firmware must already be loaded).

As a module: provides the Scope class used by the other scope scripts (scope_daemon.py,
scope_live.py, run_capture.py, burst_scope.py, solenoid_step.py).

As a script: makes one capture and saves it.
usage: scope.py <rate MS/s> <range1> <range2> <channels> <megabytes> <out.npy> [delay s]
  rate       sample rate in million samples per second: 48, 30, 24, 16, 8, 4 or 1
  range1/2   input range of CH1 / CH2: 100mV, 250mV, 500mV or 1V (volts per division at the scope
             input, before any probe attenuation)
  channels   1 or 2
  megabytes  amount of data to capture, in units of 2**20 bytes (may be fractional)
  delay      optional wait in seconds between configuring the scope and starting the capture

Needs: the scope on USB showing the sigrok ID 1d50:608e (load the firmware with
"sigrok-cli --scan" or scope_loadfw.py), pyusb, libusb at the path hard-coded below, and
usually root rights to open the USB device.
Writes: <out.npy>, a one-dimensional numpy uint8 array of raw ADC counts. With two channels the
bytes alternate CH1, CH2, CH1, CH2... Prints the amount captured and the achieved data rate.
"""

import sys, time, numpy as np, usb.core, usb.util, usb.backend.libusb1 as b

# Value written to a channel's gain register for each input range name. The names are volts per
# division at the scope input; the values are what the firmware expects (they look like the
# amplifier gain: the most sensitive range has the highest number).
GAIN = {"1V": 1, "500mV": 2, "250mV": 5, "100mV": 10}
# Value written to the sample-rate register for each rate in MS/s (the same number).
RATE = {48: 48, 30: 30, 24: 24, 16: 16, 8: 8, 4: 4, 1: 1}


class Scope:
    """The oscilloscope, opened over USB. One instance claims the device for this process."""

    def __init__(self):
        """Find the scope on USB and claim its interface. Exits the program if it is not there."""
        # pyusb is told exactly where libusb lives: the Homebrew path on a Mac, the Debian arm64
        # path otherwise (the Raspberry Pi).
        lib = (
            "/opt/homebrew/lib/libusb-1.0.dylib"
            if sys.platform == "darwin"
            else "/usr/lib/aarch64-linux-gnu/libusb-1.0.so.0"
        )
        be = b.get_backend(find_library=lambda x: lib)
        # 1d50:608e is the ID the scope shows once the sigrok firmware is running.
        self.d = usb.core.find(idVendor=0x1D50, idProduct=0x608E, backend=be)
        if self.d is None:
            raise SystemExit('scope not found (run "sigrok-cli --scan" once to load its firmware)')
        self.d.set_configuration()
        usb.util.claim_interface(self.d, 0)

    def reg(self, r, v):
        """Write the one-byte value v to the firmware's control register r.

        r is used as the USB request number of a vendor request from host to device (0x40);
        the timeout is 200 ms.
        """
        self.d.ctrl_transfer(0x40, r, 0, 0, bytes([v]), 200)

    def setup(self, rate_mhz, g1, g2, nch=2):
        """Stop any capture and configure the scope.

        rate_mhz: sample rate in MS/s (a key of RATE); g1, g2: range names for CH1 and CH2
        (keys of GAIN); nch: number of channels to sample (1 or 2).
        """
        self.nch = nch
        # Registers, as far as this code shows: 0xE3 = run (1) / stop (0), 0xE0 = CH1 gain,
        # 0xE1 = CH2 gain, 0xE2 = sample rate, 0xE4 = number of channels.
        self.reg(0xE3, 0)
        self.reg(0xE0, GAIN[g1])
        self.reg(0xE1, GAIN[g2])
        self.reg(0xE2, RATE[rate_mhz])
        self.reg(0xE4, nch)

    def capture(self, nbytes, chunk=1 << 20):
        """Capture at least nbytes bytes of samples.

        nbytes: amount wanted, in bytes (with two channels, half that many samples per channel).
        chunk: size in bytes of each USB read.
        Returns a list of uint8 numpy arrays, one per USB read. Each array is contiguous in
        time, but samples may have been lost between one array and the next. The total can
        exceed nbytes by up to one chunk.
        """
        out = []
        # Start sampling.
        self.reg(0xE3, 1)
        try:
            # 0x86 is the bulk IN endpoint the samples arrive on. Arguments: size in bytes, timeout
            # in ms.
            self.d.read(0x86, 1 << 16, 1000)  # discard start-up junk
            got = 0
            while got < nbytes:
                a = np.frombuffer(self.d.read(0x86, chunk, 2000), dtype=np.uint8)
                out.append(a)
                got += len(a)
        finally:
            # Stop sampling, whether the reads succeeded or not.
            self.reg(0xE3, 0)
        return out


if __name__ == "__main__":
    # Command-line use: see the module docstring. mb = megabytes to capture, outf = output file.
    rate, g1, g2, nch, mb, outf = (
        int(sys.argv[1]),
        sys.argv[2],
        sys.argv[3],
        int(sys.argv[4]),
        float(sys.argv[5]),
        sys.argv[6],
    )
    delay = float(sys.argv[7]) if len(sys.argv) > 7 else 0
    s = Scope()
    s.setup(rate, g1, g2, nch)
    # Optional pause, so that something else can be started before the capture begins.
    time.sleep(delay)
    # Capture, timing it to see whether the USB link kept up with the sample rate.
    t = time.time()
    chunks = s.capture(int(mb * (1 << 20)))
    dt = time.time() - t
    n = sum(len(c) for c in chunks)
    # "continuous would be" is the data rate the scope produces (rate x channels); a lower achieved
    # rate means there are gaps between chunks.
    print(
        "captured %.1f MB in %.2f s (%.1f MB/s; continuous would be %.1f MB/s), %d chunks"
        % (n / 2**20, dt, n / 2**20 / dt, rate * nch * 1e6 / 2**20, len(chunks))
    )
    # All chunks are joined end to end; any gaps between them are not marked in the file.
    np.save(outf, np.concatenate(chunks))
