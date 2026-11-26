import pyblish.api

from ayon_core.pipeline import PublishError, registered_host
from ayon_fusion.api import get_current_comp


class CollectCurrentCompFusion(pyblish.api.ContextPlugin):
    """Collect current comp and its context"""

    order = pyblish.api.CollectorOrder - 0.5
    label = "Collect Current Comp"
    hosts = ["fusion"]

    def process(self, context):
        """Collect all image sequence tools"""

        current_comp = get_current_comp()
        if not current_comp:
            raise PublishError("Must have active Fusion composition")

        context.data["currentComp"] = current_comp

        # Store path to current file
        filepath = current_comp.GetAttrs().get("COMPS_FileName", "")
        context.data["currentFile"] = filepath

        # Collect the context of this comp, because the host's current context
        # follows the active comp which may change while publishing.
        host = registered_host()
        with host.current_comp(current_comp):
            current_context = host.get_current_context()
        context.data["folderPath"] = current_context["folder_path"]
        context.data["task"] = current_context["task_name"]
