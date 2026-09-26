from iap2 import *
l = Link(); l.connect()
C = l.sess
def x(mid, params=(), wait=3000):
    l.send(C, msg(mid, params)); r = l.recv(wait)
    if r and r[4][:2] == b'\x40\x40': m, ps = parse(r[4]); print(f'  <- 0x{m:04X}'); return m, ps
x(0xAA00); x(0xAA02, [(0, os.urandom(32))])
l.send(C, msg(0xAA05)); x(0x1D00)
print('== IdentificationAccepted'); l.send(C, msg(0x1D02))
print('== observe 4s'); r = l.recv(4000); print('  got', r and r[4][:30].hex(' ')); l.recv(1000)
print('== test pure ack'); l.send_raw(0x40, l.seq, l.rseq, 0)
print('== StartEAPSession'); x(0xEA00, [(0, b'\x01'), (1, b'\x00\x01')], 3000)
l.recv(2000); l.run = False
