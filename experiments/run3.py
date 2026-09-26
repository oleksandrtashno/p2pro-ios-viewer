from iap2 import *
l = Link(); l.connect()
C = l.sess
def x(mid, params=(), wait=3000):
    l.send(C, msg(mid, params))
    r = l.recv(wait)
    if r and r[4][:2] == b'\x40\x40':
        m, ps = parse(r[4]); print(f'  <- 0x{m:04X}', [(p, d[:24]) for p, d in ps][:4]); return m, ps
    print('  reply:', r and r[4][:40].hex(' '))
x(0xAA00); x(0xAA02, [(0, os.urandom(32))])
l.send(C, msg(0xAA05)); x(0x1D00)
l.send(C, msg(0x1D02))
print('StartEAPSession'); x(0xEA00, [(0, b'\x01'), (1, b'\x00\x01')], 3000)
d = l.d
usb.util.claim_interface(d, 1); d.set_interface_altsetting(1, 1); print('alt 1 set')
data = bytearray(); log = []
def nat():
    while l.run:
        try:
            b = bytes(d.read(0x82, 1 << 20, 300)); data.extend(b); log.append((round(time.time()-T0, 2), len(b), b[:48].hex(' ')))
        except usb.core.USBTimeoutError: pass
        except Exception as e: print('native err', e); break
T0 = time.time()
threading.Thread(target=nat, daemon=True).start()
def ctl_drain():
    while True:
        r = l.recv(100)
        if not r: return
        print('   ctl:', r[4][:40].hex(' '))
def step(name, secs):
    n = len(log); time.sleep(secs); ctl_drain()
    print(f'[{name}] native chunks: {len(log)-n}, total bytes {len(data)}')
    for e in log[n:n+5]: print('   ', e)
step('passive', 4)
probes = [
    ('preview_start raw8', bytes.fromhex('0fc1000000000000')),
    ('setup+preview_start', bytes.fromhex('4145780000 9d0800'.replace(' ','')) + bytes.fromhex('0fc1000000000000')),
    ('get_device_info', bytes.fromhex('0584000000000030')),
]
for name, p in probes:
    try: d.write(0x07, p, 1500); print('wrote', name, p.hex(' '))
    except Exception as e: print('write fail', name, e)
    step(name, 2)
open('native.bin', 'wb').write(data)
l.run = False
