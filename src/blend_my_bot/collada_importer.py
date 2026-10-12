from pathlib import Path
from urllib.parse import unquote, urlsplit

import bpy
import collada
import numpy as np

from .collada_mesh import ColladaPart, read_collada

DEFAULT_COLOR = (0.0, 0.0, 0.0, 1.0)
LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)


def texture_path(path: str, dae: Path) -> Path:
    uri = urlsplit(path)
    if uri.scheme == "file" and uri.netloc in {"", "localhost"}:
        result = Path(unquote(uri.path))
    elif not uri.scheme:
        result = dae.parent / unquote(path)
    else:
        raise ValueError(f"Unsupported DAE texture URI: {path}")
    if not result.is_file():
        raise FileNotFoundError(f"DAE texture not found: {result}")
    return result.resolve()


def _color(value, name: str) -> tuple[float, float, float, float]:
    if value is None:
        return DEFAULT_COLOR
    array = np.asarray(value, dtype=float)
    if array.shape != (4,) or not np.all(np.isfinite(array)):
        raise ValueError(f"DAE material {name} must contain four finite color values")
    if np.any(array < 0) or not 0 <= array[3] <= 1:
        raise ValueError(f"DAE material {name} has invalid color/alpha values")
    return tuple(array)


def _texture(nodes, links, mapping, part, dae, images):
    if not part.texcoords:
        raise ValueError(f"Textured DAE mesh '{part.name}' has no texture coordinates")
    binding = part.material_inputs.get(mapping.texcoord)
    if binding is not None:
        semantic, uv_set = binding
        if semantic != "TEXCOORD":
            raise ValueError(f"Unsupported DAE texture binding: {semantic}")
        uv_set = int(uv_set)
    elif mapping.texcoord is None:
        uv_set = part.texcoord_sets[0]
    else:
        raise ValueError(
            f"DAE texture-coordinate binding is missing: {mapping.texcoord}"
        )
    if uv_set not in part.texcoord_sets:
        raise ValueError(f"DAE texture-coordinate set is missing: {uv_set}")
    path = texture_path(mapping.sampler.surface.image.path, dae)
    if path not in images:
        image = bpy.data.images.load(str(path), check_existing=False)
        image.pack()
        images[path] = image
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = images[path]
    uv = nodes.new("ShaderNodeUVMap")
    uv.uv_map = f"UV{uv_set}"
    links.new(uv.outputs["UV"], texture.inputs["Vector"])
    return texture


def build_material(part: ColladaPart, dae: Path, images) -> bpy.types.Material:
    source = part.material
    effect = source.effect
    if effect.bumpmap is not None:
        raise ValueError(
            f"DAE material '{source.name or source.id}' uses an unsupported bump map"
        )
    material = bpy.data.materials.new(source.name or source.id)
    if material.node_tree is None:
        material.use_nodes = True
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    shader = nodes.get("Principled BSDF")
    if shader is None:
        raise RuntimeError("Blender did not create a Principled material node")
    material.use_backface_culling = not part.double_sided
    if isinstance(effect.diffuse, collada.material.Map):
        texture = _texture(nodes, links, effect.diffuse, part, dae, images)
        links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    else:
        color = _color(effect.diffuse, "diffuse")
        material.diffuse_color = color
        shader.inputs["Base Color"].default_value = color
        shader.inputs["Alpha"].default_value = color[3]
    if isinstance(effect.emission, collada.material.Map):
        texture = _texture(nodes, links, effect.emission, part, dae, images)
        links.new(texture.outputs["Color"], shader.inputs["Emission Color"])
        shader.inputs["Emission Strength"].default_value = 1
    else:
        emission = _color(effect.emission, "emission")
        shader.inputs["Emission Color"].default_value = emission
        shader.inputs["Emission Strength"].default_value = float(any(emission[:3]))
    if isinstance(effect.specular, collada.material.Map):
        texture = _texture(nodes, links, effect.specular, part, dae, images)
        links.new(texture.outputs["Color"], shader.inputs["Specular Tint"])
    else:
        specular = _color(effect.specular, "specular")
        shader.inputs["Specular Tint"].default_value = (*specular[:3], 1)
        shader.inputs["Specular IOR Level"].default_value = float(np.mean(specular[:3]))
    if effect.shininess is not None:
        shininess = float(effect.shininess)
        if not np.isfinite(shininess) or shininess < 0:
            raise ValueError("DAE material shininess must be nonnegative and finite")
        shader.inputs["Roughness"].default_value = float(np.sqrt(2 / (shininess + 2)))
    if effect.index_of_refraction is not None:
        ior = float(effect.index_of_refraction)
        if not np.isfinite(ior) or ior < 1:
            raise ValueError("DAE material index of refraction must be finite and >= 1")
        shader.inputs["IOR"].default_value = ior
    if effect.transparent is not None or effect.transparency is not None:
        factor = 1.0 if effect.transparency is None else float(effect.transparency)
        if not np.isfinite(factor) or not 0 <= factor <= 1:
            raise ValueError("DAE material transparency must be between zero and one")
        mode = effect.opaque_mode or collada.material.OPAQUE_MODE.A_ONE
        if isinstance(effect.transparent, collada.material.Map):
            texture = _texture(nodes, links, effect.transparent, part, dae, images)
            multiply = nodes.new("ShaderNodeMath")
            multiply.operation = "MULTIPLY"
            multiply.inputs[1].default_value = factor
            if mode == collada.material.OPAQUE_MODE.A_ONE:
                links.new(texture.outputs["Alpha"], multiply.inputs[0])
                alpha = multiply.outputs[0]
            elif mode == collada.material.OPAQUE_MODE.RGB_ZERO:
                inverse = nodes.new("ShaderNodeMath")
                inverse.operation = "SUBTRACT"
                inverse.inputs[0].default_value = 1
                luminance = nodes.new("ShaderNodeRGBToBW")
                links.new(texture.outputs["Color"], luminance.inputs["Color"])
                links.new(luminance.outputs["Val"], multiply.inputs[0])
                links.new(multiply.outputs[0], inverse.inputs[1])
                alpha = inverse.outputs[0]
            else:
                raise ValueError(f"Unsupported DAE transparency mode: {mode}")
            links.new(alpha, shader.inputs["Alpha"])
        else:
            transparent = _color(effect.transparent, "transparent")
            if mode == collada.material.OPAQUE_MODE.A_ONE:
                alpha = transparent[3] * factor
            elif mode == collada.material.OPAQUE_MODE.RGB_ZERO:
                alpha = 1 - float(np.dot(transparent[:3], LUMINANCE_WEIGHTS)) * factor
            else:
                raise ValueError(f"Unsupported DAE transparency mode: {mode}")
            if not 0 <= alpha <= 1:
                raise ValueError("DAE material opacity must be between zero and one")
            shader.inputs["Alpha"].default_value = alpha
    material.surface_render_method = "DITHERED"
    return material


def import_collada(path: str) -> list[bpy.types.Object]:
    dae = Path(path)
    parts = read_collada(dae)
    previous_objects = set(bpy.data.objects)
    previous_blocks = [
        (data, set(data))
        for data in (bpy.data.meshes, bpy.data.materials, bpy.data.images)
    ]
    selected = list(bpy.context.selected_objects)
    active = bpy.context.view_layer.objects.active
    materials = {}
    images = {}
    meshes = []
    completed = False
    try:
        bpy.ops.object.select_all(action="DESELECT")
        for part in parts:
            data = bpy.data.meshes.new(part.name)
            data.from_pydata(part.vertices.tolist(), part.edges, part.faces)
            if len(data.polygons) != len(part.faces):
                raise ValueError("Blender rejected DAE polygon data")
            if part.edges and len(data.edges) != len(part.edges):
                raise ValueError("Blender rejected DAE edge data")
            data.update()
            for uv_set, coordinates in zip(part.texcoord_sets, part.texcoords):
                layer = data.uv_layers.new(name=f"UV{uv_set}")
                layer.data.foreach_set("uv", coordinates.ravel())
            if part.normals is not None:
                data.polygons.foreach_set("use_smooth", [True] * len(data.polygons))
                data.normals_split_custom_set(part.normals.tolist())
            if part.material is not None:
                key = (
                    part.material.id,
                    tuple(sorted(part.material_inputs.items())),
                    part.double_sided,
                )
                if key not in materials:
                    materials[key] = build_material(part, dae, images)
                data.materials.append(materials[key])
            mesh = bpy.data.objects.new(part.name, data)
            bpy.context.collection.objects.link(mesh)
            mesh.select_set(True)
            meshes.append(mesh)
        bpy.context.view_layer.objects.active = meshes[-1]
        completed = True
    finally:
        if not completed:
            for obj in set(bpy.data.objects) - previous_objects:
                bpy.data.objects.remove(obj, do_unlink=True)
            for data, previous in previous_blocks:
                for block in set(data) - previous:
                    if block.users == 0:
                        data.remove(block)
            for obj in selected:
                obj.select_set(True)
            bpy.context.view_layer.objects.active = active
    return meshes
