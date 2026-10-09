#!/usr/bin/env python3
"""Record a manual CS2 walk and measured poses. Never imports input controls."""
import argparse
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'vendor/csgobot'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--map-id', default='de_dust2')
    parser.add_argument('--seconds', type=float, default=120)
    parser.add_argument('--stop-file', type=Path)
    args = parser.parse_args()
    if sys.platform != 'win32':
        parser.error('Live capture requires Windows')
    if not 0 < args.seconds <= 600:
        parser.error('Duration must be 1–600 seconds')
    import cv2
    import win32gui
    from run import create_config, OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT
    from config import CaptureRegion
    from grabbers import get_grabber
    from nav.calibration import load_calibration
    from nav.paths import resolve_calibration_path
    from nav.minimap_reader import MinimapReader
    from nav.place_localizer import PlaceLocalizer
    from nav.visual_perception import VisualPerception
    config = create_config()
    if config.grabber_type == 'obs_vc':
        config.capture_region = CaptureRegion(0, 0, OBS_CANVAS_WIDTH, OBS_CANVAS_HEIGHT)
    else:
        from utils.win32 import get_window_rect
        config.capture_region = CaptureRegion(*get_window_rect(config.window_title, config.border_offsets))
    if (config.capture_region.width, config.capture_region.height) != (1280, 720):
        raise ValueError('Recording requires 1280x720')
    args.output.mkdir(parents=True, exist_ok=True)
    perception = VisualPerception(MinimapReader(load_calibration(resolve_calibration_path())), PlaceLocalizer(args.map_id))
    grabber = get_grabber(config.grabber_type, **config.grabber_options)
    writer = None
    started, count, accepted = time.monotonic(), 0, 0
    print('RECORDING ONLY: walk manually in CS2. No input is sent.', flush=True)
    try:
        writer = cv2.VideoWriter(str(args.output/'walk.mp4'), cv2.VideoWriter_fourcc(*'mp4v'), 10, (1280, 720))
        if not writer.isOpened():
            raise RuntimeError('Video encoder unavailable')
        with (args.output/'trace.jsonl').open('w', encoding='utf-8') as log:
            log.write(json.dumps({'type': 'identity', 'map_id': args.map_id, 'mode': 'manual_record', 'video_fps': 10})+'\n')
            while time.monotonic()-started < args.seconds:
                if args.stop_file and args.stop_file.exists():
                    break
                if config.window_title.lower() not in win32gui.GetWindowText(win32gui.GetForegroundWindow()).lower():
                    time.sleep(.1)
                    continue
                stamp = time.monotonic()
                frame = grabber.get_image(config.capture_region.to_dict())
                if frame is None:
                    time.sleep(.02)
                    continue
                if frame.shape[:2] != (720, 1280):
                    raise ValueError('Capture resolution changed')
                result = perception.update(frame, now=stamp)
                p = result.pose
                writer.write(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
                log.write(json.dumps({'t': stamp-started, 'video_frame': count, 'valid': p.valid,
                    'x': p.x_norm, 'y': p.y_norm, 'yaw': p.yaw_deg, 'confidence': p.confidence,
                    'reason': perception.reason, 'map_id': args.map_id})+'\n')
                log.flush()
                count += 1
                accepted += int(p.valid)
                if count % 50 == 0:
                    print(f'{time.monotonic()-started:.0f}s: {count} frames; measured {accepted}', flush=True)
                time.sleep(max(0, .1-(time.monotonic()-stamp)))
    finally:
        grabber.cleanup()
        if writer:
            writer.release()
    summary = {'map_id': args.map_id, 'frames': count, 'accepted': accepted, 'input_sent': False,
               'note': 'Video is sampled at 10 fps; trace timestamps preserve actual capture times. No walkability inferred.'}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)
    if not count:
        raise RuntimeError('Нет кадров: верните фокус в окно CS2 и проверьте источник захвата')


if __name__ == '__main__':
    main()
