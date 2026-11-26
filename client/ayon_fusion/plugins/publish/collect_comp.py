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
        folder_path = current_context["folder_path"]
        task_name = current_context["task_name"]

        collected_folder_path = context.data.get("folderPath", folder_path)
        collected_task_name = context.data.get("task", task_name)
        if (
            collected_folder_path != folder_path
            or collected_task_name != task_name
        ):
            self.log.warning(
                f"Collected context '{collected_folder_path}' >"
                f" '{collected_task_name}' does not match the context"
                f" '{folder_path}' > '{task_name}' of the published comp."
                " Using the context of the published comp."
            )
        context.data["folderPath"] = folder_path
        context.data["task"] = task_name
