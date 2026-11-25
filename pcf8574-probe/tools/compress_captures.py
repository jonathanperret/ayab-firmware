"""Losslessly compress every .npy capture in a folder to .npz (zlib), checking each before removing
the original.
usage: compress_captures.py <folder>      Read them back with capio.load().

Each x.npy becomes x.npz holding the same array under the name "a". The .npz is read back and
compared with the original (same data type, same values) before the .npy is deleted; on a
mismatch the .npz is deleted instead and the original is kept. An existing x.npz is overwritten.
Prints one line per mismatch and, at the end, the total size before and after in megabytes
(whole megabytes, rounded down), counting only the files that were converted.
"""

import sys, os, glob, numpy as np

# d = the folder to process; before / after = total bytes of the originals / of the compressed
# files.
d = sys.argv[1]
before = after = 0
for f in sorted(glob.glob(os.path.join(d, "*.npy"))):
    a = np.load(f)
    out = f[:-4] + ".npz"
    np.savez_compressed(out, a=a)
    # Read the compressed file back and check that it holds exactly the same array.
    with np.load(out) as z:
        ok = z["a"].dtype == a.dtype and np.array_equal(z["a"], a)
    if not ok:
        os.remove(out)
        print("MISMATCH, kept original:", f)
        continue
    before += os.path.getsize(f)
    after += os.path.getsize(out)
    os.remove(f)
print("%d MB -> %d MB" % (before / 2**20, after / 2**20))
