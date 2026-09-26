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
REJ = '06 86 84 06 00 00'
hit = None
for c in range(5):
    for b in range(5):
        for a in range(5):
            p = bytes([6, 1, a, b, c, 0])
            got, nb = probe(p, 0.25)
            if got != [REJ]:
                print('HIT', p.hex(' '), '->', got[:3], 'bytes', nb); hit = p; break
        if hit: break
    if hit: break
if hit:
    step('streaming?', 4)
    print('total native bytes', len(data), 'chunk sizes', [e[1] for e in log[-20:]])
else:
    print('no hit on 6-byte cmd01; trying lengths')
    for L in range(2, 40):
        got, nb = probe(bytes([L, 1]) + bytes([1]) * (L - 2), 0.25)
        if got != [REJ]: print('len', L, '->', got[:2], nb)
open('native.bin', 'wb').write(data)
l.run = False
