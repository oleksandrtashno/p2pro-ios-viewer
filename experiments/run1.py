from iap2 import *
l = Link(); l.connect()
C = l.sess
def x(mid, params=(), expect=True):
    l.send(C, msg(mid, params))
    while expect:
        r = l.recv(3000)
        if r is None: print('  no reply'); return None
        if r[3] == C and r[4][:2] == b'\x40\x40':
            m, ps = parse(r[4]); print(f'  <- 0x{m:04X}', [(p, len(d)) for p, d in ps]); return m, ps
        print('  other', r[3], r[4][:32].hex(' '))
print('RequestAuthCert'); x(0xAA00)
print('RequestChallenge'); x(0xAA02, [(0, os.urandom(32))])
print('AuthSucceeded'); l.send(C, msg(0xAA05)); time.sleep(0.3)
print('StartIdentification'); r = x(0x1D00)
import pickle; pickle.dump(r, open('ident.pkl', 'wb'))
