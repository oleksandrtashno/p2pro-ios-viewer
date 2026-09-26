from iap2 import *
l = Link(); l.connect()
C = l.sess
def x(mid, params=(), wait=3000):
    l.send(C, msg(mid, params)); r = l.recv(wait)
    if r and r[4][:2] == b'\x40\x40': m, ps = parse(r[4]); print(f'  <- 0x{m:04X}'); return m, ps
x(0xAA00); x(0xAA02, [(0, os.urandom(32))])
l.send(C, msg(0xAA05)); x(0x1D00)
print('== IdentificationAccepted'); l.send(C, msg(0x1D02))
r = l.recv(4000); l.recv(1000)
print('== StartEAPSession'); l.send(C, msg(0xEA00, [(0, b'\x01'), (1, b'\x00\x01')]))
l.recv(1000)
d = l.d
usb.util.claim_interface(d, 1); d.set_interface_altsetting(1, 1); print('== alt 1 set')
data = bytearray(); log = []
def nat():
    while l.run:
        try:
            b = bytes(d.read(0x82, 1 << 20, 300)); data.extend(b); log.append((round(time.time()-T0, 2), len(b), b[:48].hex(' ')))
        except usb.core.USBTimeoutError: pass
        except Exception as e: print('native err', e); break
threading.Thread(target=nat, daemon=True).start()
def step(name, secs):
    n = len(log); end = time.time() + secs
    while time.time() < end: l.recv(200)
    print(f'[{name}] native chunks: {len(log)-n}, total bytes {len(data)}')
    for e in log[n:n+6]: print('   ', e)
step('passive', 1)
def probe(p, wait=0.3):
    n = len(log)
    d.write(0x07, p, 1500)
    end = time.time() + wait
    while time.time() < end: l.recv(50)
    return [e[2] for e in log[n:]], sum(e[1] for e in log[n:])
import json
results = []
def P(p, wait=0.35):
    n = len(log)
    try: d.write(0x07, p, 1500)
    except Exception as e: print('write fail', p.hex(' '), e); return
    end = time.time() + wait
    while time.time() < end: l.recv(50)
    got = bytes(data[sum(e[1] for e in log[:n]):]) if len(log) > n else b''
    results.append((p.hex(' '), got.hex(' ')))
    short = got[:24].hex(' ') + (f' ...(+{len(got)-24})' if len(got) > 24 else '')
    if 0: print(f'{p.hex(" "):20s} -> {short}')
for c in list(range(0x10, 0x100)) + [4]:
    n0 = len(data); P(bytes([6, c, 0, 0, 0, 0]), 0.15)
    got = bytes(data[n0:])
    if not got.startswith(bytes.fromhex('068682')): print(f'  cmd {c:02x}: {got[:40].hex(" ")} (+{max(0,len(got)-40)})')
step('final wait', 4)
json.dump(results, open('results8.json', 'w'), indent=0)
open('native.bin', 'wb').write(data)
l.run = False
