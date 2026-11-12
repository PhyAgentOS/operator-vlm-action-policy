"""Original implementation of the public Forge Arrow field contracts.

No SDK source is vendored. These narrow carriers avoid pulling unrelated image
and robot SDK dependencies into the generic action runtime.
"""

from __future__ import annotations

import base64
import io

import numpy as np
from PIL import Image

from .contracts import ImageInput


def batch(value):
    import pyarrow as pa

    if isinstance(value, pa.RecordBatch):
        return value
    if isinstance(value, pa.Table):
        return value.combine_chunks().to_batches()[0]
    if isinstance(value, pa.StructArray):
        return pa.RecordBatch.from_struct_array(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return pa.ipc.open_stream(bytes(value)).read_next_batch()
    raise ValueError("unsupported Arrow carrier")


def row(value):
    value = batch(value)
    if value.num_rows != 1:
        raise ValueError("message must contain exactly one row")
    return {name: value[name][0].as_py() for name in value.schema.names}


def state_values(value, names):
    data = row(value)
    if len(data["name"]) != len(data["position"]) or len(set(data["name"])) != len(data["name"]):
        raise ValueError("invalid state name/value mapping")
    values = dict(zip(data["name"], data["position"], strict=True))
    if any(name not in values for name in names):
        raise ValueError("missing required state name")
    ordered = [float(values[name]) for name in names]
    if not np.isfinite(ordered).all():
        raise ValueError("state contains nonfinite values")
    return ordered


def image_input(value, max_pixels):
    data = row(value)
    encoding = data.get("encoding")
    if encoding not in {"rgb8", "bgr8"}:
        raise ValueError("only raw rgb8/bgr8 Forge Image is supported")
    h, w, stride = int(data["height"]), int(data["width"]), int(data["step"])
    if min(h, w) <= 0 or h * w > max_pixels or stride < w * 3:
        raise ValueError("invalid image dimensions/stride")
    raw = data["data"]
    if len(raw) != h * stride:
        raise ValueError("invalid image byte length")
    pixels = np.frombuffer(raw, dtype=np.uint8).reshape(h, stride)[:, : w * 3].reshape(h, w, 3)
    if encoding == "bgr8":
        pixels = pixels[..., ::-1]
    buffer = io.BytesIO()
    Image.fromarray(pixels).save(buffer, format="PNG")
    return ImageInput(data=base64.b64encode(buffer.getvalue()).decode())


def joint_command(values):
    import pyarrow as pa

    vector = lambda x: pa.array([x], type=pa.list_(pa.float64()))  # noqa: E731
    return pa.RecordBatch.from_pydict(
        {
            "name": pa.array([values["name"]], type=pa.list_(pa.string())),
            "mode": pa.array(["position"], type=pa.string()),
            "position": vector(values["position"]),
            "velocity": vector([]),
            "effort": vector([]),
            "kp": vector([]),
            "kd": vector([]),
        }
    )
