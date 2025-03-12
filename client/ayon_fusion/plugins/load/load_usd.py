from ayon_core.pipeline import load
from ayon_fusion.api import (
    imprint_container,
    get_current_comp,
    comp_lock_and_undo_chunk
)
from ayon_fusion.api.lib import get_fusion_module


class FusionLoadUSD(load.LoaderPlugin):
    """Load USD into Fusion

    Support for USD was added since Fusion 18.5
    """

    product_types = {"*"}
    representations = {"*"}
    extensions = {"usd", "usda", "usdz"}

    label = "Load USD"
    order = -10
    icon = "code-fork"
    color = "orange"

    tool_type = "uLoader"

    @classmethod
    def apply_settings(cls, project_settings):
        super().apply_settings(project_settings)
        if cls.enabled:
            # Enable only in Fusion 18.5+
            fusion = get_fusion_module()
            version = fusion.GetVersion()
            major = version[1]
            minor = version[2]
            is_usd_supported = (major, minor) >= (18, 5)
            cls.enabled = is_usd_supported

    def load(self, context, name, namespace, data):
        # Fallback to folder name when namespace is None
        if namespace is None:
            namespace = context["folder"]["name"]

        # Create the Loader with the filename path set
        comp = get_current_comp()
        with comp_lock_and_undo_chunk(comp, "Create tool"):
            path = self.filepath_from_context(context)

            args = (-32768, -32768)
            tool = comp.AddTool(self.tool_type, *args)
            tool["Filename"] = path

            imprint_container(tool,
                              name=name,
                              namespace=namespace,
                              context=context,
                              loader=self.__class__.__name__)

    def switch(self, container, context):
        self.update(container, context)

    def update(self, container, context):

        tool = container["_tool"]
        assert tool.ID == self.tool_type, f"Must be {self.tool_type}"
        comp = tool.Comp()

        path = self.filepath_from_context(context)
        with comp_lock_and_undo_chunk(comp, "Update tool"):
            tool["Filename"] = path

            # Update the imprinted representation
            tool.SetData("avalon.representation",
                         context["representation"]["id"])

    def remove(self, container):
        tool = container["_tool"]
        assert tool.ID == self.tool_type, f"Must be {self.tool_type}"
        comp = tool.Comp()

        with comp_lock_and_undo_chunk(comp, "Remove tool"):
            tool.Delete()
