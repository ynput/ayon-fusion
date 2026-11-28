import pyblish.api

from ayon_core.pipeline import PublishValidationError
from ayon_fusion.api import get_current_comp


class ValidateCompActive(pyblish.api.ContextPlugin):
    """Validate the published comp is the active comp.

    The publisher collects the instances from the comp that was active when
    it was refreshed. Some publish plugins read the active comp instead, like
    the ones collecting and validating the loaded containers.
    """

    order = pyblish.api.ValidatorOrder
    label = "Validate Comp Is Active"
    hosts = ["fusion"]

    def process(self, context):
        comp = context.data["currentComp"]
        active_comp = get_current_comp()
        # Remote objects of the same comp do not compare equal, but their
        # string representations do.
        if active_comp is not None and str(active_comp) == str(comp):
            return

        name = comp.GetAttrs()["COMPS_Name"]
        raise PublishValidationError(
            f"The publisher was refreshed for comp '{name}', but another"
            " comp is active now. Activate the comp you want to publish and"
            " refresh the publisher.",
            title=self.label,
        )
