# Was nicht funktioniert — und warum

Dieses Dokument ist wichtiger als der Code. Es hält fest, welche naheliegenden
Wege wir ausprobiert haben und woran sie gescheitert sind. Ohne diese Notizen
probiert man den vermeintlich einfacheren Weg in einem Jahr erneut aus.

Alles am 2026-08-01 auf einem UGREEN iDX6011 **non-Pro** unter TrueNAS SCALE
26.0.0-BETA.2 festgestellt.

---

## LEDs

### `ugreen_leds_cli` setzt die Helligkeit auf 0

Der iDX-Fork [klein0r/ugreen_leds_controller](https://github.com/klein0r/ugreen_leds_controller)
erkennt den iDX6011 korrekt per DMI und liest auch alle LEDs sauber aus. Aber:

**Jeder Aufruf des CLI setzt die Helligkeit der angesprochenen LED auf 0** —
auch ein reines `-status`. Die LED geht damit aus.

Beobachtbar so: Farbe per rohem `i2cset` setzen, Helligkeit per `i2cset` auf
255 — die LED leuchtet. Danach `ugreen_leds_cli power -status` aufrufen — die
LED geht aus. Der Statuswert meldet dann konsequent `brightness = 0`, während
die Farbe korrekt übernommen wurde.

**Konsequenz:** Das CLI ist auf diesem Modell unbrauchbar. Wir sprechen den
MCU direkt per `i2cset` an. Das Protokoll selbst funktioniert einwandfrei — der
Fehler sitzt im CLI, nicht in der Hardware.

Das gebaute Binary liegt trotzdem als Referenz im Repo; es ist nützlich, um
sich den Ist-Zustand aller LEDs anzusehen (dann aber danach neu setzen).

### Es gibt keine fertigen Binaries für den iDX6011

Für die DX/DXP-Serie liefert
[miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller)
fertige Releases. Für die iDX-Serie braucht man den klein0r-Fork — und der hat
**keine Releases**. Das CLI muss aus dem Quellcode gebaut werden.

TrueNAS hat keinen Compiler. Der Bau gelingt trotzdem in einem
Wegwerf-Container:

```bash
docker run --rm -v /mnt/<pool>/scripts/leds_controller:/out debian:bookworm bash -c '
  apt-get update -qq && apt-get install -y -qq git build-essential libi2c-dev
  git clone -q --depth 1 https://github.com/klein0r/ugreen_leds_controller /src
  cd /src/cli && make && cp ugreen_leds_cli /out/'
```

Das Makefile linkt bereits statisch. Auf dem Host wird nichts installiert.

### Der Weg über das Kernel-Modul ist eine Sackgasse

Naheliegend, aber falsch: Das Installationsscript
[0x556c79/install_ugreen_leds_controller](https://github.com/0x556c79/install_ugreen_leds_controller)
sucht ein **vorgebautes Kernel-Modul** passend zur TrueNAS-Version. Vorhanden
sind nur Builds bis Goldeye (25.10) — für 26.0.x existiert in keinem der beiden
Repos etwas, und es bricht sauber ab:

```
Detected TrueNAS version: 26.0.0
Unsupported TrueNAS SCALE version: 26.0.0.
No precompiled kernel module found in repository.
```

**Das Modul wird aber gar nicht gebraucht.** Es liefert `/sys/class/leds`-Einträge
und Trigger; für reine Statusanzeige genügt der Userspace-Zugriff über I²C. Der
Verzicht darauf ist sogar der robustere Weg, weil kein Kernel-Update etwas
kaputtmachen kann.

### Das non-Pro hat eine Netzwerk-LED weniger

Das Pro-Modell hat zwei Netzwerk-LEDs (`network_stat`, `network_stat2`), das
non-Pro nur eine. Dadurch ist die **gesamte Platten-Kette um einen Index
verschoben**, und `0x08` existiert nicht.

Wer die Pro-Belegung übernimmt, wundert sich über eine dunkle erste Platten-LED
und eine, die nie reagiert. Siehe [hardware.md](hardware.md) für die korrekte
Tabelle.

### Blinken hört nicht von selbst auf

Die MCU blinkt autonom weiter, bis man sie aktiv stoppt. Wer einfach aufhört,
Blink-Befehle zu senden, hat eine dauerhaft blinkende LED.

Der Mode-Reset (`0x04` mit Nullen) schaltet die LED dabei **ab** — es braucht
zwingend ein anschließendes `0x03` mit `0xFF`, um sie wieder zu aktivieren.
Fehlt das, bleibt sie dunkel, obwohl Farbe und Helligkeit gesetzt sind.

---

## Lüfter

### `it87` funktioniert prinzipiell nicht

Auf dem DXP6800 Pro läuft die Lüftersteuerung über einen `it8613` Super-I/O-Chip
und den [IT-Kuny-Treiber](https://github.com/IT-Kuny/UGREEN-DXP-FAN-NAS-Driver).
Das lässt sich **nicht** auf den iDX6011 übertragen.

Der iDX6011 hat keinen Super-I/O-Baustein, sondern einen **ITE IT5571 Embedded
Controller**. `modprobe it87` quittiert entsprechend mit `No such device` — auch
das im TrueNAS-Kernel bereits enthaltene `it87.ko`. Das IT-Kuny-Repo listet den
iDX6011 folgerichtig nicht als unterstützt.

Nebenbei: Kernel-Header *sind* auf TrueNAS vorhanden
(`/usr/src/linux-headers-truenas-production-amd64`, `hwmon-vid.ko`, BTF unter
`/sys/kernel/btf/vmlinux`) — ein Modulbau wäre also technisch möglich. Er würde
hier nur nichts nützen.

### `ug-fand` regelt beide Lüfter gekoppelt

[ug-fand](https://github.com/Reevoy24/ugreen-idx6011-panel) funktioniert und ist
sauber gebaut — es hat uns die EC-Registerbelegung geliefert. Aber es fährt
**beide Lüfter mit demselben Wert** und kennt keine GPU-Temperatur.

Für den Standardfall (zwei gleichwertige Gehäuselüfter) ist das richtig. Wer an
einem Anschluss einen dedizierten Lüfter für eine Erweiterungskarte hat, braucht
getrennte Regelung — daher der eigene Daemon.

Zwei Fallstricke beim Ausprobieren:
* Das Binary hat **keine `--help`-Option**. Es startet stattdessen sofort als
  Daemon und regelt die Lüfter.
* Nach dem Beenden bleiben die zuletzt geschriebenen Werte stehen — die Lüfter
  gehen **nicht** automatisch auf einen sicheren Wert zurück.

### Das Freigabe-Byte wird leicht übersehen

Der auffälligste Fehler in unserer eigenen Entwicklung: Wir schrieben nur die
Geschwindigkeitsregister (`0x9d`/`0x9f`), nicht die Freigabe-Bytes
(`0x9c`/`0x9e`).

Der EC nimmt den Wert dann nur teilweise an. Konkret gemessen: Duty 198 ergab
**5557 RPM statt 7435 RPM** — rund ein Viertel Drehzahl verschenkt, während die
GPU unter Volllast stand. Von außen wirkt es, als sei die Regelung „zu leise
eingestellt".

Nach einem Neustart stehen die Freigabe-Bytes auf `0`. Das heißt **nicht**
„Lüfter aus", sondern „Firmware regelt selbst" — die Lüfter drehen dabei.

### Die Firmware erzwingt eine Mindestdrehzahl

Der EC gibt die Kontrolle nicht vollständig ab. Wird es warm (CPU ab etwa
55 °C), hält er Lüfter 1 nahe Vollast, unabhängig davon, welchen niedrigeren
Wert wir schreiben. Erst bei kühler CPU greift unser Wert.

Gemessen unter GPU-Volllast: Duty 150 und Duty 195 ergaben **1918 bzw. 1916
RPM** — praktisch identisch. Bei kalter CPU liefert Duty 150 dagegen rund
1530 RPM.

Zwei Konsequenzen:
* Die gemessene Kennlinie gilt nur im kühlen Zustand.
* Eine explizite Kopplung „Lüfter 1 mindestens X % von Lüfter 2" ist überflüssig
  — die Hardware macht das bereits. Wenn die GPU heiß wird, läuft auch die CPU
  unter Last und Lüfter 1 ist ohnehin oben.

Das ist ein nützliches Sicherheitsnetz: Selbst ein abgestürzter Daemon oder eine
falsch ausgelegte Kurve führt nicht zur Überhitzung.

### NVMe: nur `Composite` auswerten

NVMe melden mehrere Sensoren. `Composite` ist der offizielle Wert mit Warn- und
Kritischschwelle — der, den SMART und die TrueNAS-Berichte anzeigen. Daneben
gibt es `Sensor 1`/`Sensor 2` (interne Messpunkte, meist der Controller).

Auf diesem Gerät meldet die billige Boot-NVMe (YSO128) einen `Sensor 1` mit
dauerhaft ~51 °C, während ihr `Composite` bei 35 °C liegt — **16 Grad
Unterschied, ohne definierten Grenzwert für den heißen Sensor**.

Wer das Maximum über alle Sensoren nimmt, regelt auf einen Wert, der nichts
bedeutet, auf dem unwichtigsten Datenträger im System: Lüfter 1 lief mit Duty
96–110 statt der angemessenen 52, während die eigentlichen Pool-Laufwerke
entspannt bei 37 °C lagen.

Auffällig wird das erst im Vergleich mit den TrueNAS-Berichten — deren Werte
wichen deutlich von denen des Daemons ab.

---

## Tesla T4 in diesem Gehäuse

Anmerkungen zu einer passiv gekühlten Tesla T4 im iDX6011, gekühlt von einem
dedizierten Lüfter am zweiten Anschluss.

**Der Slot meldet `SlotPowerLimit 25W`** — folgenlos. `nvidia-smi` weist ein
Limit von 70 W aus, und die Karte zieht diese auch. Der PCIe-Link läuft mit
x8 statt x16 (`Width x8 (downgraded)`), was funktional unkritisch ist.

**Treiber:** Nicht manuell installieren. TrueNAS bringt passende Treiber mit,
zu aktivieren über `midclt call --job docker.update '{"nvidia": true}'` oder die
Weboberfläche. Hier: Treiber 590.44.01, CUDA 13.1.

**Lasttest (`gpu-burn`, 10 Minuten, geschlossenes Gehäuse):** Die Karte pendelt
sich bei **76–78 °C** ein, GPU-Lüfter auf Vollast.

Entscheidend ist die Ursache der Taktabsenkung von 1590 auf ~765 MHz:

```
SW Power Cap:          Active
HW Thermal Slowdown:   Not Active
SW Thermal Slowdown:   Not Active
```

Die Karte ist **power-limitiert, nicht thermisch limitiert**; alle
Thermal-Slowdown-Zähler stehen auf 0 µs. Die Kühlung ist also ausreichend, und
ein Absenken des Power-Limits (`nvidia-smi -pl`) löst kein vorhandenes Problem.

Wer die Temperatur allein sieht, kommt leicht zum gegenteiligen Schluss — die
Throttle-Gründe abzufragen ist der einzige verlässliche Weg.
