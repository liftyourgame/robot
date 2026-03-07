# Robot 3D-Printed Parts List
> Derived from `Meshy_AI_Character_output.glb` skeleton (23 bones → rigid shell segments)

Each **panel** is a rigid plastic shell that surrounds one bone segment.  
Joints between panels are either servo-driven or passive pivot connectors.

---

## Scale

| Parameter | Value |
|-----------|-------|
| Full model height | 1,700 mm |
| **Print scale** | **50%** |
| **Assembled height** | **850 mm** |
| Shoulder width | 380 mm |
| Depth (front to back) | 185 mm |

> Set scale to **50%** in Bambu Studio before slicing each part.

---

## HEAD (4 parts)
> Estimated height at 50%: ~170 mm — fits P1S (256 mm) ✅

| # | Part | Qty | Notes |
|---|------|-----|-------|
| H-01 | Head shell — rear dome | 1 | Back half of cranium |
| H-02 | Head shell — front face plate | 1 | `headfront` bone; visor/eye cutouts |
| H-03 | Head top cap | 1 | `head_end` bone; closes the crown |
| H-04 | Neck collar | 1 | `neck` bone; connects to Spine02; houses head-pan servo |

---

## TORSO (5 parts)
> Estimated height at 50%: ~340 mm — **exceeds P1S build volume (256 mm) ⚠️**  
> **Split T-01/T-02 chest and T-03/T-04/T-05 hip section into two separate prints.**

| # | Part | Qty | Notes |
|---|------|-----|-------|
| T-01 | Upper chest — front plate | 1 | `Spine02` bone; speaker/LED panel optional |
| T-02 | Upper chest — rear plate | 1 | Mirror of T-01; cable routing channels |
| T-03 | Mid torso shell | 1 | `Spine01` bone; spans waist |
| T-04 | Lower torso / abdomen shell | 1 | `Spine` bone |
| T-05 | Hip pelvis shell | 1 | `Hips` bone; central structural hub; mounts all leg servos |

---

## LEFT ARM (5 parts)
> Estimated length at 50%: ~240 mm — fits P1S ✅

| # | Part | Qty | Notes |
|---|------|-----|-------|
| LA-01 | Left shoulder cap | 1 | `LeftShoulder` bone; ball-socket housing |
| LA-02 | Left upper arm shell | 1 | `LeftArm` bone; elbow pivot mount |
| LA-03 | Left forearm shell | 1 | `LeftForeArm` bone |
| LA-04 | Left wrist cuff | 1 | Wrist rotation housing |
| LA-05 | Left hand — back plate | 1 | `LeftHand` bone |

---

## RIGHT ARM (5 parts — mirror of left)
> Mirror of left arm — same dimensions ✅

| # | Part | Qty | Notes |
|---|------|-----|-------|
| RA-01 | Right shoulder cap | 1 | `RightShoulder` bone |
| RA-02 | Right upper arm shell | 1 | `RightArm` bone |
| RA-03 | Right forearm shell | 1 | `RightForeArm` bone |
| RA-04 | Right wrist cuff | 1 | Wrist rotation housing |
| RA-05 | Right hand — back plate | 1 | `RightHand` bone |

---

## LEFT LEG (5 parts)
> Estimated length at 50%: ~320 mm total leg; thigh ~170 mm, shin ~150 mm — fits P1S ✅

| # | Part | Qty | Notes |
|---|------|-----|-------|
| LL-01 | Left thigh shell | 1 | `LeftUpLeg` bone; hip joint mount |
| LL-02 | Left shin shell | 1 | `LeftLeg` bone; knee hinge mount |
| LL-03 | Left ankle housing | 1 | `LeftFoot` bone; ankle servo |
| LL-04 | Left foot sole | 1 | Base plate; flat for stability |
| LL-05 | Left toe plate | 1 | `LeftToeBase` bone |

---

## RIGHT LEG (5 parts — mirror of left)
> Mirror of left leg — same dimensions ✅

| # | Part | Qty | Notes |
|---|------|-----|-------|
| RL-01 | Right thigh shell | 1 | `RightUpLeg` bone |
| RL-02 | Right shin shell | 1 | `RightLeg` bone |
| RL-03 | Right ankle housing | 1 | `RightFoot` bone |
| RL-04 | Right foot sole | 1 | |
| RL-05 | Right toe plate | 1 | `RightToeBase` bone |

---

## STRUCTURAL / CONNECTOR PARTS (not panels)

| # | Part | Qty | Notes |
|---|------|-----|-------|
| S-01 | Servo bracket — standard | ~18 | One per motorised joint |
| S-02 | Shoulder ball joint cup | 2 | Press-fit into LA-01 / RA-01 |
| S-03 | Hip ball joint cup | 2 | Press-fit into T-05 |
| S-04 | Knee hinge pin housing | 2 | Connects thigh to shin shells |
| S-05 | Spine stacking connector | 3 | Links T-02 → T-03 → T-04 → T-05 |
| S-06 | Cable management clips | ~20 | Snap into channel grooves on shells |
| S-07 | Electronics tray (chest) | 1 | Sits inside T-01/T-02; holds MCU & battery |

---

## SUMMARY

| Region | Shell panels | Connectors |
|--------|-------------|------------|
| Head   | 4 | 1 neck servo bracket |
| Torso  | 5 | 3 spine connectors |
| Arms   | 10 (5 × 2) | 2 shoulder cups, 2 wrist housings |
| Legs   | 10 (5 × 2) | 2 hip cups, 2 knee housings |
| **Total panels** | **29** | |
| **Total structural** | | **~29** |
| **Grand total parts** | **~58** | |

---

## Recommended Print Settings

| Parameter | Value |
|-----------|-------|
| Material | PETG (impact resistance) or PLA+ for prototyping |
| Layer height | 0.2 mm standard; 0.1 mm for face plate (H-02) |
| Infill | 30% gyroid for structural parts; 15% for cosmetic shells |
| Walls | 3 perimeters minimum on all load-bearing parts |
| Supports | Required on shoulder caps (LA-01, RA-01) and foot soles |
| Scale | Set to **50%** uniformly in Bambu Studio before slicing |
| Torso split | Cut T-01/T-02 and T-03–T-05 into two print jobs; join with M3 bolts + heat-set inserts |
