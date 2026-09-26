"""Capture USB traffic with USB Packet Viewer to a raw file.
Record format: <IIiH> ts, nano, status, len  + data
Stops after DURATION seconds or when file 'stop.flag' appears."""
import ctypes, os, sys, struct, time, threading
SDK = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'upv_sdk', 'x64')
os.add_dll_directory(SDK)
lib = ctypes.CDLL(os.path.join(SDK, 'usbpv_lib.dll'))
lib.upv_list_devices.restype = ctypes.c_char_p
CB = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_ubyte), ctypes.c_int32, ctypes.c_int32)
lib.upv_open_device.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, CB]
lib.upv_open_device.restype = ctypes.c_void_p
lib.upv_close_device.argtypes = [ctypes.c_void_p]
lib.upv_get_last_error.restype = ctypes.c_int
lib.upv_get_error_string.argtypes = [ctypes.c_int]; lib.upv_get_error_string.restype = ctypes.c_char_p

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 120
OUT = sys.argv[2] if len(sys.argv) > 2 else 'capture.bin'
FLAGS = 0xFF & ~(0x10 | 0x04 | 0x20)   # drop SOF, NAK, PING

chunks = []; count = [0, 0]; lock = threading.Lock()
@CB
def cb(ctx, ts, nano, data, ln, status):
    rec = struct.pack('<IIiH', ts, nano, status, ln) + ctypes.string_at(data, ln)
    with lock:
        chunks.append(rec); count[0] += 1; count[1] += ln
    return 0

devs = lib.upv_list_devices().decode()
if not devs: sys.exit('no analyzer found')
sn = devs.split(',')[0]; print('analyzer', sn)
opt = sn.encode() + b'\x00' + bytes([3, FLAGS, 1] + [0xff] * 8)
h = lib.upv_open_device(opt, len(opt), None, cb)
if not h: sys.exit('open failed: ' + lib.upv_get_error_string(lib.upv_get_last_error()).decode())
print(f'CAPTURING for {DURATION:.0f}s -> {OUT}', flush=True)
t0 = time.time()
with open(OUT, 'wb') as f:
    while time.time() - t0 < DURATION and not os.path.exists('stop.flag'):
        time.sleep(1)
        with lock: buf, chunks[:] = b''.join(chunks), []
        f.write(buf); f.flush()
        print(f'  {time.time()-t0:5.0f}s packets={count[0]} bytes={count[1]}', flush=True)
    lib.upv_close_device(h)
    with lock: f.write(b''.join(chunks))
print('done', count)
