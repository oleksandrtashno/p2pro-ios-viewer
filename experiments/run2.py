from iap2 import *
l = Link(); l.connect()
C = l.sess
def x(mid, params=(), wait=3000):
    l.send(C, msg(mid, params))
    r = l.recv(wait)
    if r and r[4][:2] == b'\x40\x40':
        m, ps = parse(r[4]); print(f'  <- 0x{m:04X}', [(p, d.hex()[:40]) for p, d in ps][:6]); return m, ps
    print('  reply:', r and r[4][:40].hex(' '))
x(0xAA00); x(0xAA02, [(0, os.urandom(32))])
l.send(C, msg(0xAA05)); x(0x1D00)
print('IdentificationAccepted'); l.send(C, msg(0x1D02))
d = l.d
usb.util.claim_interface(d, 1); d.set_interface_altsetting(1, 1)
data = bytearray(); chunks = []
def nat():
    while l.run:
        try:
            b = bytes(d.read(0x82, 1 << 20, 300)); data.extend(b); chunks.append(len(b))
        except usb.core.USBTimeoutError: pass
        except Exception as e: print('native err', e); break
threading.Thread(target=nat, daemon=True).start()
print('StartEAPSession'); x(0xEA00, [(0, b'\x01'), (1, b'\x00\x01')], 2000)
time.sleep(6)
print('native bytes in 6s:', len(data), 'chunks:', len(chunks), chunks[:30])
print(bytes(data[:256]).hex(' '))
open('native.bin', 'wb').write(data)
while True:
    r = l.recv(500)
    if not r: break
    print('ctl late:', r[4][:40].hex(' '))
l.run = False
