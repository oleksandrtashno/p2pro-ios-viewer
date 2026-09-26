import usb.core, usb.util, libusb_package, os, struct, time, threading, queue
be = libusb_package.get_libusb1_backend()

T0 = time.time()
TRACE = False
def ck(b): return (-sum(b)) & 0xff

class Link:
    def __init__(s, verbose=True):
        s.v = verbose
        s.d = usb.core.find(idVendor=0x0bda, idProduct=0x5840, backend=be)
        s.d.set_configuration()
        usb.util.claim_interface(s.d, 0)
        for ep in (0x05, 0x86):
            try: s.d.clear_halt(ep)
            except Exception as e: print("clear_halt", hex(ep), e)
        s.buf = b''; s.seq = 0x2B; s.rseq = 0; s.sess = 0
        s.q = queue.Queue(); s.run = True
        threading.Thread(target=s._reader, daemon=True).start()
    def _reader(s):
        while s.run:
            try: s.q.put(bytes(s.d.read(0x86, 65536, 200)))
            except usb.core.USBTimeoutError: pass
            except Exception as e: print('reader err', e); time.sleep(0.2)
    def raw_read(s, t):
        try: s.buf += s.q.get(timeout=t/1000)
        except queue.Empty: pass
    def pkt(s, t=1000):
        """return (ctrl,seq,ack,sess,payload) or None"""
        end = time.time() + t/1000
        while True:
            i = s.buf.find(b'\xff\x5a')
            j = s.buf.find(b'\xff\x55')
            if j == 0 and len(s.buf) >= 6:
                s.buf = s.buf[6:]; continue
            if i >= 0 and len(s.buf) >= i+9:
                s.buf = s.buf[i:]
                L = struct.unpack('>H', s.buf[2:4])[0]
                if len(s.buf) >= L:
                    p = s.buf[:L]; s.buf = s.buf[L:]
                    pl = p[9:-1] if L > 9 else b''
                    if TRACE: print(f'   IN  {time.time()-T0:7.3f} c={p[4]:02x} s={p[5]} a={p[6]} sess={p[7]} {pl[:14].hex(" ")}')
                    return p[4], p[5], p[6], p[7], pl
            if time.time() > end: return None
            s.raw_read(200)
    def send_raw(s, ctrl, seq, ack, sess, payload=b''):
        L = 9 + (len(payload)+1 if payload else 0)
        h = bytes([0xff, 0x5a, L >> 8, L & 0xff, ctrl, seq, ack, sess])
        p = h + bytes([ck(h)])
        if payload: p += payload + bytes([ck(payload)])
        t = time.time()
        try: s.d.write(0x05, p, 3000)
        finally:
            if TRACE: print(f'   OUT {time.time()-T0:7.3f} c={ctrl:02x} s={seq} a={ack} sess={sess} {payload[:14].hex(" ")} ({(time.time()-t)*1000:.0f}ms)')
    def connect(s):
        s.raw_read(1500); print('initial:', s.buf.hex(' ')); s.buf = b''
        s.d.write(0x05, bytes.fromhex('FF550200EE10'), 2000)
        tries = 0
        while True:
            r = s.pkt(3000)
            if r is None:
                tries += 1
                raise SystemExit('no SYN -> camera stuck, replug it')
            if r[0] & 0x80:
                ctrl, seq, ack, sess, pl = r; break
        print('SYN params', pl.hex(' '))
        s.rseq = seq
        s.sess = pl[10]  # first session id (control)
        s.syn_params = pl
        s.send_raw(0xC0, s.seq, s.rseq, 0, pl)   # SYN+ACK echoing params
        r = s.pkt(2000); print('after SYNACK:', r and (hex(r[0]), r[1], r[2], r[4].hex(' ')))
        if r and r[4]: s.handle_incoming(r)
    def handle_incoming(s, r):
        ctrl, seq, ack, sess, pl = r
        if pl:
            s.rseq = seq
            try: s.send_raw(0x40, s.seq, s.rseq, 0)  # ack
            except usb.core.USBTimeoutError: print('  (ack write timeout)')
        return r
    def send(s, sess, payload):
        s.seq = (s.seq + 1) & 0xff
        s.send_raw(0x40, s.seq, s.rseq, sess, payload)
        s.pending = []
        end = time.time() + 3
        while time.time() < end:   # wait for ACK of our seq, queue data packets
            r = s.pkt(500)
            if r is None: continue
            if r[4]: s.handle_incoming(r); s.pending.append(r)
            if (r[0] & 0x40) and r[2] == s.seq: return
        print('  (no ack for seq', s.seq, ')')
    def recv(s, t=2000):
        """next packet with payload (acks it)"""
        if getattr(s, 'pending', None): return s.pending.pop(0)
        end = time.time() + t/1000
        while time.time() < end:
            r = s.pkt(max(1, int((end-time.time())*1000)))
            if r is None: return None
            if r[4]:
                s.handle_incoming(r); return r
        return None

def msg(mid, params=()):
    body = b''.join(struct.pack('>HH', 4+len(d), pid) + d for pid, d in params)
    return struct.pack('>HHH', 0x4040, 6+len(body), mid) + body

def parse(pl):
    som, L, mid = struct.unpack('>HHH', pl[:6])
    ps, o = [], 6
    while o < L:
        pl_, pid = struct.unpack('>HH', pl[o:o+4]); ps.append((pid, pl[o+4:o+pl_])); o += pl_
    return mid, ps
