import pyblish.api

from ayon_core.pipeline import (
    publish,
    OptionalPyblishPluginMixin,
    PublishValidationError,
)

from ayon_fusion.api.action import SelectInvalidAction


class ValidateBackgroundDepth(
    pyblish.api.ContextPlugin, OptionalPyblishPluginMixin
):
    """Validate if all Background tools are set to float32 bit

    This is a context plug-in because the Background tools are validated for
    the full comp instead of per instance, so it only needs to run once.
    """

    order = pyblish.api.ValidatorOrder
    label = "Validate Background Depth 32 bit"
    hosts = ["fusion"]
    families = ["render", "image"]
    optional = True

    actions = [SelectInvalidAction, publish.RepairContextAction]

    @classmethod
    def get_invalid(cls, context):
        comp = context.data.get("currentComp")
        assert comp, "Must have Comp object"

        backgrounds = comp.GetToolList(False, "Background").values()
        if not backgrounds:
            return []

        return [i for i in backgrounds if i.GetInput("Depth") != 4.0]

    def process(self, context):
        if not self.is_active(context.data):
            return

        invalid = self.get_invalid(context)
        if invalid:
            raise PublishValidationError(
                "Found {} Backgrounds tools which"
                " are not set to float32".format(len(invalid)),
                title=self.label,
            )

    @classmethod
    def repair(cls, context):
        comp = context.data.get("currentComp")
        invalid = cls.get_invalid(context)
        for i in invalid:
            i.SetInput("Depth", 4.0, comp.TIME_UNDEFINED)
