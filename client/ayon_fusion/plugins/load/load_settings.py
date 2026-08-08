from ayon_core.pipeline import load
from ayon_core.lib import BoolDef
from ayon_fusion.api import (
    get_current_comp,
    get_bmd_library,
    comp_lock_and_undo_chunk
)


class FusionLoadSetting(load.LoaderPlugin):
    """Load .setting into Fusion"""

    product_types = {"*"}
    representations = {"*"}
    extensions = {"setting"}

    label = "Load setting"
    order = -10
    icon = "code-fork"
    color = "orange"

    options = [
        BoolDef(
            "use_selection",
            label="Load to selected tools",
            tooltip="Load the .setting to the selected tools",
            default=False
        )
    ]

    def load(self, context, name=None, namespace=None, options=None):
        use_selection = options.get("use_selection", False)

        # Create the Loader with the filename path set
        path = self.filepath_from_context(context)
        comp = get_current_comp()

        if use_selection:
            # Apply to current selection
            selection = comp.GetToolList(True).values()
            if not selection:
                self.log.error("No selected tools to apply to.")
                return

            for tool in selection:
                self.log.info(f"Loading setting to {tool.Name}")
                tool.LoadSettings(path)
            return
        else:
            # Paste the contents of the .setting file
            bmd = get_bmd_library()
            contents = bmd.readfile(path)
            with comp_lock_and_undo_chunk(comp, "Load setting"):
                comp.Paste(contents)
