# Hardware reference — UGREEN iDX6011 (non-Pro)

All values verified on real hardware on 2026-08-01, TrueNAS SCALE
26.0.0-BETA.2. DMI reports product `iDX6011`, vendor `UGREEN`.

## LEDs

Driven by an I²C MCU on the **SMBus** (`i2c-i801`), bus `/dev/i2c-0`,
address `0x3a`. Prerequisite: `modprobe i2c-i801 && modprobe i2c-dev`.

### LED indices

The **non-Pro has only one network LED** — the Pro model has two. This shifts
the entire drive chain **by one** compared to the Pro. Index `0x08` does not
exist on the non-Pro.

| Index | LED |
|---|---|
| `0x00` | power |
| `0x01` | network |
| `0x02` | disk1 |
| `0x03` | disk2 |
| `0x04` | disk3 |
| `0x05` | disk4 |
| `0x06` | disk5 |
| `0x07` | disk6 |

### Protocol

SMBus block write (`i2cset ... s`, **not** `i`). Eleven bytes:

```
0xA0 0x01 0x00 0x00  <cmd> <p1> <p2> <p3> <p4>  <ck_hi> <ck_lo>
```

Checksum: `sum = 0xA0 + 0x01 + cmd + p1 + p2 + p3 + p4`,
then `ck_hi = (sum >> 8) & 0xFF`, `ck_lo = sum & 0xFF`.

| cmd | Function | Parameters |
|---|---|---|
| `0x01` | Brightness | 0–255 |
| `0x02` | Colour | R, G, B |
| `0x03` | On/off | `0xFF` = on |
| `0x04` | Blink | cycle_hi, cycle_lo, on_hi, on_lo |
| `0x05` | Breathe | same as blink |

Example — set the power LED to maximum brightness:

```bash
i2cset -y 0 0x3a 0x00 0xa0 0x01 0x00 0x00 0x01 0xff 0x00 0x00 0x00 0x01 0xa1 s
```

### Stopping a blink

The MCU **keeps blinking on its own** until you actively stop it — simply
ceasing to send blink commands is not enough. The mode reset (`0x04` with all
zeros) switches the LED off in the process, so it has to be followed by `0x03`
with `0xFF`.

Working sequence for a clean steady light, ~50 ms between steps:

```
0x04 (0,0,0,0)  ->  0x01 brightness  ->  0x02 colour  ->  0x03 0xFF  ->  0x01 brightness
```

This is the same takeover sequence used to wrest control from the MCU after
boot (otherwise it runs its own animation).

## Drive bays

Bay-to-SCSI-address mapping, determined by moving a single drive between bays.
The numbering is **not contiguous** — it wraps back to `0:` and `1:` at the end.
Identical to the DXP6800 Pro.

| Bay | ata | HCTL | LED index |
|---|---|---|---|
| 1 | ata3 | `2:0:0:0` | `0x02` |
| 2 | ata4 | `3:0:0:0` | `0x03` |
| 3 | ata5 | `4:0:0:0` | `0x04` |
| 4 | ata6 | `5:0:0:0` | `0x05` |
| 5 | ata1 | `0:0:0:0` | `0x06` |
| 6 | ata2 | `1:0:0:0` | `0x07` |

Rule of thumb: SCSI host = `ata` number minus 1.

## Fans

An **ITE IT5571 embedded controller** — not a Super I/O chip. Chip ID `0x5571`
can be read via configuration port `0x4e`.

Accessed from userspace through `/dev/port` using the ACPI EC protocol:

| | |
|---|---|
| Data port | `0x62` |
| Status/command port | `0x66` |
| Read | command `0x80`, then address, then data byte |
| Write | command `0x81`, then address, then value |
| Handshake | wait for IBF (bit 1) before each step, OBF (bit 0) before reading |

The ports are not claimed by the kernel, even though an ACPI EC device
(`PNP0C09:00`) exists.

### Registers (non-Pro, 2 fans)

| Address | Meaning |
|---|---|
| `0x96` / `0x97` | Fan 1 speed, 16-bit big-endian |
| `0x98` / `0x99` | Fan 2 speed, 16-bit big-endian |
| `0x9c` / `0x9d` | Fan 1: **enable**, duty (0–198) |
| `0x9e` / `0x9f` | Fan 2: **enable**, duty (0–198) |

The Pro model has four fans at `0x34` (speed) and `0xB0` (control).

**The enable byte is mandatory.** Left at `0`, the EC only partially accepts the
duty value — the fan then spins at roughly three quarters of its speed even at
duty 198. It returns to `0` after every reboot; that means "firmware controls
this itself", **not** "fan off" (the fans do keep spinning).

### Measured curve

Recorded with the chassis open, at idle. Fan 1 is two Noctua NF-A9 PWM on a
Y-cable, fan 2 a small high-RPM fan for a Tesla T4. Both still start reliably
at duty 40.

| Duty | Fan 1 | Fan 2 |
|---:|---:|---:|
| 198 | 1970 RPM | 7334 RPM |
| 180 | 1819 RPM | 7000 RPM |
| 160 | 1661 RPM | 6594 RPM |
| 140 | 1479 RPM | 6196 RPM |
| 120 | 1290 RPM | 5629 RPM |
| 100 | 1091 RPM | 5073 RPM |
| 80 | 878 RPM | 4295 RPM |
| 60 | 654 RPM | 3444 RPM |
| 40 | 399 RPM | 2409 RPM |

Both curves are close to linear. **These values only hold as long as the
firmware stays out of the way** — see the minimum-speed section in
[findings.md](findings.md).

#### Cross-check against production data

The table above was recorded by hand with the chassis open. As a control,
10,104 daemon log lines from the closed chassis were analysed (median per duty
value):

| Duty | Fan 2, hand-measured | Fan 2, in production | n |
|---:|---:|---:|---:|
| 198 | 7334 RPM | 7461 RPM | 37 |
| 160 | 6594 RPM | 6634 RPM | 9 |
| 140 | 6196 RPM | 6178 RPM | 5 |
| 100 | 5073 RPM | 5146 RPM | 16 |

The deviation is one to two percent — the curve holds up in production, if
anything slightly conservative. Highest value ever logged: 7619 RPM.

**Watch the sample size when analysing the log.** Duty values that appear only
five to eight times are transitional states during ramp-up or ramp-down: the
tachometer is read in the same cycle in which the new value is written, so it
lags behind the actual speed change. Such lines show apparent outliers, up to
and including inversions (higher duty, lower speed), and are not valid data
points. Values with a three-digit sample count match the table cleanly.

Fan 1 **cannot** be cross-checked this way, because the firmware interferes
there (see [findings.md](findings.md)).

## Temperature sensors

| Source | hwmon `name` | Note |
|---|---|---|
| CPU | `coretemp` | |
| SATA drives | `drivetemp` | |
| NVMe | `nvme` | **use `Composite` only**, see findings.md |
| Network controllers | interface name, e.g. `enp90s0` | PHY and MAC |
| GPU | — | via `nvidia-smi`, not hwmon |

For NVMe you have to check the label: besides `Composite` (the official value
reported by SMART) there are `Sensor 1`/`Sensor 2` — internal measurement
points, some without a defined limit and reading considerably higher.
