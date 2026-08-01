# UGREEN NASync iDX6011 (non-Pro) unter TrueNAS SCALE

LED- und Lüftersteuerung für den UGREEN iDX6011 **non-Pro** unter TrueNAS SCALE.
Beides läuft vollständig im Userspace — **kein Kernel-Modul nötig**, damit
unabhängig von der TrueNAS-Version und update-fest.

Getestet auf TrueNAS SCALE 26.0.0-BETA.2 (Kernel 6.18.23-production+truenas).

> **Warum eigene Scripte und nicht die vorhandenen Projekte?**
> Die verbreiteten Lösungen passen für dieses Modell nicht oder nur halb.
> Die Gründe stehen in [docs/findings.md](docs/findings.md) — bitte dort lesen,
> bevor du einen der Standardwege ausprobierst. Das spart Stunden.

## Was es kann

**LEDs** — Power-, Netzwerk- und sechs Platten-LEDs an der Gerätefront:

| LED | Verhalten |
|---|---|
| Power | Blau = alle Pools ONLINE · Orange blinkend = degraded/faulted |
| Netzwerk | Farbe nach Linkgeschwindigkeit, Blinkfrequenz nach **echtem Durchsatz** |
| disk1–6 | Grün = Platte vorhanden und fehlerfrei · Rot blinkend = ZFS-Fehler · Aus = Schacht leer |

**Lüfter** — beide Anschlüsse werden **getrennt** geregelt:

| Anschluss | Regelgröße |
|---|---|
| Lüfter 1 (Gehäuse) | höchster Bedarf aus CPU, Datenträgern und Netzwerk-Controllern |
| Lüfter 2 | GPU-Temperatur (hier: dedizierter Lüfter für eine Tesla T4) |

Mit Glättung gegen Drehzahlpendeln und Notfallschwellen, die alles übersteuern.

## Aufbau

```
leds/
  ugreen-led-lib.sh   Bibliothek: Farbe, Helligkeit, Blinken per i2cset
  led-update.sh       Power- und Platten-LEDs (Cron, alle 5 Min)
  led-network.sh      Netzwerk-LED mit Durchsatzanzeige (Daemon, 2s-Takt)
fan/
  fan-control.py      Lüfter-Daemon mit getrennten Kurven
  tools/              Diagnose- und Messwerkzeuge (siehe unten)
docs/
  hardware.md         Register, Indizes, Mappings, gemessene Kennlinien
  findings.md         Was nicht funktioniert und warum
```

## Installation

Die Scripte gehören auf ein **Dataset im Pool**, nicht ins Systemverzeichnis —
TrueNAS' Root ist schreibgeschützt und wird bei Updates ersetzt.

```bash
zfs create <pool>/scripts
mkdir -p /mnt/<pool>/scripts/{leds_controller,fancontrol}
```

Scripte dorthin kopieren, ausführbar machen, dann in der Weboberfläche unter
**System Settings → Advanced** eintragen:

| Typ | Zeitpunkt | Befehl |
|---|---|---|
| Command | PREINIT | `modprobe i2c-i801 && modprobe i2c-dev` |
| Command | POSTINIT | `/mnt/<pool>/scripts/leds_controller/led-update.sh` |
| Command | POSTINIT | `setsid nohup /mnt/<pool>/scripts/leds_controller/led-network.sh > /dev/null 2>&1 < /dev/null &` |
| Command | POSTINIT | `setsid nohup /mnt/<pool>/scripts/fancontrol/fan-control.py > /dev/null 2>&1 < /dev/null &` |

Dazu ein Cron-Job als `root`, alle 5 Minuten:
`/mnt/<pool>/scripts/leds_controller/led-update.sh`

**Pfade anpassen:** Die Scripte haben `/mnt/nvme-tank/scripts/...` fest
eingetragen (jeweils oben in der Datei).

## Anpassen

Farben, Schwellwerte und Kurven stehen als Konstanten am Anfang der jeweiligen
Datei. Die Lüfterkurven in `fan-control.py` sind bewusst konservativ ausgelegt —
die verbauten NVMe sind erst bei 87 °C kritisch, die Kurve geht schon bei 58 °C
auf Vollast. Wer Ruhe der Kühlung vorzieht, kann die Schwellen deutlich anheben.

## Werkzeuge

| Werkzeug | Zweck |
|---|---|
| `fan/tools/ec_read.py` | Aktuelle Drehzahlen und Ansteuerung auslesen |
| `fan/tools/ec_calib.py` | Kennlinie aufnehmen (Duty → RPM), mit Temperaturabbruch |
| `fan/tools/thermal_log.py` | Temperaturverlauf protokollieren |
| `fan/tools/loadtest_log.py` | Messprotokoll während eines Lasttests |
| `fan/tools/ab_test.py` | A/B-Vergleich zweier Lüftereinstellungen |

Alle Werkzeuge außer `ec_calib.py` und `ab_test.py` sind rein lesend.

## Sicherheitshinweis

Falsche Werte in Lüfterregistern können Hardware überhitzen. Die Scripte setzen
bei Fehlern, beim Beenden und über den Notfallschwellen immer auf **Vollast** —
prüfe das nach eigenen Änderungen. Nimm eine Kennlinie nur mit
Temperaturüberwachung und Abbruchbedingung auf.

Die EC-Firmware erzwingt zusätzlich eine eigene Mindestdrehzahl, wenn es warm
wird (siehe [docs/findings.md](docs/findings.md)) — ein Sicherheitsnetz unter
allem, was hier läuft.

## Lizenz und Herkunft

Die LED-Protokollkenntnisse stammen aus der Reverse-Engineering-Arbeit von
[miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller)
und dem iDX-Fork von
[klein0r](https://github.com/klein0r/ugreen_leds_controller);
die EC-Registerbelegung aus
[ugreen-idx6011-panel](https://github.com/Reevoy24/ugreen-idx6011-panel).
Dank an deren Autoren — ohne diese Vorarbeit wäre das hier nicht möglich gewesen.
