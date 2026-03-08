# Robot Build — Equipment List
> All prices in **AUD** (converted at 1 USD = 1.41 AUD, March 2026)

---

## 1. 3D Printer

| Option | Model | Price | Best For |
|--------|-------|-------|----------|
| ⭐ Recommended | Bambu Lab P1S | ~$990 | Best balance — enclosed, fast, fits all panels |
| Budget | Bambu Lab A1 Mini | ~$425 | Starter option; some panels need splitting |
| Premium | Bambu Lab X1C | ~$1,690 | Carbon-fibre filaments, max strength |

**Why enclosed matters:** PETG warps without an enclosure. The P1S is the sweet spot.

Install slicer software:
```bash
brew install --cask bambu-studio
```

---

## 2. Filament

| Material | Use | Qty | Cost |
|----------|-----|-----|------|
| PETG (black or grey) | All structural shells & joints | 3 × 1kg spools | ~$35/spool |
| PLA+ (any colour) | Prototyping / test fits | 1 × 1kg spool | ~$28/spool |
| TPU 95A (flexible) | Foot sole pads, fingertip grips | 0.5kg spool | ~$35 |

> Print structural parts in PETG. Use PLA+ only for dry-run test fits before committing PETG.

---

## 3. Servos

The robot has 18 motorised joints based on the skeleton:

| Joint Group | Servo Model | Qty | Torque | Unit Price | Total |
|-------------|------------|-----|--------|------------|-------|
| Hips, knees, shoulders (high load) | DS3225 25kg Digital Servo | 8 | 25 kg·cm | ~$17 | ~$136 |
| Elbows, ankles, wrists (medium load) | MG996R Metal Gear Servo | 6 | 13 kg·cm | ~$10 | ~$60 |
| Neck, wrist rotation, toes (low load) | SG90 Micro Servo | 4 | 1.8 kg·cm | ~$4 | ~$16 |

**Subtotal: ~$212**

> All three are standard PWM servos — compatible with any servo driver board.

---

## 4. Electronics & Control

| Component | Model | Qty | Cost |
|-----------|-------|-----|------|
| Single-board computer | Raspberry Pi 5 (4GB) | 1 | ~$85 |
| Servo driver board | PCA9685 16-channel PWM | 2 | ~$11 each |
| Power distribution board | 5V/6V BEC + 12V rail | 1 | ~$21 |
| Logic level converter | 3.3V ↔ 5V bidirectional | 1 | ~$7 |
| IMU (balance sensor) | MPU-6050 6-axis | 1 | ~$7 |
| Micro SD card (OS) | 32GB Class 10 | 1 | ~$14 |

**Subtotal: ~$156**

---

## 5. Power

| Component | Spec | Qty | Cost |
|-----------|------|-----|------|
| LiPo battery pack | 3S 11.1V 5000mAh | 1 | ~$50 |
| LiPo balance charger | ISDT Q6 Plus or similar | 1 | ~$56 |
| Voltage regulators | Step-down 12V→6V (servos) + 12V→5V (Pi) | 2 | ~$14 each |
| XT60 connectors + wiring | 18 AWG silicone wire | 1 pack | ~$17 |

**Subtotal: ~$151**

> LiPo gives good power density for a walking robot. Always use a balance charger — never charge unattended.

---

## 6. Fasteners & Hardware

| Item | Spec | Qty | Cost |
|------|------|-----|------|
| Heat-set inserts | M3 × 4mm OD × 5mm | 100 pack | ~$11 |
| Socket head bolts | M3 × 8mm, M3 × 12mm | 200 pack | ~$14 |
| Socket head bolts | M2 × 6mm (servo horns) | 50 pack | ~$8 |
| Servo horn screws | Self-tapping 2mm | 50 pack | ~$6 |
| Ball bearings | 3×8×4mm MR83ZZ | 20 pack | ~$14 |
| Soldering iron + solder | Any temp-controlled iron | 1 | ~$42 |
| Heat shrink tubing | Assorted sizes | 1 pack | ~$11 |

**Subtotal: ~$106**

---

## 7. Audio

| Component | Spec | Qty | Cost |
|-----------|------|-----|------|
| Speaker | 40mm 3W 8Ω round | 1 | ~$8 |
| I²S Amplifier | MAX98357A breakout board | 1 | ~$10 |
| MEMS Microphone | INMP441 I²S breakout board | 2 | ~$12 each |

**Subtotal: ~$42**

> All three connect via I²S to Raspberry Pi GPIO — no USB audio adapter needed.
> Speaker mounts behind the chest grille (T-01). Mics seat inside the ear panels.

---

## 8. Tools

| Tool | Notes |
|------|-------|
| Heat-set insert tip | Fits standard soldering iron; melts inserts into PETG cleanly |
| Digital calipers | Essential for verifying printed tolerances |
| Allen key set | M2 / M3 socket heads |
| Multimeter | Voltage/continuity checks on wiring |
| Wire strippers | 22–28 AWG |

---

## Total Budget Summary

| Category | Cost (AUD) |
|----------|------------|
| 3D Printer (P1S) | ~$990 |
| Filament | ~$133 |
| Servos | ~$212 |
| Electronics & Control | ~$156 |
| Power | ~$151 |
| Audio | ~$42 |
| Fasteners & Hardware | ~$106 |
| Tools (if not owned) | ~$85 |
| **Total** | **~$1,875** |

> Reduce to ~$1,310 with the A1 Mini instead of P1S.  
> Increase to ~$2,575 with the X1C for carbon-fibre capable printing.
