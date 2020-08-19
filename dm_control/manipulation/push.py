# Copyright 2019 The dm_control Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or  implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ============================================================================

"""
A task where the goal is to use the hand to move a prop to the right side.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections

from dm_control import composer
from dm_control.composer import initializers
from dm_control.composer.observation import observable
from dm_control.composer.variation import distributions
from dm_control.entities import props
from dm_control.manipulation.shared import arenas
from dm_control.manipulation.shared import cameras
from dm_control.manipulation.shared import constants
from dm_control.manipulation.shared import observations
from dm_control.manipulation.shared import registry
from dm_control.manipulation.shared import robots
from dm_control.manipulation.shared import tags
from dm_control.manipulation.shared import workspaces
from dm_control.utils import rewards
import numpy as np


_PushWorkspace = collections.namedtuple(
    '_PushWorkspace', ['target_bbox', 'tcp_bbox', 'arm_offset'])

# Ensures that the props are not touching the table before settling.
_PROP_Z_OFFSET = 0.001

_DUPLO_WORKSPACE = _PushWorkspace(
    target_bbox=workspaces.BoundingBox(
        lower=(-0.1, -0.1, _PROP_Z_OFFSET),
        upper=(0.0, 0.1, _PROP_Z_OFFSET)), # start on left side
    tcp_bbox=workspaces.BoundingBox(
        lower=(-0.1, -0.1, 0.2),
        upper=(0.1, 0.1, 0.4)),
    arm_offset=robots.ARM_OFFSET)

_HAND_TARGET_RADIUS = 0.05
_TARGET_RADIUS = 0.025
_TARGET_PROP_XPOS = 0.1


class Push(composer.Task):
  """Bring the hand close to a target prop or site."""

  def __init__(
      self, arena, arm, hand, prop, obs_settings, workspace, control_timestep):
    """Initializes a new `Push` task.

    Args:
      arena: `composer.Entity` instance.
      arm: `robot_base.RobotArm` instance.
      hand: `robot_base.RobotHand` instance.
      prop: `composer.Entity` instance specifying the prop to push to, or None
        in which case the target is a fixed site whose position is specified by
        the workspace.
      obs_settings: `observations.ObservationSettings` instance.
      workspace: `_PushWorkspace` specifying the placement of the prop and TCP.
      control_timestep: Float specifying the control timestep in seconds.
    """
    self._arena = arena
    self._arm = arm
    self._hand = hand
    self._arm.attach(self._hand)
    self._arena.attach_offset(self._arm, offset=workspace.arm_offset)
    self.control_timestep = control_timestep
    self._tcp_initializer = initializers.ToolCenterPointInitializer(
        self._hand, self._arm,
        position=distributions.Uniform(*workspace.tcp_bbox),
        quaternion=workspaces.DOWN_QUATERNION)

    # Add custom camera observable.
    self._task_observables = cameras.add_camera_observables(
        arena, obs_settings, cameras.FRONT_CLOSE)

    target_pos_distribution = distributions.Uniform(*workspace.target_bbox)
    self._prop = prop
    # The prop itself is used to visualize the target location.
    self._make_target_site(parent_entity=prop, visible=False)
    self._target = self._arena.add_free_entity(prop)
    self._prop_placer = initializers.PropPlacer(
        props=[prop],
        position=target_pos_distribution,
        quaternion=workspaces.uniform_z_rotation,
        settle_physics=True)

    obs = observable.MJCFFeature('pos', self._target)
    obs.configure(**obs_settings.prop_pose._asdict())
    self._task_observables['target_position'] = obs

    # Add sites for visualizing the prop and target bounding boxes.
    workspaces.add_bbox_site(
        body=self.root_entity.mjcf_model.worldbody,
        lower=workspace.tcp_bbox.lower, upper=workspace.tcp_bbox.upper,
        rgba=constants.GREEN, name='tcp_spawn_area')
    workspaces.add_bbox_site(
        body=self.root_entity.mjcf_model.worldbody,
        lower=workspace.target_bbox.lower, upper=workspace.target_bbox.upper,
        rgba=constants.BLUE, name='target_spawn_area')

  def _make_target_site(self, parent_entity, visible):
    return workspaces.add_target_site(
        body=parent_entity.mjcf_model.worldbody,
        radius=_HAND_TARGET_RADIUS, visible=visible,
        rgba=constants.RED, name='target_site')

  @property
  def root_entity(self):
    return self._arena

  @property
  def arm(self):
    return self._arm

  @property
  def hand(self):
    return self._hand

  @property
  def task_observables(self):
    return self._task_observables

  def get_reward(self, physics):
    hand_pos = physics.bind(self._hand.tool_center_point).xpos
    target_pos = physics.bind(self._target).xpos
    distance = np.linalg.norm(hand_pos - target_pos)
    prop_x_distance = abs(target_pos[0] - _TARGET_PROP_XPOS)
    hand_reward = rewards.tolerance(
        distance, bounds=(0, _HAND_TARGET_RADIUS), margin=_HAND_TARGET_RADIUS*4, value_at_margin=0.2, sigmoid='long_tail')
    prop_reward = rewards.tolerance(
        prop_x_distance, bounds=(0, _TARGET_RADIUS), margin=_TARGET_RADIUS*4, value_at_margin=0.2, sigmoid='long_tail')
    return hand_reward + prop_reward

  def initialize_episode(self, physics, random_state):
    self._hand.set_grasp(physics, close_factors=random_state.uniform())
    self._tcp_initializer(physics, random_state)
    if self._prop:
      self._prop_placer(physics, random_state)
    else:
      physics.bind(self._target).pos = (
          self._target_placer(random_state=random_state))


def _push(obs_settings):
  """Configure and instantiate a `Push` task.

  Args:
    obs_settings: An `observations.ObservationSettings` instance.

  Returns:
    An instance of `push.Push`.
  """
  arena = arenas.Standard()
  arm = robots.make_arm(obs_settings=obs_settings)
  hand = robots.make_hand(obs_settings=obs_settings)
  workspace = _DUPLO_WORKSPACE
  prop = props.Duplo(observable_options=observations.make_options(
      obs_settings, observations.FREEPROP_OBSERVABLES))
  task = Push(arena=arena, arm=arm, hand=hand, prop=prop,
               obs_settings=obs_settings,
               workspace=workspace,
               control_timestep=constants.CONTROL_TIMESTEP)
  return task


@registry.add(tags.FEATURES, tags.EASY)
def push_duplo_features():
  return _push(obs_settings=observations.PERFECT_FEATURES)


@registry.add(tags.VISION, tags.EASY)
def push_duplo_vision():
  return _push(obs_settings=observations.VISION)


# @registry.add(tags.FEATURES, tags.EASY)
# def push_site_features():
#   return _push(obs_settings=observations.PERFECT_FEATURES, use_site=True)


# @registry.add(tags.VISION, tags.EASY)
# def push_site_vision():
#   return _push(obs_settings=observations.VISION, use_site=True)
