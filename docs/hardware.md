# Hardware-Referenz — UGREEN iDX6011 (non-Pro)

Alle Werte am 2026-08-01 auf echter Hardware verifiziert, TrueNAS SCALE
26.0.0-BETA.2. DMI meldet sich als Produkt `iDX6011`, Hersteller `UGREEN`.

## LEDs

Angebunden über einen I²C-MCU auf dem **SMBus** (`i2c-i801`), Bus `/dev/i2c-0`,
Adresse `0x3a`. Voraussetzung: `modprobe i2c-i801 && modprobe i2c-dev`.

### LED-Indizes

Das **non-Pro hat nur eine Netzwerk-LED** — das Pro-Modell hat zwei. Dadurch ist
die gesamte Platten-Kette gegenüber dem Pro **um eins verschoben**. Index `0x08`
existiert auf dem non-Pro nicht.

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

### Protokoll

SMBus-Blockwrite (`i2cset ... s`, **nicht** `i`). Elf Bytes:

```
0xA0 0x01 0x00 0x00  <cmd> <p1> <p2> <p3> <p4>  <ck_hi> <ck_lo>
```

Prüfsumme: `sum = 0xA0 + 0x01 + cmd + p1 + p2 + p3 + p4`,
danach `ck_hi = (sum >> 8) & 0xFF`, `ck_lo = sum & 0xFF`.

| cmd | Funktion | Parameter |
|---|---|---|
| `0x01` | Helligkeit | 0–255 |
| `0x02` | Farbe | R, G, B |
| `0x03` | Ein/Aus | `0xFF` = ein |
| `0x04` | Blinken | cycle_hi, cycle_lo, on_hi, on_lo |
| `0x05` | Atmen | wie Blinken |

Beispiel — Helligkeit auf Maximum für die Power-LED:

```bash
i2cset -y 0 0x3a 0x00 0xa0 0x01 0x00 0x00 0x01 0xff 0x00 0x00 0x00 0x01 0xa1 s
```

### Blinken beenden

Die MCU blinkt **autonom weiter**, bis man sie aktiv stoppt — es genügt nicht,
einfach keinen Blink-Befehl mehr zu senden. Der Mode-Reset (`0x04` mit lauter
Nullen) schaltet die LED dabei ab, deshalb muss `0x03` mit `0xFF` folgen.

Funktionierende Reihenfolge für sauberes Dauerlicht, je ~50 ms Pause:

```
0x04 (0,0,0,0)  ->  0x01 Helligkeit  ->  0x02 Farbe  ->  0x03 0xFF  ->  0x01 Helligkeit
```

Das entspricht der Übernahme-Sequenz, mit der man der MCU nach dem Boot die
Kontrolle abnimmt (sie fährt sonst eine eigene Animation).

## Laufwerksschächte

Zuordnung Schacht → SCSI-Adresse, durch Umstecken einer einzelnen Platte
ermittelt. Die Nummerierung ist **nicht durchgehend fortlaufend** — sie springt
am Ende auf `0:` und `1:` zurück. Identisch zum DXP6800 Pro.

| Schacht | ata | HCTL | LED-Index |
|---|---|---|---|
| 1 | ata3 | `2:0:0:0` | `0x02` |
| 2 | ata4 | `3:0:0:0` | `0x03` |
| 3 | ata5 | `4:0:0:0` | `0x04` |
| 4 | ata6 | `5:0:0:0` | `0x05` |
| 5 | ata1 | `0:0:0:0` | `0x06` |
| 6 | ata2 | `1:0:0:0` | `0x07` |

Faustregel: SCSI-Host = `ata`-Nummer minus 1.

## Lüfter

Ein **ITE IT5571 Embedded Controller** — kein Super-I/O-Baustein. Chip-ID
`0x5571` lässt sich über den Konfigurationsport `0x4e` auslesen.

Zugriff aus dem Userspace über `/dev/port` nach ACPI-EC-Protokoll:

| | |
|---|---|
| Datenport | `0x62` |
| Status-/Kommandoport | `0x66` |
| Lesen | Kommando `0x80`, dann Adresse, dann Datenbyte |
| Schreiben | Kommando `0x81`, dann Adresse, dann Wert |
| Handshake | vor jedem Schritt IBF (Bit 1) abwarten, vor dem Lesen OBF (Bit 0) |

Die Ports sind vom Kernel nicht reserviert, obwohl ein ACPI-EC-Gerät
(`PNP0C09:00`) existiert.

### Register (non-Pro, 2 Lüfter)

| Adresse | Bedeutung |
|---|---|
| `0x96` / `0x97` | Drehzahl Lüfter 1, 16 Bit big-endian |
| `0x98` / `0x99` | Drehzahl Lüfter 2, 16 Bit big-endian |
| `0x9c` / `0x9d` | Lüfter 1: **Freigabe**, Geschwindigkeit (0–198) |
| `0x9e` / `0x9f` | Lüfter 2: **Freigabe**, Geschwindigkeit (0–198) |

Das Pro-Modell hat vier Lüfter auf `0x34` (Drehzahl) und `0xB0` (Ansteuerung).

**Das Freigabe-Byte ist Pflicht.** Steht es auf `0`, nimmt der EC den
Geschwindigkeitswert nur teilweise an — der Lüfter dreht dann trotz Duty 198 nur
rund drei Viertel seiner Drehzahl. Nach jedem Neustart steht es auf `0`; das
bedeutet „Firmware regelt selbst", **nicht** „Lüfter aus" (die Lüfter drehen
dabei durchaus).

### Gemessene Kennlinie

Aufgenommen bei geöffnetem Gehäuse im Leerlauf. Lüfter 1 sind zwei Noctua
NF-A9 PWM an einem Y-Kabel, Lüfter 2 ein kleiner Hochdrehzahllüfter für eine
Tesla T4. Beide laufen bei Duty 40 noch zuverlässig an.

| Duty | Lüfter 1 | Lüfter 2 |
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

Beide Kennlinien sind nahezu linear. **Die Werte gelten nur, solange die
Firmware nicht dazwischengeht** — siehe Mindestdrehzahl in
[findings.md](findings.md).

## Temperatursensoren

| Quelle | hwmon-`name` | Anmerkung |
|---|---|---|
| CPU | `coretemp` | |
| SATA-Platten | `drivetemp` | |
| NVMe | `nvme` | **nur `Composite` verwenden**, siehe findings.md |
| Netzwerk-Controller | Name des Interfaces, z.B. `enp90s0` | PHY und MAC |
| GPU | — | über `nvidia-smi`, nicht über hwmon |

Für die NVMe muss man das Label prüfen: Neben `Composite` (der offizielle,
von SMART gemeldete Wert) gibt es `Sensor 1`/`Sensor 2` — interne Messpunkte,
teils ohne definierten Grenzwert und deutlich höher.
