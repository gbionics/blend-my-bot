from pathlib import Path

import collada
import numpy as np


def make_collada(
    path: Path,
    *,
    up_axis="Z_UP",
    reflected=False,
    instances=True,
    concave=False,
    lines=False,
):
    document = collada.Collada()
    document.assetInfo.unitname = "millimeter"
    document.assetInfo.unitmeter = 0.001
    document.assetInfo.upaxis = up_axis
    positions = np.array(
        [[0, 0, 0], [1000, 0, 0], [1000, 1000, 0], [0, 1000, 0], [0, 0, 1000]],
        dtype=float,
    )
    if concave:
        positions[1:3] = [[300, 300, 0], [1000, 0, 0]]
    normals = np.array(
        [[1, 1, 1], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, -1, 0]], dtype=float
    )
    normals /= np.linalg.norm(normals, axis=1)[:, None]
    uv = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [0.5, 0.5]], dtype=float)
    sources = [
        collada.source.FloatSource("positions", positions, ("X", "Y", "Z")),
        collada.source.FloatSource("normals", normals, ("X", "Y", "Z")),
        collada.source.FloatSource("uv0", uv, ("S", "T")),
        collada.source.FloatSource("uv1", uv * 0.5 + 0.25, ("S", "T")),
    ]
    geometry = collada.geometry.Geometry(document, "geometry", "Fixture", sources)
    inputs = collada.source.InputList()
    inputs.addInput(0, "VERTEX", "#positions")
    inputs.addInput(1, "NORMAL", "#normals")
    inputs.addInput(2, "TEXCOORD", "#uv0", set="0")
    inputs.addInput(3, "TEXCOORD", "#uv1", set="1")
    geometry.primitives.append(
        geometry.createTriangleSet(np.repeat([0, 1, 4], 4), inputs, "solid")
    )
    geometry.primitives.append(
        geometry.createPolylist(np.repeat([0, 1, 2, 3], 4), [4], inputs, "textured")
    )
    if lines:
        line_inputs = collada.source.InputList()
        line_inputs.addInput(0, "VERTEX", "#positions")
        geometry.primitives.append(
            geometry.createLineSet(np.array([0, 1]), line_inputs, None)
        )
    document.geometries.append(geometry)
    image = collada.material.CImage("image", "tex%20with%20spaces.png")
    document.images.append(image)
    surface = collada.material.Surface("surface", image)
    sampler = collada.material.Sampler2D("sampler", surface)
    colored = collada.material.Effect(
        "colored",
        [],
        "phong",
        diffuse=(0.25, 0.5, 0.75, 0.8),
        emission=(0.1, 0.2, 0, 1),
        specular=(0.2, 0.2, 0.2, 1),
        shininess=50.0,
        transparent=(0, 0, 0, 0.5),
        transparency=0.75,
        opaque_mode=collada.material.OPAQUE_MODE.A_ONE,
        double_sided=True,
    )
    textured = collada.material.Effect(
        "textured",
        [surface, sampler],
        "lambert",
        diffuse=collada.material.Map(sampler, "CHANNEL"),
    )
    document.effects.extend([colored, textured])
    solid = collada.material.Material("solid", "Solid", colored)
    texture = collada.material.Material("textured", "Textured", textured)
    document.materials.extend([solid, texture])
    materials = [
        collada.scene.MaterialNode("solid", solid, []),
        collada.scene.MaterialNode("textured", texture, [("CHANNEL", "TEXCOORD", "1")]),
    ]
    child = collada.scene.Node(
        "scaled",
        children=[collada.scene.GeometryNode(geometry, materials)],
        transforms=[collada.scene.ScaleTransform(-2 if reflected else 2, 3, 4)],
    )
    document.nodes.append(child)
    children = [collada.scene.NodeNode(child)]
    if instances:
        children.append(
            collada.scene.Node(
                "instance",
                children=[collada.scene.NodeNode(child)],
                transforms=[collada.scene.TranslateTransform(0, 0, 2000)],
            )
        )
    parent = collada.scene.Node(
        "parent",
        children=children,
        transforms=[
            collada.scene.TranslateTransform(10, 20, 30),
            collada.scene.RotateTransform(0, 0, 1, 90),
        ],
    )
    scene = collada.scene.Scene("scene", [parent])
    document.scenes.append(scene)
    document.scene = scene
    with path.open("wb") as stream:
        document.write(stream)
    return document
