"""Live viewer for the Thermal Master / InfiRay P2 Pro, Lightning (iOS) version, on a PC.

The camera is an Apple iAP2 accessory. We play the iPhone's role (see iap2.py), send the
initialisation sequence the iOS app sends (init_cmds.json, captured with a USB analyzer),
then decode the raw 14-bit sensor stream and correct it with the camera's shutter.

Mouse:
  left click          add a temperature cursor
  left drag           draw a rectangle (shows min / max / average inside)
  right click         delete the cursor / rectangle under the mouse
Keys:
  a                   toggle adaptive colour scale  <->  fixed scale
  arrows              fixed scale: Up/Down = top +/-1 C, Right/Left = bottom +/-1 C
  k                   temperature calibration: click a spot, type its real temperature, Enter
  r                   reset temperature calibration to defaults
  c                   shutter calibration (flat-field) now
  x                   clear all cursors and rectangles
  p                   next colour palette
  s                   save a snapshot PNG
  h                   show / hide help
  q / Esc / close     quit

NOTE: the camera must be unplugged and plugged back in before every start.
"""
import json
import os
import queue
import threading
import time

import cv2
import numpy as np

from iap2 import Link, msg, usb

HERE = os.path.dirname(os.path.abspath(__file__))
INIT_CMDS = json.load(open(os.path.join(HERE, 'init_cmds.json')))
CALIB_FILE = os.path.join(HERE, 'calib.json')

FRAME_BYTES = 106080            # 260 x 204 x uint16 per frame (210 USB packets x 506 payload bytes)
IMG = (slice(6, 202), slice(2, 258))   # 256 x 196 image area; rows 0-5 and 202-203 are header/reference/telemetry
W, H = 256, 196
SCALE = 3
BAR_W = 80                      # colour bar width
STATUS_H = 26
WIN = 'P2 Pro thermal'

SHUTTER_CLOSE = ('06 1e 00 10 00 10', '06 1e 00 10 00 00')
SHUTTER_OPEN = ('06 1e 00 40 00 40', '06 1e 00 40 00 00')
AUTO_SHUTTER_S = 60

# Linear model: T = offset + gain * (shutter_ref - raw). Defaults estimated from sensor noise
# (~3.6 counts rms at the rated 40 mK NETD); refine with the 'k' calibration.
DEFAULT_CALIB = {'gain': 0.012, 'offset': 28.0}

PALETTES = [('inferno', cv2.COLORMAP_INFERNO), ('ironbow', cv2.COLORMAP_HOT), ('jet', cv2.COLORMAP_JET),
            ('turbo', cv2.COLORMAP_TURBO), ('gray', None)]


class Camera:
    def __init__(self):
        self.l = l = Link()
        l.connect()
        c = l.sess

        def x(mid, params=(), wait=3000):
            l.send(c, msg(mid, params))
            return l.recv(wait)
        x(0xAA00)                                   # RequestAuthenticationCertificate
        x(0xAA02, [(0, os.urandom(32))])            # RequestAuthenticationChallengeResponse
        l.send(c, msg(0xAA05))                      # AuthenticationSucceeded (we don't verify)
        x(0x1D00)                                   # StartIdentification
        l.send(c, msg(0x1D02))                      # IdentificationAccepted
        l.recv(1500)                                # camera sends RequestAppLaunch; ignore
        self.d = d = l.d
        usb.util.claim_interface(d, 1)
        d.set_interface_altsetting(1, 1)            # open the EA native-transport data channel
        print('iAP2 handshake ok')

        self.run = True
        self.q = queue.Queue()
        self.cv = threading.Condition()
        self.frame, self.nframe = None, 0
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._keep_link, daemon=True).start()

        t0 = time.time()
        for cmd in INIT_CMDS:                       # send the iOS app's init sequence, ends with start-stream
            self.cmd(cmd)
            try:
                self.q.get(timeout=0.5)
            except queue.Empty:
                pass
        print(f'init sequence sent ({len(INIT_CMDS)} commands, {time.time() - t0:.1f}s)')
        threading.Thread(target=self._frame_loop, daemon=True).start()
        self.ref = None

    def cmd(self, hexstr):
        self.d.write(0x07, bytes.fromhex(hexstr), 1000)

    def pulse(self, pair):
        self.cmd(pair[0])
        time.sleep(0.07)
        self.cmd(pair[1])

    def _reader(self):
        while self.run:
            try:
                self.q.put(bytes(self.d.read(0x82, 1 << 20, 500)))
            except usb.core.USBTimeoutError:
                pass
            except Exception as e:
                if self.run:
                    print('USB read error:', e)
                self.run = False

    def _keep_link(self):                           # keep ACKing the iAP2 control link
        while self.run:
            self.l.recv(200)

    def _frame_loop(self):
        cur, fid = bytearray(), None
        while self.run:
            try:
                chunk = self.q.get(timeout=1)
            except queue.Empty:
                continue
            for o in range(0, len(chunk), 512):
                p = chunk[o:o + 512]
                if len(p) < 8 or p[0] != 6 or not (p[1] & 0x80):
                    continue                        # command replies / junk
                f = p[1] & 1                        # frame-id bit toggles every frame
                if fid is not None and f != fid:
                    if len(cur) == FRAME_BYTES:
                        fr = np.frombuffer(bytes(cur), '<u2').reshape(204, 260).astype(np.float32)
                        with self.cv:
                            self.frame, self.nframe = fr, self.nframe + 1
                            self.cv.notify_all()
                    cur = bytearray()
                fid = f
                cur += p[6:]

    def wait_frame(self, after, timeout=2.0):
        with self.cv:
            self.cv.wait_for(lambda: self.nframe > after or not self.run, timeout)
            return self.frame, self.nframe

    def shutter_calibrate(self):
        self.pulse(SHUTTER_CLOSE)
        time.sleep(0.35)
        _, n = self.wait_frame(0, 0)
        refs = []
        while len(refs) < 8 and self.run:
            fr, n = self.wait_frame(n)
            if fr is not None:
                refs.append(fr)
        self.pulse(SHUTTER_OPEN)
        time.sleep(0.25)
        if refs:
            self.ref = np.mean(refs, 0)

    def close(self):
        try:
            self.cmd('03 02 00')                    # stop stream
        except Exception:
            pass
        self.run = False
        self.l.run = False


def load_calib():
    try:
        with open(CALIB_FILE) as f:
            c = json.load(f)
        return {'gain': float(c['gain']), 'offset': float(c['offset'])}
    except Exception:
        return dict(DEFAULT_CALIB)


def save_calib(c):
    with open(CALIB_FILE, 'w') as f:
        json.dump(c, f, indent=2)


def text(img, s, org, scale=0.5, color=(255, 255, 255), thick=1):
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), thick + 2, cv2.LINE_AA)
    cv2.putText(img, s, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def marker(img, x, y, color, size=6):
    cv2.drawMarker(img, (x, y), (0, 0, 0), cv2.MARKER_CROSS, size * 2 + 2, 3)
    cv2.drawMarker(img, (x, y), color, cv2.MARKER_CROSS, size * 2, 1)


class Viewer:
    def __init__(self, cam):
        self.cam = cam
        self.calib = load_calib()
        self.cal_points = []          # (diff_counts, true_temp) collected this session
        self.adaptive = True
        self.fixed = None             # (lo, hi) in C
        self.palette = 0
        self.points = []              # (x, y) in sensor pixels
        self.rects = []               # (x0, y0, x1, y1) in sensor pixels, inclusive
        self.drag = None              # (x0, y0, x1, y1) in display pixels while dragging
        self.help = False
        self.cal_mode = None          # None | 'pick' | ('type', x, y, diff)
        self.typed = ''
        self.msg, self.msg_t = '', 0
        self.temp = None
        self.diff = None

    # ---------- temperatures ----------
    def temps(self, fr):
        diff = cv2.medianBlur((self.cam.ref - fr)[IMG], 3)     # median removes dead pixels
        return diff, self.calib['offset'] + self.calib['gain'] * diff

    def flash(self, s):
        self.msg, self.msg_t = s, time.time()
        print(s)

    # ---------- mouse ----------
    def to_sensor(self, x, y):
        return min(max(x // SCALE, 0), W - 1), min(max(y // SCALE, 0), H - 1)

    def on_mouse(self, ev, x, y, flags, _):
        if x >= W * SCALE or y >= H * SCALE:
            if ev == cv2.EVENT_LBUTTONUP:
                self.drag = None
            return
        if self.cal_mode is not None:              # calibration: only a click to pick the spot
            self.drag = None
            if self.cal_mode == 'pick' and ev == cv2.EVENT_LBUTTONUP and self.diff is not None:
                sx, sy = self.to_sensor(x, y)
                d = float(np.median(self.diff[max(sy - 1, 0):sy + 2, max(sx - 1, 0):sx + 2]))
                self.cal_mode, self.typed = ('type', sx, sy, d), ''
            return
        if ev == cv2.EVENT_LBUTTONDOWN:
            self.drag = (x, y, x, y)
        elif ev == cv2.EVENT_MOUSEMOVE and self.drag and flags & cv2.EVENT_FLAG_LBUTTON:
            self.drag = (self.drag[0], self.drag[1], x, y)
        elif ev == cv2.EVENT_LBUTTONUP and self.drag:
            x0, y0 = self.drag[:2]
            self.drag = None
            if abs(x - x0) < 5 and abs(y - y0) < 5:
                self.points.append(self.to_sensor(x, y))
            else:
                a, b = self.to_sensor(min(x0, x), min(y0, y)), self.to_sensor(max(x0, x), max(y0, y))
                self.rects.append((a[0], a[1], b[0], b[1]))
        elif ev == cv2.EVENT_RBUTTONUP:
            sx, sy = self.to_sensor(x, y)
            for i, (px, py) in enumerate(self.points):
                if abs(px - sx) <= 4 and abs(py - sy) <= 4:
                    del self.points[i]
                    return
            for i in range(len(self.rects) - 1, -1, -1):
                x0, y0, x1, y1 = self.rects[i]
                if x0 <= sx <= x1 and y0 <= sy <= y1:
                    del self.rects[i]
                    return

    # ---------- keys ----------
    def on_key(self, k):
        """returns False to quit"""
        if isinstance(self.cal_mode, tuple):                 # typing a calibration temperature
            ch = k & 0xff if k < 256 else None
            if k == 27:
                self.cal_mode = None
            elif ch in (8, 127):
                self.typed = self.typed[:-1]
            elif ch in (13, 10):
                try:
                    self.add_cal_point(float(self.typed.replace(',', '.')))
                except ValueError:
                    self.flash('not a number')
                self.cal_mode = None
            elif ch is not None and chr(ch) in '0123456789.-,':
                self.typed += chr(ch)
            return True
        if k in (27, ord('q')):
            if self.cal_mode == 'pick':
                self.cal_mode = None
                return True
            return False
        if k == ord('a'):
            self.adaptive = not self.adaptive
            if not self.adaptive:
                self.fixed = self.last_range
            self.flash('adaptive scale' if self.adaptive else 'fixed scale %.1f .. %.1f C' % self.fixed)
        elif k in (2490368, 2621440, 2555904, 2424832) and not self.adaptive:   # up, down, right, left
            lo, hi = self.fixed
            if k == 2490368: hi += 1
            elif k == 2621440: hi = max(hi - 1, lo + 1)
            elif k == 2555904: lo = min(lo + 1, hi - 1)
            else: lo -= 1
            self.fixed = (lo, hi)
        elif k == ord('k'):
            self.cal_mode = 'pick'
            self.flash('calibration: click a spot with known temperature')
        elif k == ord('r'):
            self.calib, self.cal_points = dict(DEFAULT_CALIB), []
            save_calib(self.calib)
            self.flash('temperature calibration reset to defaults')
        elif k == ord('c'):
            self.flash('shutter calibration...')
            self.cam.shutter_calibrate()
            self.last_shutter = time.time()
        elif k == ord('x'):
            self.points, self.rects = [], []
        elif k == ord('p'):
            self.palette = (self.palette + 1) % len(PALETTES)
            self.flash('palette: ' + PALETTES[self.palette][0])
        elif k == ord('s'):
            fn = os.path.join(HERE, time.strftime('snapshot_%Y%m%d_%H%M%S.png'))
            cv2.imwrite(fn, self.canvas)
            self.flash('saved ' + os.path.basename(fn))
        elif k == ord('h'):
            self.help = not self.help
        return True

    def add_cal_point(self, t):
        _, sx, sy, d = self.cal_mode
        self.cal_points.append((d, t))
        g = self.calib['gain']
        pts = self.cal_points[-2:]
        if len(pts) == 2 and abs(pts[0][0] - pts[1][0]) > 30:        # two distinct temps: fit gain too
            (d1, t1), (d2, t2) = pts
            g = (t1 - t2) / (d1 - d2)
            if not 0.001 < g < 0.2:
                self.flash('calibration points inconsistent, gain kept')
                g = self.calib['gain']
        self.calib = {'gain': g, 'offset': t - g * d}
        save_calib(self.calib)
        self.flash('calibrated: %d point(s), gain %.4f C/count, offset %.2f C' % (min(len(self.cal_points), 2), g, self.calib['offset']))

    # ---------- drawing ----------
    def render(self, temp):
        if self.adaptive:
            lo, hi = float(temp.min()), float(temp.max())
            if hi - lo < 0.5:
                mid = (lo + hi) / 2
                lo, hi = mid - 0.25, mid + 0.25
        else:
            lo, hi = self.fixed
        self.last_range = (lo, hi)
        g = np.clip((temp - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
        g = cv2.resize(g, (W * SCALE, H * SCALE), interpolation=cv2.INTER_CUBIC)
        cmap = PALETTES[self.palette][1]
        img = cv2.applyColorMap(g, cmap) if cmap is not None else cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)

        canvas = np.zeros((H * SCALE + STATUS_H, W * SCALE + BAR_W, 3), np.uint8)
        canvas[:H * SCALE, :W * SCALE] = img
        # colour bar
        bh = H * SCALE - 40
        ramp = np.linspace(255, 0, bh).astype(np.uint8)[:, None].repeat(18, 1)
        ramp = cv2.applyColorMap(ramp, cmap) if cmap is not None else cv2.cvtColor(ramp, cv2.COLOR_GRAY2BGR)
        bx = W * SCALE + 8
        canvas[20:20 + bh, bx:bx + 18] = ramp
        for i in range(6):
            v = hi - (hi - lo) * i / 5
            y = 20 + int(bh * i / 5)
            cv2.line(canvas, (bx + 18, y), (bx + 23, y), (255, 255, 255), 1)
            text(canvas, f'{v:.1f}', (bx + 25, y + 5), 0.4)
        text(canvas, 'AUTO' if self.adaptive else 'FIXED', (bx - 2, 14), 0.45, (0, 255, 255) if self.adaptive else (0, 165, 255))

        # cursors
        for (sx, sy) in self.points:
            x, y = sx * SCALE + SCALE // 2, sy * SCALE + SCALE // 2
            marker(canvas, x, y, (255, 255, 255), 8)
            text(canvas, f'{temp[sy, sx]:.1f}C', (x + 8, y - 8), 0.5)
        # rectangles
        for (x0, y0, x1, y1) in self.rects:
            cv2.rectangle(canvas, (x0 * SCALE, y0 * SCALE), (x1 * SCALE + SCALE - 1, y1 * SCALE + SCALE - 1), (0, 0, 0), 3)
            cv2.rectangle(canvas, (x0 * SCALE, y0 * SCALE), (x1 * SCALE + SCALE - 1, y1 * SCALE + SCALE - 1), (255, 255, 255), 1)
            roi = temp[y0:y1 + 1, x0:x1 + 1]
            iy, ix = np.unravel_index(np.argmax(roi), roi.shape)
            jy, jx = np.unravel_index(np.argmin(roi), roi.shape)
            marker(canvas, (x0 + ix) * SCALE + 1, (y0 + iy) * SCALE + 1, (60, 60, 255))
            marker(canvas, (x0 + jx) * SCALE + 1, (y0 + jy) * SCALE + 1, (255, 160, 60))
            ty = y0 * SCALE - 8 if y0 * SCALE > 50 else y1 * SCALE + 18
            text(canvas, f'max {roi.max():.1f}', (x0 * SCALE, ty - 16), 0.45, (120, 120, 255))
            text(canvas, f'min {roi.min():.1f}  avg {roi.mean():.1f}', (x0 * SCALE, ty), 0.45, (255, 200, 120))
        if self.drag:
            x0, y0, x1, y1 = self.drag
            cv2.rectangle(canvas, (x0, y0), (x1, y1), (0, 255, 255), 1)

        # status bar
        sy0 = H * SCALE + 18
        mode = 'AUTO %.1f..%.1f C' % (lo, hi) if self.adaptive else 'FIXED %.1f..%.1f C (arrows)' % (lo, hi)
        cal = 'default cal' if not self.cal_points and self.calib == DEFAULT_CALIB else 'user cal'
        text(canvas, f'{mode} | {cal} | {self.fps:4.1f} fps | h = help', (6, sy0), 0.45, (200, 200, 200))
        if self.cal_mode == 'pick':
            text(canvas, 'CALIBRATION: click a spot whose temperature you know (Esc cancels)', (10, 24), 0.5, (0, 255, 255))
        elif isinstance(self.cal_mode, tuple):
            _, sx, sy, _ = self.cal_mode
            marker(canvas, sx * SCALE + 1, sy * SCALE + 1, (0, 255, 255), 10)
            text(canvas, f'real temperature at marker: {self.typed}_  C  (Enter / Esc)', (10, 24), 0.55, (0, 255, 255))
        elif self.msg and time.time() - self.msg_t < 3:
            text(canvas, self.msg, (10, 24), 0.5, (0, 255, 255))
        if self.help:
            lines = [l for l in __doc__.split('Mouse:')[1].split('NOTE')[0].splitlines() if l.strip()]
            box = canvas[40:40 + 18 * len(lines) + 10, 10:W * SCALE - 10]
            box[:] = (box * 0.35).astype(np.uint8)
            for i, l in enumerate(lines):
                text(canvas, l.rstrip(), (16, 58 + 18 * i), 0.45)
        return canvas

    def loop(self):
        cv2.namedWindow(WIN, cv2.WINDOW_AUTOSIZE)
        cv2.setMouseCallback(WIN, self.on_mouse)
        self.cam.shutter_calibrate()
        self.last_shutter = time.time()
        self.fps, nf, tf = 0.0, 0, time.time()
        self.last_range = (20.0, 30.0)
        n = 0
        while self.cam.run:
            fr, n = self.cam.wait_frame(n, 0.5)
            if fr is not None:
                self.diff, self.temp = self.temps(fr)
                self.canvas = self.render(self.temp)
                cv2.imshow(WIN, self.canvas)
                nf += 1
            k = cv2.waitKeyEx(1)
            if cv2.getWindowProperty(WIN, cv2.WND_PROP_VISIBLE) < 1:      # window closed with X
                break
            if k != -1 and not self.on_key(k):
                break
            if time.time() - self.last_shutter > AUTO_SHUTTER_S and not self.cal_mode:
                self.cam.shutter_calibrate()
                self.last_shutter = time.time()
            if time.time() - tf >= 1:
                self.fps, nf, tf = nf / (time.time() - tf), 0, time.time()


def main():
    try:
        cam = Camera()
    except SystemExit as e:
        print(e)
        print('-> unplug the camera, plug it back in, and run again')
        return
    try:
        Viewer(cam).loop()
    finally:
        cam.close()
        cv2.destroyAllWindows()
        print('bye')
        os._exit(0)                 # don't wait for threads blocked in libusb


if __name__ == '__main__':
    main()
