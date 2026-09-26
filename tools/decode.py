"""Rebuild USB transactions from raw UPV capture."""
import struct, sys, collections
PID = {0xE1:'OUT',0x69:'IN',0x2D:'SETUP',0xA5:'SOF',0xC3:'DATA0',0x4B:'DATA1',0x87:'DATA2',0x0F:'MDATA',
       0xD2:'ACK',0x5A:'NAK',0x1E:'STALL',0x96:'NYET',0xB4:'PING'}
def records(fn):
    b = open(fn, 'rb').read(); o = 0
    while o + 14 <= len(b):
        ts, nano, st, ln = struct.unpack_from('<IIiH', b, o); o += 14
        yield ts + nano / 1e9, st, b[o:o+ln]; o += ln

def transactions(fn):
    """yield (t, kind, addr, ep, data, handshake)"""
    tok = None; data = None
    for t, st, d in records(fn):
        if (st >> 4) & 0xf:
            yield t, 'BUS%d' % ((st >> 4) & 0xf), 0, 0, b'', None; continue
        if not d: continue
        p = PID.get(d[0], '?%02x' % d[0])
        if p in ('OUT', 'IN', 'SETUP', 'PING') and len(d) >= 3:
            v = d[1] | (d[2] << 8); tok = (t, p, v & 0x7f, (v >> 7) & 0xf); data = None
        elif p.startswith('DATA') or p == 'MDATA':
            data = d[1:-2]  # strip PID + CRC16
            if tok and tok[1] == 'IN': pass
        elif p in ('ACK', 'NAK', 'STALL', 'NYET'):
            if tok:
                yield tok[0], tok[1], tok[2], tok[3], data or b'', p
            tok = None; data = None

if __name__ == '__main__':
    fn = sys.argv[1] if len(sys.argv) > 1 else 'capture.bin'
    stats = collections.Counter()
    for t, k, a, e, d, hs in transactions(fn):
        stats[(k, a, e, hs)] += 1
    for k, v in sorted(stats.items(), key=lambda x: -x[1])[:30]: print(v, k)
