from dataclasses import dataclass
from typing import Dict

import idyntree.bindings as idyntree
import numpy as np

from .link import Link


@dataclass
class BlenderModel:
    """Class containing the model of the robot in blender"""

    name: str
    links: Dict[str, Link]
    kindyn: idyntree.KinDynComputations
    model_geometry: idyntree.Model

    def __post_init__(self):
        self.zero_base_velocity = np.zeros(6)
        self.zero_joint_velocity = np.zeros(self.kindyn.getNrOfDegreesOfFreedom())
        self.zero_gravity = np.zeros(3)

    def update(self, w_H_b: np.ndarray, s: np.ndarray) -> None:
        """Update the model in blender with the given state

        Args:
            w_H_b (np.ndarray): Homogeneous transformation from world to base
            s (np.ndarray): Joint positions
        """

        self._set_robot_state(w_H_b, s)
        for link in self.links.values():
            w_H_l = self.kindyn.getWorldTransform(link.name)
            l_H_g = link.link_H_geometry
            w_H_g = w_H_l * l_H_g
            link.mesh.location = w_H_g.getPosition().toNumPy().flatten()
            link.mesh.rotation_quaternion = w_H_g.getRotation().asQuaternion().toNumPy()
            link.mesh.keyframe_insert(data_path="location", index=-1)
            link.mesh.keyframe_insert(data_path="rotation_quaternion", index=-1)

    def _set_robot_state(self, w_H_b, s):
        """Set the robot state in the kindyn model

        Args:
            w_H_b (np.ndarray): Homogeneous transformation from world to base
            s (np.ndarray): Joint positions
        """

        self.kindyn.setRobotState(
            w_H_b,
            s,
            self.zero_base_velocity,
            self.zero_joint_velocity,
            self.zero_gravity,
        )
