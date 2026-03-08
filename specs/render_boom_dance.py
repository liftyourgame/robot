"""
render_boom_dance.py
────────────────────
Blender headless script that loads the robot GLB, finds the clip that
is labelled "Boom Dance" in the UI (the raw GLB clip is named "Walking"),
sets up a camera + 3-point lighting, and renders every frame to PNG.

Run from the project root:
    blender --background --python specs/render_boom_dance.py

Output: frames_boom_dance/frame_NNNN.png
Then run:  python3 specs/make_gif.py
"""

import bpy
import os
import math
try:
    from termcolor import cprint
    def log(msg, color="cyan"): cprint(f"[render] {msg}", color)
except ImportError:
    def log(msg, color="cyan"): print(f"[render] {msg}")


# ── CONFIG ────────────────────────────────────────────────────────────────────

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GLB_PATH    = os.path.join(ROOT, "Meshy_AI_biped", "Meshy_AI_Meshy_Merged_Animations.glb")
OUTPUT_DIR  = os.path.join(ROOT, "frames_boom_dance")

# The GLB clip physically named "Walking" is the Boom Dance animation.
# (Meshy mislabelled it — see ANIM_LABEL_MAP in robot.html)
TARGET_CLIP = "Walking"

RENDER_W    = 512       # output frame width  (px)
RENDER_H    = 720       # output frame height (px)
FPS         = 24        # frames per second
SKIP        = 1         # render every Nth frame (raise to 2-3 for a quick preview)

# Camera: 3/4 front view, slightly above robot mid-point
CAM_DIST        = 3.4   # distance from robot centre (Blender units)
CAM_YAW_DEG     = 35    # horizontal offset angle
CAM_PITCH_DEG   = 12    # elevation angle
CAM_TARGET_Z    = 0.9   # world Z of the point the camera looks at (robot mid-torso)
CAM_LENS_MM     = 55    # focal length


# ── CLEAR DEFAULT SCENE ───────────────────────────────────────────────────────

log("Clearing default scene")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete()
# Remove default cube/camera/light if they still exist
for name in ("Cube", "Camera", "Light"):
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)


# ── IMPORT GLB ────────────────────────────────────────────────────────────────

if not os.path.exists(GLB_PATH):
    raise FileNotFoundError(f"GLB not found: {GLB_PATH}")

log(f"Importing {GLB_PATH}")
bpy.ops.import_scene.gltf(filepath=GLB_PATH)
log("Import complete", "green")


# ── FIND ARMATURE ─────────────────────────────────────────────────────────────

armature = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if armature is None:
    raise RuntimeError("No armature found — check the GLB import succeeded.")
log(f"Armature: {armature.name}")


# ── LIST + SELECT TARGET ACTION ───────────────────────────────────────────────

action_names = [a.name for a in bpy.data.actions]
log(f"Available actions: {action_names}")

target_action = None
for action in bpy.data.actions:
    if TARGET_CLIP.lower() in action.name.lower():
        target_action = action
        log(f"Using action: {action.name}  "
            f"({int(action.frame_range[0])}–{int(action.frame_range[1])} frames)", "green")
        break

if target_action is None:
    log(f"WARNING: '{TARGET_CLIP}' not found in actions. Falling back to first.", "yellow")
    target_action = bpy.data.actions[0]
    log(f"Using: {target_action.name}")

armature.animation_data_create()
armature.animation_data.action = target_action

frame_start = int(target_action.frame_range[0])
frame_end   = int(target_action.frame_range[1])
log(f"Animation frames: {frame_start} → {frame_end}  ({frame_end - frame_start + 1} total)")


# ── SCENE FRAME RANGE ─────────────────────────────────────────────────────────

scene = bpy.context.scene
scene.frame_start = frame_start
scene.frame_end   = frame_end
scene.render.fps  = FPS


# ── WORLD BACKGROUND ─────────────────────────────────────────────────────────

log("Setting world background")
world = scene.world
if world is None:
    world = bpy.data.worlds.new("World")
    scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.04, 0.07, 0.13, 1.0)   # dark navy
    bg.inputs[1].default_value = 1.0


# ── CAMERA ───────────────────────────────────────────────────────────────────

log("Setting up camera")
bpy.ops.object.camera_add()
cam_obj = bpy.context.active_object
cam_obj.name = "RenderCam"
scene.camera = cam_obj
cam_obj.data.lens = CAM_LENS_MM

yaw   = math.radians(CAM_YAW_DEG)
pitch = math.radians(CAM_PITCH_DEG)
cam_obj.location = (
    math.sin(yaw)  * CAM_DIST,
    -math.cos(yaw) * CAM_DIST,
    CAM_TARGET_Z + math.sin(pitch) * CAM_DIST,
)

# Empty as look-at target
bpy.ops.object.empty_add(type="PLAIN_AXES", location=(0.0, 0.0, CAM_TARGET_Z))
look_at = bpy.context.active_object
look_at.name = "CamTarget"

ct = cam_obj.constraints.new("TRACK_TO")
ct.target     = look_at
ct.track_axis = "TRACK_NEGATIVE_Z"
ct.up_axis    = "UP_Y"


# ── LIGHTING (3-point) ────────────────────────────────────────────────────────

log("Adding lights")

def add_sun(name, location, energy, color):
    bpy.ops.object.light_add(type="SUN", location=location)
    light = bpy.context.active_object
    light.name = name
    light.data.energy = energy
    light.data.color  = color
    return light

add_sun("KeyLight",  ( 2.5, -2.0,  5.0), energy=4.0, color=(1.00, 0.95, 0.85))
add_sun("FillLight", (-2.0, -1.5,  2.5), energy=1.4, color=(0.70, 0.85, 1.00))
add_sun("RimLight",  ( 0.0,  3.5,  3.5), energy=2.0, color=(0.60, 0.80, 1.00))


# ── RENDER SETTINGS ───────────────────────────────────────────────────────────

log("Configuring render settings")

# Use EEVEE (fast, looks great for stylised characters)
for engine in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
    try:
        scene.render.engine = engine
        log(f"Render engine: {engine}", "green")
        break
    except TypeError:
        continue

scene.render.resolution_x          = RENDER_W
scene.render.resolution_y          = RENDER_H
scene.render.resolution_percentage = 100
scene.render.film_transparent       = False

scene.render.image_settings.file_format  = "PNG"
scene.render.image_settings.color_mode   = "RGB"
scene.render.image_settings.compression  = 15   # fast write


# ── RENDER FRAMES ─────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

frames_to_render = range(frame_start, frame_end + 1, SKIP)
total = len(frames_to_render)
log(f"Rendering {total} frames → {OUTPUT_DIR}")

for i, frame in enumerate(frames_to_render, 1):
    scene.frame_set(frame)
    out_path = os.path.join(OUTPUT_DIR, f"frame_{frame:04d}.png")
    scene.render.filepath = out_path
    bpy.ops.render.render(write_still=True)
    log(f"  {i}/{total}  frame {frame:04d}", "white")

log(f"Done — {total} frames saved to {OUTPUT_DIR}", "green")
log("Next step: python3 specs/make_gif.py", "cyan")
