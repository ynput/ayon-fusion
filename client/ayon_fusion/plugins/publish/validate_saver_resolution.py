import pyblish.api
from ayon_core.pipeline import (
    PublishValidationError,
    OptionalPyblishPluginMixin,
)

from ayon_fusion.api.action import SelectInvalidAction
from ayon_fusion.api.lib import get_tool_resolution


class ValidateSaverResolution(
    pyblish.api.InstancePlugin, OptionalPyblishPluginMixin
):
    """Validate that the saver input resolution matches the folder resolution"""

    order = pyblish.api.ValidatorOrder
    label = "Validate Folder Resolution"
    families = ["render", "image"]
    hosts = ["fusion"]
    optional = True
    actions = [SelectInvalidAction]

    def process(self, instance):
        if not self.is_active(instance.data):
            return

        resolution = self.get_resolution(instance)
        expected_resolution = self.get_expected_resolution(instance)
        if resolution != expected_resolution:
            raise PublishValidationError(
                "The input's resolution does not match "
                "the folder's resolution {}x{}.\n\n"
                "The input's resolution is {}x{}.".format(
                    expected_resolution[0], expected_resolution[1],
                    resolution[0], resolution[1]
                )
            )

    @classmethod
    def get_invalid(cls, instance):
        saver = instance.data["tool"]
        try:
            resolution = cls.get_resolution(instance)
        except PublishValidationError:
            resolution = None
        expected_resolution = cls.get_expected_resolution(instance)
        if resolution != expected_resolution:
            return [saver]

    @classmethod
    def get_resolution(cls, instance):
        saver = instance.data["tool"]
        first_frame = instance.data["frameStartHandle"]

        try:
            return get_tool_resolution(saver, frame=first_frame)
        except ValueError:
            raise PublishValidationError(
                "Cannot get resolution info for frame '{}'.\n\n "
                "Please check that saver has connected input.".format(
                    first_frame
                )
            )

    @classmethod
    def get_expected_resolution(cls, instance):

        entity = instance.data.get("taskEntity")
        if not entity:
            cls.log.debug(
                "Using folder entity resolution for validation because "
                f"task entity not found for instance: {instance}")
            entity = instance.data["folderEntity"]

        attributes = entity["attrib"]
        return attributes["resolutionWidth"], attributes["resolutionHeight"]
