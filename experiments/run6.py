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
step('passive', 3)
H = bytes.fromhex
probes = []
for c in range(0, 16): probes.append((f'len6 cmd{c:02x}', bytes([6, c, 0, 0, 0, 0])))
for c in (0x80, 0x81, 0x82, 0x86): probes.append((f'len6 cmd{c:02x}', bytes([6, c, 0, 0, 0, 0])))
probes += [
    ('echo reply', H('068682060000')),
    ('1 byte', H('01')), ('2 bytes', H('0200')), ('4 bytes', H('04000000')),
    ('len8 preview_start', H('080fc10000000000')),
    ('len10 +preview', H('0a000fc10000000000 00'.replace(' ',''))),
    ('len le16 prefix', H('0a000fc1000000000000')),
    ('len6 cmd06 01', H('060601000000')),
    ('len7', H('07010000000000')),
    ('len5', H('0501000000')),
    ('len3', H('030100')),
    ('big 512', bytes(512)),
]
resp = []
for name, p in probes:
    n = len(log)
    try: d.write(0x07, p, 1500)
    except Exception as e: print('write fail', name, e); continue
    end = time.time() + 0.5
    while time.time() < end: l.recv(100)
    got = [e[2] for e in log[n:]]
    print(f'{name:22s} {p[:12].hex(" "):38s} -> {got}')
step('after probes', 3)
open('native.bin', 'wb').write(data)
l.run = False
