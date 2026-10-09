"""Select the supported Ultralytics precision argument without warning spam."""


def inference_precision(half_precision, defaults):
    if "quantize" in defaults:
        return {"quantize": 16 if half_precision else None}
    return {"half": bool(half_precision)}
