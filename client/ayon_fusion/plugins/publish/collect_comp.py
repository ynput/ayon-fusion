import pyblish.api

from ayon_core.pipeline import PublishError, registered_host
from ayon_fusion.api import get_current_comp


class CollectCurrentCompFusion(pyblish.api.ContextPlugin):
    """Collect the comp the publisher collected its instances from

    This is the comp that was active when the publisher was refreshed, which
    is not necessarily the active comp anymore.
    """

    order = pyblish.api.CollectorOrder - 0.5
    label = "Collect Current Comp"
    hosts = ["fusion"]

    def process(self, context):
        """Collect all image sequence tools"""

        current_comp = self.get_create_context_comp(context)
        if not current_comp:
            raise PublishError("Must have active Fusion composition")

        context.data["currentComp"] = current_comp

        # Store path to current file
        filepath = current_comp.GetAttrs().get("COMPS_FileName", "")
        context.data["currentFile"] = filepath

        # Collect the context of this comp, because the host's current context
        # follows the active comp.
        host = registered_host()
        with host.current_comp(current_comp):
            current_context = host.get_current_context()
        context.data["folderPath"] = current_context["folder_path"]
        context.data["task"] = current_context["task_name"]

    @staticmethod
    def get_create_context_comp(context):
        # The workfile instance stores the comp it was collected from. Read
        # it from the create context, because pyblish instances only exist
        # for active instances and the workfile instance may be disabled.
        # Without a create context, e.g. when publishing headless, core
        # creates one from the active comp.
        create_context = context.data.get("create_context")
        if create_context is not None:
            for instance in create_context.instances:
                comp = instance.transient_data.get("comp")
                if comp is not None:
                    return comp
        return get_current_comp()
