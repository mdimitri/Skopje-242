"""NAT lab 'internet' services: a STUN binding server (UDP 3478) and a tiny MQTT 3.1.1 broker (TCP 1883, QoS 0, # wildcard)."""
import socket, struct, threading, sys

def stun(ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.bind((ip, 3478))
    while True:
        d, a = s.recvfrom(2048)
        if len(d) < 20 or d[:2] != b"\x00\x01":
            continue
        ip = bytes(x ^ y for x, y in zip(socket.inet_aton(a[0]), b"\x21\x12\xa4\x42"))
        attr = struct.pack("!HHBBH", 0x20, 8, 0, 1, a[1] ^ 0x2112) + ip
        s.sendto(struct.pack("!HHI", 0x0101, len(attr), 0x2112A442) + d[8:20] + attr, a)

subs, lock = {}, threading.Lock()          # conn -> [topic filters]

def match(f, t):
    return f == t or (f.endswith("#") and t.startswith(f[:-1]))

def client(c):
    buf = b""
    try:
        while True:
            d = c.recv(4096)
            if not d:
                return
            buf += d
            while len(buf) >= 2:
                ln, mul, i = 0, 1, 1
                while i < len(buf):
                    ln += (buf[i] & 0x7F) * mul; mul <<= 7; i += 1
                    if not buf[i - 1] & 0x80: break
                else: break
                if len(buf) < i + ln: break
                h, body, buf = buf[0], buf[i:i + ln], buf[i + ln:]
                typ = h >> 4
                if typ == 1: c.sendall(b"\x20\x02\x00\x00")
                elif typ == 8:
                    pid, = struct.unpack_from("!H", body); tl, = struct.unpack_from("!H", body, 2)
                    with lock: subs.setdefault(c, []).append(body[4:4 + tl].decode())
                    c.sendall(b"\x90\x03" + struct.pack("!H", pid) + b"\x00")
                elif typ == 12: c.sendall(b"\xd0\x00")
                elif typ == 3:
                    tl, = struct.unpack_from("!H", body); t = body[2:2 + tl].decode()
                    pkt = bytes([h]) + buf_len(len(body)) + body
                    with lock: targets = [k for k, fs in subs.items() if any(match(f, t) for f in fs)]
                    for k in targets:
                        try: k.sendall(pkt)
                        except OSError: pass
    except OSError:
        pass
    finally:
        with lock: subs.pop(c, None)

def buf_len(n):
    out = b""
    while True:
        b, n = n & 0x7F, n >> 7
        out += bytes([b | (0x80 if n else 0)])
        if not n: return out

for ip in sys.argv[1:] or ["0.0.0.0"]:
    threading.Thread(target=stun, args=(ip,), daemon=True).start()
ls = socket.socket(); ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); ls.bind(("0.0.0.0", 1883)); ls.listen()
print("servers up", flush=True)
while True:
    c, _ = ls.accept()
    threading.Thread(target=client, args=(c,), daemon=True).start()
