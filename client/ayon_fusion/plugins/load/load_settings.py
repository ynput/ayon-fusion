from ayon_core.pipeline import load
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

    def load(self, context, name=None, namespace=None, options=None):
        # TODO: Loading a Silhouette-published roto track points `.setting`
        #  file only applies correctly when loaded directly to a Roto node.
        #  Preferably the user shouldn't need to care and we may need to find
        #  out how we could automate that, and/or be able to tell the user
        #  what selection a particular product needs, or  maybe target the
        #  product type explicitly so that it creates a Polygon tool if none
        #  are selected - but it'd make this load logic specific to that
        #  product type instead of "load any .setting file".
        path = self.filepath_from_context(context)

        # Create the Loader with the filename path set
        comp = get_current_comp()

        # Apply to selection if anything is selected
        selection = comp.GetToolList(True).values()
        if selection:
            # Apply to current selection
            for tool in selection:
                tool.LoadSettings(path)
        else:
            # Try straight up pasting the .setting file
            bmd = get_bmd_library()
            bmd.readfile(path)
            with comp_lock_and_undo_chunk(comp, "Load setting"):
                comp.Paste()
