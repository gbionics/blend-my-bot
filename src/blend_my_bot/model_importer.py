from dataclasses import dataclass
from typing import Dict, List, Optional

import bpy
import idyntree.bindings as idyntree
import numpy as np

from .blender_model import BlenderModel
from .collada_importer import import_collada
from .link import Link


@dataclass
class ModelImporter:
    @staticmethod
    def build_model(
        model_name: str,
        urdf_path: str,
        joints_list: Optional[List[str]] = None,
        collection: Optional[bpy.types.Collection] = None,
    ) -> BlenderModel:
        """Build the model of the robot in blender

        Args:
            model_name (str): Name of the model
            urdf_path (str): Path to the urdf file
            joints_list (List, optional): List of joints to import. Defaults to None.
            collection (bpy.types.Collection, optional): Import into a separate
                collection instead of reusing existing named meshes.

        Returns:
            BlenderModel: Model of the robot in blender
        """

        kindyn = ModelImporter.build_kindyn(urdf_path, joints_list)
        model_loader_geometry = idyntree.ModelLoader()
        if not model_loader_geometry.loadModelFromFile(urdf_path):
            raise ValueError(f"Cannot load robot geometry from {urdf_path}")
        model_geometry = model_loader_geometry.model().copy()
        links = ModelImporter.import_links(
            model_name, model_geometry, kindyn, collection
        )
        return BlenderModel(
            name=model_name, links=links, kindyn=kindyn, model_geometry=model_geometry
        )

    @staticmethod
    def build_kindyn(
        urdf_path: str, joints_list: Optional[List[str]] = None
    ) -> idyntree.KinDynComputations:
        """Build the kindyn model

        Args:
            urdf_path (str): Path to the urdf file
            joints_list (List, optional): List of joints to import. Defaults to None.

        Returns:
            idyntree.KinDynComputations: Kindyn model
        """

        model_loader = idyntree.ModelLoader()
        if joints_list is None:
            loaded = model_loader.loadModelFromFile(urdf_path)
        else:
            loaded = model_loader.loadReducedModelFromFile(urdf_path, joints_list)
        if not loaded:
            raise ValueError(f"Cannot load robot model from {urdf_path}")
        model = model_loader.model()
        kindyn = idyntree.KinDynComputations()
        if not kindyn.loadRobotModel(model):
            raise ValueError(f"Cannot initialize robot kinematics from {urdf_path}")
        return kindyn

    @staticmethod
    def import_links(
        model_name: str,
        model_geometry: idyntree.Model,
        kindyn: idyntree.KinDynComputations,
        collection: Optional[bpy.types.Collection] = None,
    ) -> Dict[str, Link]:
        """Import the links of the robot in blender

        Args:
            model_name (str): Name of the model
            model_geometry (idyntree.Model): Model of the robot
            kindyn (idyntree.KinDynComputations): Kindyn model

        Returns:
            Dict[str, Link]: Visual parts mapped to their robot links
        """

        visuals = model_geometry.visualSolidShapes().getLinkSolidShapes()
        links = {}
        existing_objects = bpy.context.scene.objects.keys()
        # set zero position
        kindyn.setRobotState(
            np.eye(4),
            np.zeros(kindyn.getNrOfDegreesOfFreedom()),
            np.zeros(6),
            np.zeros(kindyn.getNrOfDegreesOfFreedom()),
            np.zeros(3),
        )
        for link_id in range(model_geometry.getNrOfLinks()):
            link_name = model_geometry.getLinkName(link_id)
            if visuals[link_id] == ():  # no visual
                continue
            for visual_index, link_visual in enumerate(visuals[link_id]):
                if not link_visual.isExternalMesh():
                    raise ValueError(
                        f"Link '{link_name}' has an unsupported visual primitive; "
                        "use OBJ, STL or DAE meshes"
                    )
                mesh_path = (
                    link_visual.asExternalMesh().getFileLocationOnLocalFileSystem()
                )
                print(f"mesh_path {mesh_path}")
                suffix = "" if visual_index == 0 else f"_{visual_index}"
                mesh_name = f"{model_name}_{link_name}_mesh{suffix}"
                existing = bpy.data.objects.get(mesh_name)
                reuse_existing = (
                    collection is None
                    and existing is not None
                    and mesh_name in existing_objects
                )
                if reuse_existing:
                    print(f"Using existing mesh {mesh_name}")
                    mesh = bpy.data.objects[mesh_name]
                elif mesh_path.lower().endswith(".obj"):
                    print(f"Importing {mesh_path}")
                    result = bpy.ops.wm.obj_import(filepath=mesh_path)
                    if result != {"FINISHED"} or not bpy.context.selected_objects:
                        raise ValueError(f"No mesh objects imported from {mesh_path}")
                elif mesh_path.lower().endswith(".stl"):
                    print(f"Importing {mesh_path}")
                    result = bpy.ops.wm.stl_import(filepath=mesh_path)
                    if result != {"FINISHED"} or not bpy.context.selected_objects:
                        raise ValueError(f"No mesh objects imported from {mesh_path}")
                elif mesh_path.lower().endswith(".dae"):
                    import_collada(mesh_path)
                else:
                    raise ValueError(
                        f"Extension {mesh_path.split('.')[-1]} not supported"
                    )
                l_H_g = link_visual.getLink_H_geometry()
                # set link pose to rest position
                w_H_l = kindyn.getWorldTransform(link_name)
                w_H_g = w_H_l * l_H_g
                imported_meshes = (
                    [mesh] if reuse_existing else list(bpy.context.selected_objects)
                )
                if reuse_existing:
                    part_index = 1
                    while f"{mesh_name}_part_{part_index}" in existing_objects:
                        imported_meshes.append(
                            bpy.data.objects[f"{mesh_name}_part_{part_index}"]
                        )
                        part_index += 1
                for part_index, mesh in enumerate(imported_meshes):
                    part_suffix = "" if part_index == 0 else f"_part_{part_index}"
                    mesh.name = mesh_name + part_suffix
                    mesh.scale = (
                        link_visual.asExternalMesh().getScale().toNumPy().flatten()
                    )
                    mesh.rotation_mode = "QUATERNION"
                    mesh.location = w_H_g.getPosition().toNumPy().flatten()
                    mesh.rotation_quaternion = (
                        w_H_g.getRotation().asQuaternion().toNumPy()
                    )
                    if collection is not None:
                        for previous_collection in list(mesh.users_collection):
                            previous_collection.objects.unlink(mesh)
                        collection.objects.link(mesh)
                    key = link_name + suffix + part_suffix
                    links[key] = Link(link_name, mesh, l_H_g)
                    if collection is not None:
                        mesh["blend_my_bot_link"] = link_name
                        mesh["blend_my_bot_visual_key"] = key
                        mesh["blend_my_bot_link_H_geometry"] = (
                            l_H_g.asHomogeneousTransform().toNumPy().ravel().tolist()
                        )
        return links
