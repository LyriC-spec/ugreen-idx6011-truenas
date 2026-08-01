#!/usr/bin/env python3
"""
fan-control.py - Getrennte Luefterregelung fuer UGREEN iDX6011 (non-Pro)

Luefter 1 (0x9c/0x9d): 2x Noctua NF-A9 am Y-Kabel, Gehaeuse
                       -> hoechster Bedarf aus CPU, Datentraegern und Netzwerk
Luefter 2 (0x9e/0x9f): dedizierter Luefter fuer die Tesla T4
                       -> folgt der GPU-Temperatur

Zugriff auf den ITE IT5571 EC per ACPI-Protokoll ueber /dev/port, kein Kernel-Modul.
Hinweis: duty 0/0 in den Registern bedeutet "Firmware regelt selbst" - sobald wir
schreiben, uebernehmen wir die Kontrolle.

Glaettung: gleitender Mittelwert ueber SMOOTH_N Messungen, Hysterese gegen
Pendeln, bewusst asymmetrisch - nach oben sofort, nach unten gebremst.
"""
import os, sys, time, signal, subprocess, logging
from collections import deque
from logging.handlers import RotatingFileHandler

INTERVAL   = 5
SMOOTH_N   = 6
HYST       = 8
DOWN_STEP  = 10
SPEED_MIN  = 40
SPEED_MAX  = 198
LOGFILE    = "/mnt/nvme-tank/scripts/fancontrol/fan-control.log"

CURVE_CPU  = [(45, 45), (55, 70), (65, 110), (75, 155), (82, 198)]
CURVE_DISK = [(35, 45), (42, 70), (48, 110), (54, 155), (58, 198)]
CURVE_GPU  = [(45, 50), (55, 85), (65, 130), (72, 165), (78, 198)]
CURVE_NET  = [(58, 45), (68, 75), (78, 115), (88, 160), (95, 198)]

EMERG_CPU, EMERG_DISK, EMERG_GPU, EMERG_NET = 88, 62, 82, 100

DATA, CMD         = 0x62, 0x66
EC_READ, EC_WRITE = 0x80, 0x81
FAN1_TACH_HI, FAN1_TACH_LO = 0x96, 0x97
FAN2_TACH_HI, FAN2_TACH_LO = 0x98, 0x99
FAN1_DUTY, FAN2_DUTY       = 0x9d, 0x9f
# Freigabe-Bytes: MUESSEN auf 1 stehen, sonst nimmt der EC den Geschwindigkeits-
# wert nur teilweise an. Nach einem Neustart stehen sie auf 0 (Firmware-Regelung)
# und muessen von uns aktiv gesetzt werden - sonst dreht der Luefter trotz
# Duty 198 nur etwa drei Viertel seiner Drehzahl.
FAN1_EN, FAN2_EN           = 0x9c, 0x9e

log = logging.getLogger("fan")
log.setLevel(logging.INFO)
_h = RotatingFileHandler(LOGFILE, maxBytes=512*1024, backupCount=2)
_h.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))
log.addHandler(_h)

fd = os.open("/dev/port", os.O_RDWR)
def _outb(p, v): os.pwrite(fd, bytes([v]), p)
def _inb(p):     return os.pread(fd, 1, p)[0]

def _wait(mask, want, timeout=1.0):
    t = time.time()
    while time.time() - t < timeout:
        if bool(_inb(CMD) & mask) == want: return True
        time.sleep(0.001)
    return False

def ec_read(addr):
    if not _wait(0x02, False): return None
    _outb(CMD, EC_READ)
    if not _wait(0x02, False): return None
    _outb(DATA, addr)
    if not _wait(0x01, True):  return None
    return _inb(DATA)

def ec_write(addr, val):
    if not _wait(0x02, False): return False
    _outb(CMD, EC_WRITE)
    if not _wait(0x02, False): return False
    _outb(DATA, addr)
    if not _wait(0x02, False): return False
    _outb(DATA, val)
    return _wait(0x02, False)

def fan_rpm(hi, lo):
    h, l = ec_read(hi), ec_read(lo)
    return (h << 8) | l if h is not None and l is not None else -1

def _hwmon_max(target):
    best, base = -1, "/sys/class/hwmon"
    try: devs = os.listdir(base)
    except OSError: return best
    for d in devs:
        try:
            if open(base + "/" + d + "/name").read().strip() != target: continue
            for f in os.listdir(base + "/" + d):
                if f.startswith("temp") and f.endswith("_input"):
                    v = int(open(base + "/" + d + "/" + f).read().strip()) // 1000
                    if 0 < v < 150: best = max(best, v)
        except (OSError, ValueError):
            continue
    return best

def cpu_temp():  return _hwmon_max("coretemp")

def _nvme_composite():
    """Nur den Composite-Wert der NVMe verwenden - das ist die vom Hersteller
    definierte Laufwerkstemperatur mit Warn-/Kritischschwelle, und der Wert, den
    SMART und die TrueNAS-Berichte anzeigen.
    Die zusaetzlichen Sensor-N-Werte sind interne Messpunkte (z.B. Controller);
    die Bootplatte meldet dort dauerhaft ~51 C ohne definierten Grenzwert und
    wuerde die Regelung sonst grundlos hochtreiben."""
    best, base = -1, "/sys/class/hwmon"
    try: devs = os.listdir(base)
    except OSError: return best
    for d in devs:
        try:
            if open(base + "/" + d + "/name").read().strip() != "nvme": continue
            for f in os.listdir(base + "/" + d):
                if not (f.startswith("temp") and f.endswith("_label")): continue
                if open(base + "/" + d + "/" + f).read().strip() != "Composite": continue
                vf = base + "/" + d + "/" + f[:-6] + "_input"
                v = int(open(vf).read().strip()) // 1000
                if 0 < v < 150: best = max(best, v)
        except (OSError, ValueError):
            continue
    return best

def disk_temp(): return max(_hwmon_max("drivetemp"), _nvme_composite())

def net_temp():
    try: ifaces = os.listdir("/sys/class/net")
    except OSError: return -1
    best = -1
    for n in ifaces:
        if n != "lo":
            best = max(best, _hwmon_max(n))
    return best

def gpu_temp():
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10)
        vals = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        return max(vals) if vals else -1
    except Exception:
        return -1

def curve(points, temp):
    if temp is None or temp < 0: return None
    if temp <= points[0][0]:  return points[0][1]
    if temp >= points[-1][0]: return points[-1][1]
    for (t0, d0), (t1, d1) in zip(points, points[1:]):
        if t0 <= temp <= t1:
            span = t1 - t0
            return int(d0 + (d1 - d0) * (temp - t0) / span) if span else d1
    return points[-1][1]

def clamp(v): return max(SPEED_MIN, min(SPEED_MAX, int(v)))

class Smoother:
    def __init__(self, n): self.buf = deque(maxlen=n)
    def add(self, v):
        if v is not None and v >= 0: self.buf.append(v)
        return self.avg()
    def avg(self):
        return sum(self.buf) / len(self.buf) if self.buf else None

def next_duty(current, target):
    if current is None:         return target
    if target > current:        return target
    if current - target < HYST: return current
    return max(target, current - DOWN_STEP)

def safe_exit(signum=None, frame=None):
    log.info("Beende - setze beide Luefter auf Vollast")
    for _ in range(3):
        ec_write(FAN1_EN, 1)
        ec_write(FAN1_DUTY, SPEED_MAX)
        ec_write(FAN2_EN, 1)
        ec_write(FAN2_DUTY, SPEED_MAX)
        time.sleep(0.2)
    try: os.close(fd)
    except Exception: pass
    sys.exit(0)

signal.signal(signal.SIGTERM, safe_exit)
signal.signal(signal.SIGINT,  safe_exit)

def main():
    log.info("gestartet (Intervall %ss, Mittelwert ueber %s Messungen, Hysterese %s)",
             INTERVAL, SMOOTH_N, HYST)
    sm = {k: Smoother(SMOOTH_N) for k in ("cpu", "disk", "net", "gpu")}
    duty1 = duty2 = None

    while True:
        raw = {"cpu": cpu_temp(), "disk": disk_temp(),
               "net": net_temp(), "gpu": gpu_temp()}
        avg = {k: sm[k].add(v) for k, v in raw.items()}

        def demand(points, key):
            a = curve(points, avg[key])
            r = curve(points, raw[key])
            vals = [x for x in (a, r) if x is not None]
            return max(vals) if vals else None

        d1 = [x for x in (demand(CURVE_CPU, "cpu"),
                          demand(CURVE_DISK, "disk"),
                          demand(CURVE_NET, "net")) if x is not None]
        t1 = clamp(max(d1)) if d1 else SPEED_MAX

        d2 = demand(CURVE_GPU, "gpu")
        t2 = clamp(d2) if d2 is not None else SPEED_MAX

        emerg = []
        if raw["cpu"]  >= EMERG_CPU:  emerg.append("CPU " + str(raw["cpu"]) + "C")
        if raw["disk"] >= EMERG_DISK: emerg.append("Disk " + str(raw["disk"]) + "C")
        if raw["gpu"]  >= EMERG_GPU:  emerg.append("GPU " + str(raw["gpu"]) + "C")
        if raw["net"]  >= EMERG_NET:  emerg.append("Net " + str(raw["net"]) + "C")

        if emerg:
            duty1 = duty2 = SPEED_MAX
            log.warning("NOTFALL (%s) -> beide Luefter Vollast", ", ".join(emerg))
        else:
            duty1 = next_duty(duty1, t1)
            duty2 = next_duty(duty2, t2)

        ec_write(FAN1_EN, 1)
        ec_write(FAN1_DUTY, duty1)
        ec_write(FAN2_EN, 1)
        ec_write(FAN2_DUTY, duty2)

        avgs = "/".join(("%.1f" % avg[k]) if avg[k] is not None else "-"
                        for k in ("cpu", "disk", "net", "gpu"))
        log.info("CPU %s Disk %s Net %s GPU %s (Mittel %s) | duty %s/%s | RPM %s/%s",
                 raw["cpu"], raw["disk"], raw["net"], raw["gpu"], avgs,
                 duty1, duty2,
                 fan_rpm(FAN1_TACH_HI, FAN1_TACH_LO),
                 fan_rpm(FAN2_TACH_HI, FAN2_TACH_LO))
        time.sleep(INTERVAL)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.exception("Unerwarteter Fehler: %s", e)
        safe_exit()
