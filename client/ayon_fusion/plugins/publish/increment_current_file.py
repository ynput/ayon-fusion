import os

import pyblish.api

from ayon_core.lib import version_up
from ayon_core.host import IWorkfileHost
from ayon_core.host.interfaces import SaveWorkfileOptionalData
from ayon_core.pipeline.workfile import save_next_version
from ayon_core.pipeline import (
    OptionalPyblishPluginMixin,
    registered_host,
    PublishError,
)

from ayon_fusion.api import FusionHost


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
        if not comp:
            raise PublishError("Must have comp")

        # Fusion can have multiple compositions open at the same time, and
        # as a publish is running the user may switch to another comp
        # simultaneously. Hence, we need to ensure the active comp is the
        # one current publish session is for in the registered host.
        host: FusionHost = registered_host()
        with host.current_comp(comp):
            self.increment_workfile(context)

    def increment_workfile(self, context: pyblish.api.Context):
        """Increment the current workfile version using registered host."""
        current_filepath: str = context.data["currentFile"]

        current_filename = os.path.basename(current_filepath)
        save_next_version(
            description=(
                f"Incremented by publishing from {current_filename}"
            ),
            # Optimize the save by reducing needed queries for context
            prepared_data=SaveWorkfileOptionalData(
                project_entity=context.data["projectEntity"],
                project_settings=context.data["project_settings"],
                anatomy=context.data["anatomy"],
            )
        )
