"""Capture both scope channels (yellow = CH1, blue = CH2, both x10 probes, 250 mV range)
while one command is sent to the setstate sketch, and save a picture.

usage: chipcap.py <scratch> <port> <tag> "<yellow label>" "<blue label>" "<command>"
                  [seconds] [hold-command]

The board is reset on opening the port (all outputs off); 'hold-command', if given, is
sent first.
Env: RATE (MS/s, default 16), ZOOM_US (half-width of the detail view, default 400).

  scratch       folder that holds scripts/scope.py (the scope driver), out/scope_zero.json
                (zero level of each channel per input range) and receives the output files
  port          serial port of the controller (115200 baud)
  tag           name used in the output file names and as the title of the picture
  yellow label, blue label   what each probe is connected to, used as axis labels
  command       line sent to the sketch while the scope is recording, e.g. "b 20 F676 F677 5"
  seconds       how long to keep recording after sending the command (default 0.6)
  hold-command  a command sent one second before the recording starts, e.g. to put a
                steady state on the outputs
  Env WATCH     if set, the bench supply is polled every 0.1 s for that many seconds
                through tools/psu, and its voltage and current are plotted as well

Firmware needed on the board: setstate (../setstate/src/main.cpp); commands 'n XXXX',
'm XXXX', 'r' and 'b N XXXX YYYY D'.

Prints the end of the READY line, the replies to the commands, the median, minimum and
maximum of each channel, and for a channel that switches, its number of edges and its low
and high levels. Writes in <scratch>/out:
  chip_<tag>.npy         the first 8 million raw bytes (channels interleaved)
  chip_<tag>.png         both channels in three views: whole capture, first activity,
                         largest deviation of the yellow channel
  chip_<tag>_supply.png  supply current and voltage over time (only with WATCH)"""

import sys, os, json, time, threading, subprocess, numpy as np, serial

# Command line. S is the scratch folder.
S, port, tag, ylab, blab, command = sys.argv[1:7]
secs = float(sys.argv[7]) if len(sys.argv) > 7 else 0.6
hold = sys.argv[8] if len(sys.argv) > 8 else None
sys.path.insert(0, S + "/scripts")
from scope import Scope
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Z = zero levels in raw counts, looked up as Z[range]["ch1_zero"] and ["ch2_zero"].
# MS = sample rate in MS/s, RATE = the same in samples per second per channel.
# ZOOM = half-width of the detail view in microseconds. R = input range of both channels.
Z = json.load(open(S + "/out/scope_zero.json"))
MS = int(os.environ.get("RATE", "16"))
RATE = MS * 1e6
ZOOM = float(os.environ.get("ZOOM_US", "400"))
R = "250mV"
K = 10.0 / 128  # volts per count at a x10 tip
YC, BC = "#c9a400", "#1f5fd0"  # plot colours: yellow channel, blue channel
sc = Scope()
sc.setup(MS, R, R, 2)
p = serial.Serial(port, 115200, timeout=0.2)


def wait(tok, t=4):
    """Read from the serial port until a given byte string has arrived.

    tok: the bytes to wait for, for example b"READY" or b"\\n".
    t:   maximum time to wait, in seconds.
    Returns everything received, as text with surrounding white space removed."""
    end = time.time() + t
    buf = b""
    while time.time() < end and tok not in buf:
        buf += p.read(64)
    return buf.decode("ascii", "replace").strip()


# Opening the port has reset the board: wait for the READY line and show its last 16
# characters (the state read back at start-up).
print("board:", wait(b"READY")[-16:])
# optional supply tracking through the Pi
# psu_log: (seconds since t0, volts, amps) for each supply reading.
# t0: time origin shared by the supply readings and the event list 'ev'.
psu_log = []
t0 = time.time()
watch = None
# tools/psu watch <seconds> 0.1 prints one line "<time> <volts> <amps>" every 0.1 s.
if os.environ.get("WATCH"):
    watch = subprocess.Popen(
        [os.path.dirname(os.path.abspath(__file__)) + "/psu", "watch", os.environ["WATCH"], "0.1"],
        stdout=subprocess.PIPE,
        text=True,
    )

    def _w():
        """Thread body: store each reading printed by the psu watch process in psu_log.

        Takes no argument and returns nothing; ends when the process closes its output."""
        for line in watch.stdout:
            f = line.split()
            if len(f) == 3:
                psu_log.append((time.time() - t0, float(f[1]), float(f[2])))

    threading.Thread(target=_w, daemon=True).start()
    # Give the watch process time to connect and deliver its first readings.
    time.sleep(1.2)
# ev: (seconds since t0, label) of the moments marked on the supply plot.
ev = []
# Optional hold command, then one second for the outputs and the supply to settle.
if hold:
    ev.append((time.time() - t0, "hold: " + hold))
    p.reset_input_buffer()
    p.write((hold + "\n").encode())
    print("  %s -> %s" % (hold, wait(b"\n", 3)))
    time.sleep(1.0)
# chunks: the 1 MB blocks read from the scope. run: set to False to stop the grab thread.
chunks = []
run = True


def grab():
    """Scope thread: sample continuously into 'chunks' until 'run' becomes false.

    Takes no argument and returns nothing. Register 0xE3 starts (1) and stops (0) the
    sampling; the first 64 KB read from USB endpoint 0x86 are start-up junk and are
    dropped; after that each read returns up to 1 MB (2 s timeout)."""
    sc.reg(0xE3, 1)
    sc.d.read(0x86, 1 << 16, 1000)
    while run:
        chunks.append(np.frombuffer(sc.d.read(0x86, 1 << 20, 2000), dtype=np.uint8))
    sc.reg(0xE3, 0)


# Start recording, send the command 0.15 s later, keep recording for 'secs' seconds, stop,
# and only then collect the reply (waiting up to 60 s, since a long burst may still run).
th = threading.Thread(target=grab)
th.start()
time.sleep(0.15)
ev.append((time.time() - t0, "command"))
p.reset_input_buffer()
p.write((command + "\n").encode())
time.sleep(secs)
run = False
th.join()
print("  %s -> %s" % (command, wait(b"\n", 60)))
ev.append((time.time() - t0, "done"))
# With supply tracking: wait one more second so the plot shows what follows the command.
if watch:
    time.sleep(1.0)
# Split the recording: even bytes are the yellow channel (y), odd bytes the blue one (b),
# both converted to volts at the probe tip. n = samples per channel.
a = np.concatenate(chunks)
y = (a[0::2].astype(float) - Z[R]["ch1_zero"]) * K
b = (a[1::2].astype(float) - Z[R]["ch2_zero"]) * K
n = len(y)


def desc(v):
    """Return a one-line summary (median, minimum, maximum, in volts) of a channel.

    v: array of voltages."""
    return "median %.2f V, min %.2f V, max %.2f V" % (np.median(v), v.min(), v.max())


print("yellow (%s): %s" % (ylab, desc(y)))
print("blue   (%s): %s" % (blab, desc(b)))
# A channel is treated as switching when its 0.5th and 99.5th percentiles are more than
# 1.5 V apart. The threshold is halfway between them; an edge is any crossing of it.
for nm, v in (("yellow", y), ("blue", b)):
    lo_, hi_ = np.percentile(v, 0.5), np.percentile(v, 99.5)
    if hi_ - lo_ > 1.5:
        h = v > (lo_ + hi_) / 2
        e = np.flatnonzero(h[1:] != h[:-1])
        print(
            "   %s switches: %d edges; low level %.2f V, high level %.2f V"
            % (nm, len(e), np.median(v[~h]), np.median(v[h]))
        )
# Keep the start of the recording: 8 million bytes are 4 million samples per channel
# (0.25 s at 16 MS/s).
np.save("%s/out/chip_%s.npy" % (S, tag), a[: int(8e6)])


# views: whole capture, first activity on blue (or yellow) in detail, largest yellow deviation
def first_edge(v):
    """Return the index of the first edge of a channel, or None if it does not switch.

    v: array of voltages. The same switching test and threshold as above are used.
    The index counts samples from the start of the recording."""
    lo_, hi_ = np.percentile(v, 0.5), np.percentile(v, 99.5)
    if hi_ - lo_ < 1.5:
        return None
    h = v > (lo_ + hi_) / 2
    e = np.flatnonzero(h[1:] != h[:-1])
    return int(e[0]) if len(e) else None


# fe: where the detail view is anchored: first edge of blue, else first edge of yellow,
# else the middle of the recording.
fe = first_edge(b)
fe = first_edge(y) if fe is None else fe
fe = n // 2 if fe is None else fe
# dy: distance of the yellow channel from its median; wi: sample where it is largest.
dy = np.abs(y - np.median(y))
wi = int(np.argmax(dy))
# 'cols' is not used below: the picture always has three columns, and the supply goes
# into a separate picture.
cols = 3 + (1 if psu_log else 0)
fig, ax = plt.subplots(2, 3, figsize=(15, 6.5))
# The three views: (title, centre sample, half-width in microseconds).
#   whole capture: centred on the middle, half-width = half the recording
#   first activity: starts 0.4 x ZOOM before the first edge and ends 1.6 x ZOOM after it
#   largest yellow deviation: 15 microseconds on each side
for c, (name, i, us) in enumerate(
    (
        ("whole capture", n // 2, n / RATE * 5e5),
        ("first activity in detail", fe + int(ZOOM * 0.6e-6 * RATE), ZOOM),
        ("largest yellow deviation (%.2f V from median)" % dy[wi], wi, 15),
    )
):
    # w: half-width in samples. step: plot at most about 40000 points by taking blocks of
    # 'step' samples. The time axis is in ms for views wider than 5 ms each side, else in
    # microseconds. Individual samples get a dot when the view is 20 us or narrower.
    w = int(us * 1e-6 * RATE)
    lo, hi_ = max(0, i - w), min(n, i + w)
    step = max(1, (hi_ - lo) // 40000)
    t = (np.arange(lo, hi_, step) - i) / RATE * (1e3 if us > 5000 else 1e6)
    mk = "." if us <= 20 else None
    if step > 1:  # show the envelope so that single-sample spikes are not lost
        m = (hi_ - lo) // step
        yy = y[lo : lo + m * step].reshape(m, step)
        bb = b[lo : lo + m * step].reshape(m, step)
        tt = t[:m]
        ax[0, c].fill_between(tt, yy.min(1), yy.max(1), color=YC)
        ax[1, c].fill_between(tt, bb.min(1), bb.max(1), color=BC)
    else:
        ax[0, c].plot(t, y[lo:hi_], color=YC, lw=0.8, marker=mk, ms=3)
        ax[1, c].plot(t, b[lo:hi_], color=BC, lw=0.8, marker=mk, ms=3)
    ax[0, c].set_title(name, fontsize=10)
    ax[0, c].grid(alpha=0.3)
    ax[1, c].grid(alpha=0.3)
    ax[1, c].set_xlabel("ms" if us > 5000 else "µs")
ax[0, 0].set_ylabel("YELLOW: %s (V)" % ylab)
ax[1, 0].set_ylabel("BLUE: %s (V)" % blab)
fig.suptitle("%s   [command: %s%s]" % (tag, command, ("; held: " + hold) if hold else ""))
fig.tight_layout()
fig.savefig("%s/out/chip_%s.png" % (S, tag), dpi=75)
# Supply picture: current in mA on the left axis, voltage on the right axis, with a dotted
# vertical line at each event (hold command, command, done).
if psu_log:
    # Wait for the watch process to finish its WATCH seconds, so that psu_log is complete.
    watch.wait(timeout=30)
    L = np.array(psu_log)
    fig, ax = plt.subplots(figsize=(11, 3.4))
    ax2 = ax.twinx()
    ax.plot(L[:, 0], L[:, 2] * 1000, "C3.-", ms=3, lw=0.8)
    ax2.plot(L[:, 0], L[:, 1], "C2", lw=0.8)
    for t, name in ev:
        ax.axvline(t, color="gray", ls=":")
        ax.text(t, 5, " " + name, rotation=90, fontsize=7, va="bottom")
    ax.set_xlabel("s")
    ax.set_ylabel("supply current (mA), red")
    ax2.set_ylabel("supply voltage (V), green")
    ax2.set_ylim(0, max(4.0, L[:, 1].max() * 1.15))
    ax.grid(alpha=0.3)
    ax.set_title("%s: bench supply as reported through the Pi" % tag)
    fig.tight_layout()
    fig.savefig("%s/out/chip_%s_supply.png" % (S, tag), dpi=75)
    print(
        "supply: voltage %.3f to %.3f V; current min %.0f mA, max %.0f mA over %d readings"
        % (L[:, 1].min(), L[:, 1].max(), L[:, 2].min() * 1000, L[:, 2].max() * 1000, len(L))
    )
