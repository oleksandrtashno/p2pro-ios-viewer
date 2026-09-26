from decode import *
T0 = None; inbuf = bytearray(); lastin = None; n_in = 0
out = []
for t, k, a, e, d, hs in transactions('capture.bin'):
    if T0 is None: T0 = t
    tt = t - T0
    if k == 'SETUP': out.append(f'{tt:9.4f} SETUP a{a} {d.hex(" ")}')
    elif e == 5 and k == 'OUT': out.append(f'{tt:9.4f} iAP>  {d[:40].hex(" ")}')
    elif e == 6 and k == 'IN':  out.append(f'{tt:9.4f} iAP<  {d[:40].hex(" ")}')
    elif e == 7 and k == 'OUT':
        if n_in: out.append(f'{"":9s}   (EP2 IN: {n_in} pkts, {len(inbuf)} bytes, first: {bytes(inbuf[:24]).hex(" ")})'); n_in = 0; inbuf.clear()
        out.append(f'{tt:9.4f} CMD>  [{len(d)}] {d[:48].hex(" ")}')
    elif e == 2 and k == 'IN':
        n_in += 1; inbuf += d
open('dump.txt', 'w').write('\n'.join(out))
print(len(out), 'lines')
