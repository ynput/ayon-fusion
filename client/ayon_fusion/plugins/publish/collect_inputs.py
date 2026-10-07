import pyblish.api

from ayon_core.pipeline import registered_host


def collect_input_containers(tools, containers=None):
    """Collect containers that contain any of the node in `nodes`.

    This will return any loaded Avalon container that contains at least one of
    the nodes. As such, the Avalon container is an input for it. Or in short,
    there are member nodes of that container.

    Args:
        tools (list): The Fusion tools to find the containers for.
        containers (Optional[list]): The containers to consider. When not
            provided the containers are listed from the registered host. Pass
            these to avoid listing the comp's containers on each call.

    Returns:
        list: Input avalon containers

    """

    # Lookup by node ids
    lookup = frozenset([tool.Name for tool in tools])

    if containers is None:
        host = registered_host()
        containers = list(host.ls())

    # We currently assume no "groups" as containers but just single tools
    # like a single "Loader" operator. As such we just check whether the
    # Loader is part of the processing queue.
    # The container's `objectName` is the tool's name so we avoid another
    # query of the name from the tool.
    return [
        container for container in containers
        if container["objectName"] in lookup
    ]


def iter_upstream(tool):
    """Yields all upstream inputs for the current tool.

    Yields:
        tool: The input tools.

    """

    def get_connected_input_tools(tool):
        """Helper function that returns connected input tools for a tool."""
        inputs = []

        # Filter only to actual types that will have sensible upstream
        # connections. So we ignore just "Number" inputs as they can be
        # many to iterate, slowing things down quite a bit - and in practice
        # they don't have upstream connections.
        VALID_INPUT_TYPES = ['Image', 'Particles', 'Mask', 'DataType3D']
        for type_ in VALID_INPUT_TYPES:
            for input_ in tool.GetInputList(type_).values():
                output = input_.GetConnectedOutput()
                if output:
                    input_tool = output.GetTool()
                    inputs.append(input_tool)

        return inputs

    # We keep track of which node names we have processed so far, to ensure we
    # don't process the same hierarchy again. We are not pushing the tool
    # itself into the set as that doesn't correctly recognize the same tool.
    # Since tool names are unique in a comp in Fusion we rely on that.
    collected = set()

    def get_uncollected(tools):
        """Return the tools not collected yet and mark them as collected."""
        uncollected = []
        for input_tool in tools:
            # Each query of the tool name goes through to Fusion so we make
            # sure to query it only once per tool
            name = input_tool.Name
            if name in collected:
                continue
            collected.add(name)
            uncollected.append(input_tool)
        return uncollected

    # Initialize process queue with the node's inputs itself
    queue = get_uncollected(get_connected_input_tools(tool))

    # Traverse upstream references for all nodes and yield them as we
    # process the queue.
    while queue:
        upstream_tool = queue.pop()
        yield upstream_tool

        # Find upstream tools that are not collected yet.
        upstream_inputs = get_connected_input_tools(upstream_tool)
        queue.extend(get_uncollected(upstream_inputs))


class CollectUpstreamInputs(pyblish.api.InstancePlugin):
    """Collect source input containers used for this publish.

    This will include `inputs` data of which loaded publishes were used in the
    generation of this publish. This leaves an upstream trace to what was used
    as input.

    """

    label = "Collect Inputs"
    order = pyblish.api.CollectorOrder + 0.2
    hosts = ["fusion"]
    families = ["render", "image"]

    containers_cache_key = "fusionContainers"

    def process(self, instance):

        # Get all upstream and include itself
        tool = instance.data.get("tool")
        if tool is None:
            self.log.debug("No tool found in instance, skipping..")
            return

        nodes = list(iter_upstream(tool))
        nodes.append(tool)

        # Collect containers for the given set of nodes
        containers = collect_input_containers(
            nodes, containers=self.get_containers(instance.context)
        )

        inputs = [c["representation"] for c in containers]
        instance.data["inputRepresentations"] = inputs
        self.log.debug("Collected inputs: %s" % inputs)

    def get_containers(self, context):
        """Return the comp's containers, cached for the publish context.

        Listing the containers queries the data of each tool in the comp so we
        only do it once instead of for each instance.
        """
        containers = context.data.get(self.containers_cache_key)
        if containers is None:
            host = registered_host()
            containers = list(host.ls())
            context.data[self.containers_cache_key] = containers
        return containers
