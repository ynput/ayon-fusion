import pyblish.api

from ayon_core.pipeline import OptionalPyblishPluginMixin
from ayon_core.lib import version_up
from ayon_fusion.api import FusionHost
from ayon_core.pipeline import registered_host


class FusionIncrementCurrentFile(
    pyblish.api.ContextPlugin, OptionalPyblishPluginMixin
):
    """Increment the current file.

    Saves the current file with an increased version number."""

    label = "Increment workfile version"
    order = pyblish.api.IntegratorOrder + 9.0
    hosts = ["fusion"]
    optional = True

    def process(self, context):
        if not self.is_active(context.data):
            return

        comp = context.data.get("currentComp")
        assert comp, "Must have comp"

        current_filepath = context.data["currentFile"]
        new_filepath = version_up(current_filepath)

        host: FusionHost = registered_host()
        with host.current_comp(comp):
            # Fusion can have multiple compositions open at the same time, and
            # as a publish is running the user may switch to another comp
            # simultaneously. Hence, we need to ensure the active comp is the
            # one current publish session is for.
            if hasattr(host, "save_workfile_with_context"):
                from ayon_core.host.interfaces import SaveWorkfileOptionalData
                host.save_workfile_with_context(
                    filepath=new_filepath,
                    folder_entity=context.data["folderEntity"],
                    task_entity=context.data["taskEntity"],
                    description="Incremented by publishing.",
                    # Optimize the save by reducing needed queries for context
                    prepared_data=SaveWorkfileOptionalData(
                        project_entity=context.data["projectEntity"],
                        project_settings=context.data["project_settings"],
                        anatomy=context.data["anatomy"],
                    )
                )
            else:
                # Backwards compatibility before:
                # https://github.com/ynput/ayon-core/pull/1275
                host.save_workfile(new_filepath)