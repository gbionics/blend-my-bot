import bpy

if bpy.app.version < (5, 0, 0):
    raise RuntimeError("Blend My Bot requires Blender 5.0 or newer")

from .link import Link
from .blender_model import BlenderModel
from .model_importer import ModelImporter
