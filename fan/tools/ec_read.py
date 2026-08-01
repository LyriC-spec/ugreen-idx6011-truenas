#!/usr/bin/env python3
"""Liest Luefter-Register des ITE IT5571 EC (iDX6011 non-Pro). NUR LESEND."""
import os, time
DATA, CMD, EC_READ = 0x62, 0x66, 0x80
fd = os.open("/dev/port", os.O_RDWR)
def outb(p,v): os.pwrite(fd, bytes([v]), p)
def inb(p):    return os.pread(fd, 1, p)[0]
def w_ibf():
    t=time.time()
    while time.time()-t<1.0:
        if not (inb(CMD)&0x02): return True
        time.sleep(0.001)
    return False
def w_obf():
    t=time.time()
    while time.time()-t<1.0:
        if inb(CMD)&0x01: return True
        time.sleep(0.001)
    return False
def ec_read(a):
    if not w_ibf(): return None
    outb(CMD, EC_READ)
    if not w_ibf(): return None
    outb(DATA, a)
    if not w_obf(): return None
    return inb(DATA)
try:
    r = {a: ec_read(a) for a in (0x96,0x97,0x98,0x99,0x9c,0x9d,0x9e,0x9f)}
    if None in r.values():
        print("TIMEOUT beim EC-Zugriff")
    else:
        print(f"Luefter 1 (Noctua): {(r[0x96]<<8)|r[0x97]:>5} RPM   duty {r[0x9c]}/{r[0x9d]}")
        print(f"Luefter 2 (T4):     {(r[0x98]<<8)|r[0x99]:>5} RPM   duty {r[0x9e]}/{r[0x9f]}")
finally:
    os.close(fd)
