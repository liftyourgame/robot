"""
split_by_bone.py
================
Blender Python script that splits a skinned mesh by dominant bone weight
and exports each segment as a separate STL file.

USAGE
-----
1. Open Blender (3.x or 4.x).
2. File > Import > glTF 2.0 — import Meshy_AI_Character_output.glb
3. Open the Scripting workspace tab.
4. Click "Open" and load this file  (or paste it into a new text block).
5. Edit OUTPUT_DIR below to point at your desired export folder.
6. Press "Run Script" (▶).

Each bone segment is exported as:
    <OUTPUT_DIR>/<bone_name>.stl

Vertices that are influenced by multiple bones are assigned to whichever
bone has the highest weight for that vertex.
"""

import bpy
import bmesh
import os

# ── CONFIG ────────────────────────────────────────────────────────────────────

# Absolute path to the folder where STLs will be written.
# Change this to suit your machine.
OUTPUT_DIR = "/Users/greg/local_development/humn/robot/specs/stl_parts"

# Name of the mesh object in the Blender scene.
# If you're unsure, check the Outliner — it's usually "char1" for this model.
MESH_OBJECT_NAME = "char1"

# Minimum bone weight to consider a vertex "influenced" by a bone.
# Vertices below this threshold on all bones stay in a residual "unassigned" mesh.
MIN_WEIGHT = 0.01

# ── HELPERS ───────────────────────────────────────────────────────────────────

def get_dominant_bone(vertex, obj):
    """
    Return the name of the vertex group (bone) with the highest weight
    for this vertex, or None if all weights are below MIN_WEIGHT.

    :param vertex: bmesh vertex (original mesh vertex index used)
    :param obj:    the Blender mesh object
    :returns:      str bone name or None
    """
    groups = obj.data.vertices[vertex.index].groups
    if not groups:
        return None

    best_group = max(groups, key=lambda g: g.weight)
    if best_group.weight < MIN_WEIGHT:
        return None

    return obj.vertex_groups[best_group.group].name


def export_stl(obj, filepath):
    """
    Export a single object as binary STL.

    :param obj:      Blender mesh object to export
    :param filepath: full output path including .stl extension
    """
    # Deselect all, then select only our target object
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj

    bpy.ops.wm.stl_export(
        filepath=filepath,
        export_selected_objects=True,
        ascii_format=False,   # binary STL — smaller files
    )
    print(f"  Exported → {filepath}")


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── 1. Find the source mesh object ───────────────────────────────────
    src_obj = bpy.data.objects.get(MESH_OBJECT_NAME)
    if src_obj is None or src_obj.type != 'MESH':
        raise RuntimeError(
            f"Object '{MESH_OBJECT_NAME}' not found or is not a mesh. "
            "Check MESH_OBJECT_NAME at the top of this script."
        )

    print(f"\n[split_by_bone] Source mesh: '{src_obj.name}'")
    print(f"[split_by_bone] Vertex groups: {len(src_obj.vertex_groups)}")
    print(f"[split_by_bone] Output dir:    {OUTPUT_DIR}\n")

    # ── 2. Build a map: bone_name → [vertex_index, ...] ─────────────────
    bm = bmesh.new()
    bm.from_mesh(src_obj.data)
    bm.verts.ensure_lookup_table()

    bone_verts: dict[str, list[int]] = {}   # bone name → list of vert indices
    unassigned: list[int] = []

    for v in bm.verts:
        bone = get_dominant_bone(v, src_obj)
        if bone:
            bone_verts.setdefault(bone, []).append(v.index)
        else:
            unassigned.append(v.index)

    bm.free()

    print(f"[split_by_bone] Bone segments found: {len(bone_verts)}")
    if unassigned:
        print(f"[split_by_bone] Unassigned vertices: {len(unassigned)} → saved as 'unassigned.stl'")
        bone_verts["unassigned"] = unassigned

    # ── 3. For each bone: duplicate mesh, delete unwanted verts, export ──
    created_objects = []

    for bone_name, vert_indices in bone_verts.items():
        print(f"  Processing bone: '{bone_name}' ({len(vert_indices)} verts)…")

        # Duplicate the source object (keeps UV, normals, transforms)
        dup = src_obj.copy()
        dup.data = src_obj.data.copy()
        dup.name = f"seg_{bone_name}"
        bpy.context.collection.objects.link(dup)

        # Switch to edit mode on the duplicate and delete verts NOT in this bone
        bpy.context.view_layer.objects.active = dup
        bpy.ops.object.mode_set(mode='EDIT')

        bm2 = bmesh.from_edit_mesh(dup.data)
        bm2.verts.ensure_lookup_table()

        keep = set(vert_indices)
        verts_to_delete = [v for v in bm2.verts if v.index not in keep]
        bmesh.ops.delete(bm2, geom=verts_to_delete, context='VERTS')

        bmesh.update_edit_mesh(dup.data)
        bpy.ops.object.mode_set(mode='OBJECT')

        # Apply the armature modifier so the STL is in rest pose
        for mod in dup.modifiers:
            if mod.type == 'ARMATURE':
                bpy.ops.object.modifier_apply(modifier=mod.name)
                break

        stl_path = os.path.join(OUTPUT_DIR, f"{bone_name}.stl")
        export_stl(dup, stl_path)

        created_objects.append(dup)

    # ── 4. Clean up — remove all the temporary duplicate objects ─────────
    bpy.ops.object.select_all(action='DESELECT')
    for obj in created_objects:
        obj.select_set(True)
    bpy.ops.object.delete()

    # Re-select the original
    src_obj.select_set(True)
    bpy.context.view_layer.objects.active = src_obj

    print(f"\n[split_by_bone] ✓ Done. {len(bone_verts)} STL files written to:\n  {OUTPUT_DIR}\n")


if __name__ == "__main__":
    main()
