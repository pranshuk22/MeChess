"""Loading checkpoints without running code from them.

`torch.load(..., weights_only=False)` unpickles arbitrary objects: a tampered `.pt` file (these files travel through Kaggle and back) would run code when loaded. With
`weights_only=True` only tensors and plain containers load. Some of our files also hold small NumPy arrays (the adapter's feature mean and std), so exactly the NumPy
pieces needed to rebuild an array are allowed, and nothing else."""
import numpy as np


def numpy_globals():
    out = [np.ndarray, np.dtype]
    for mod in ("numpy._core.multiarray", "numpy.core.multiarray"):
        try:
            m = __import__(mod, fromlist=["_reconstruct", "scalar"])
        except ImportError:
            continue
        out += [getattr(m, n) for n in ("_reconstruct", "scalar") if hasattr(m, n)]
        break
    out += [getattr(np.dtypes, n) for n in dir(np.dtypes) if n.endswith("DType") and isinstance(getattr(np.dtypes, n), type)] if hasattr(np, "dtypes") else []
    return out


def load(path, map_location="cpu"):
    """`torch.load` with `weights_only=True` plus the NumPy array pieces."""
    import torch
    with torch.serialization.safe_globals(numpy_globals()):
        return torch.load(path, map_location=map_location, weights_only=True)
