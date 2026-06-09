from typing import Dict, Optional, Any

import cv2
import numpy as np

from .base import BaseGrabber
from exceptions import DeviceNotFoundError


class OBSVirtualCameraGrabber(BaseGrabber):
    """
    OBS Virtual Camera grabber.

    Note: OBS captures the full source, so left/top offsets are handled by cropping.
    For best results, configure OBS to capture only the game window.
    """

    _type = "obs_vc"

    def __init__(self):
        self._device: Optional[cv2.VideoCapture] = None
        self._size_configured = False
        self._frame_width = 0
        self._frame_height = 0

    def initialize(
        self,
        device_index: int = -1,
        device_name: str = "OBS Virtual Camera",
        **kwargs: Any,
    ) -> None:
        if device_index >= 0:
            self._device = cv2.VideoCapture(device_index)
            self._device.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            from pygrabber.dshow_graph import FilterGraph
            graph = FilterGraph()
            devices = graph.get_input_devices()

            try:
                idx = devices.index(device_name)
            except ValueError:
                raise DeviceNotFoundError(
                    f'Device "{device_name}" not found. Available: {devices}'
                )

            self._device = cv2.VideoCapture(idx)

        if self._device is not None:
            # Low latency: drop buffered frames, request 30 FPS from virtual cam.
            self._device.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _configure_size(self, width: int, height: int) -> None:
        if self._device is not None:
            self._device.set(cv2.CAP_PROP_FPS, 30)
            self._device.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self._device.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self._frame_width = int(self._device.get(cv2.CAP_PROP_FRAME_WIDTH))
            self._frame_height = int(self._device.get(cv2.CAP_PROP_FRAME_HEIGHT))
            self._size_configured = True

    def get_image(self, grab_area: Dict[str, int]) -> Optional[np.ndarray]:
        if self._device is None:
            self.initialize()

        width = grab_area["width"]
        height = grab_area["height"]

        # Virtual Camera carries the OBS scene only — no desktop (left/top) offset.
        if not self._size_configured:
            self._configure_size(width, height)

        ret, frame = self._device.read()
        if not ret or frame is None:
            return None

        # Avoid cv2.cvtColor SIMD size constraints on odd frame dimensions.
        frame = np.ascontiguousarray(frame[:, :, ::-1])

        fh, fw = frame.shape[:2]
        if fw != width or fh != height:
            frame = cv2.resize(
                frame, (width, height), interpolation=cv2.INTER_LINEAR,
            )

        return frame

    def cleanup(self) -> None:
        if self._device is not None:
            self._device.release()
            self._device = None
            self._size_configured = False
