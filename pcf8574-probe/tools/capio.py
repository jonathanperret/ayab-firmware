"""Reading captures, compressed or not. load('x.npy') also finds 'x.npz' (and the reverse).

A module, not a script: the analysis scripts import it. Captures are saved by the scope scripts
as .npy files and may later be compressed to .npz by compress_captures.py; with this loader the
analysis scripts work on either without caring which one is on disk.
"""

import os, numpy as np


def load(path):
    """Load a capture as a numpy array.

    path: file name ending in .npy or .npz, or with no extension. The uncompressed .npy is
    used if it exists; otherwise the .npz is opened and its array named "a" is returned (the
    name compress_captures.py stores it under). Raises FileNotFoundError if neither exists.
    """
    # base = the path without its extension.
    base = path[:-4] if path.endswith((".npy", ".npz")) else path
    if os.path.exists(base + ".npy"):
        return np.load(base + ".npy")
    with np.load(base + ".npz") as z:
        return z["a"]
