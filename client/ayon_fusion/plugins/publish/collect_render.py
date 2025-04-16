import os
import attr
import pyblish.api

from ayon_core.pipeline import publish
from ayon_core.pipeline.publish import RenderInstance
from ayon_fusion.api.lib import get_frame_path, get_tool_resolution


@attr.s
class FusionRenderInstance(RenderInstance):
    # extend generic, composition name is needed
    fps = attr.ib(default=None)
    projectEntity = attr.ib(default=None)
    stagingDir = attr.ib(default=None)
    app_version = attr.ib(default=None)
    tool = attr.ib(default=None)
    workfileComp = attr.ib(default=None)
    publish_attributes = attr.ib(default={})
    frameStartHandle = attr.ib(default=None)
    frameEndHandle = attr.ib(default=None)


class CollectFusionRender(
    publish.AbstractCollectRender,
    publish.ColormanagedPyblishPluginMixin
):

    order = pyblish.api.CollectorOrder + 0.09
    label = "Collect Fusion Render"
    hosts = ["fusion"]

    def get_instances(self, context):

        comp = context.data.get("currentComp")
        comp_frame_format_prefs = comp.GetPrefs("Comp.FrameFormat")
        aspect_x = comp_frame_format_prefs["AspectX"]
        aspect_y = comp_frame_format_prefs["AspectY"]

        current_file = context.data["currentFile"]
        version = context.data.get("version")
        project_entity = context.data["projectEntity"]

        instances = []
        for inst in context:
            if not inst.data.get("active", True):
                continue

            product_type = inst.data["productType"]
            if product_type not in ["render", "image"]:
                continue

            # Get resolution from tool if we can
            tool = inst.data["transientData"]["tool"]
            try:
                width, height = get_tool_resolution(
                    tool, frame=inst.data["frameStart"])
            except ValueError:
                self.log.debug(
                    f"Unable to get resolution from tool: {tool}. "
                    "Falling back to comp frame format resolution "
                    "preferences.")
                width = comp_frame_format_prefs.get("Width")
                height = comp_frame_format_prefs.get("Height")

            instance_families = inst.data.get("families", [])
            product_name = inst.data["productName"]
            instance = FusionRenderInstance(
                tool=inst.data["transientData"]["tool"],
                workfileComp=comp,
                productType=product_type,
                family=product_type,
                families=instance_families,
                version=version,
                time="",
                source=current_file,
                label=inst.data["label"],
                productName=product_name,
                folderPath=inst.data["folderPath"],
                task=inst.data["task"],
                attachTo=False,
                setMembers='',
                publish=True,
                name=product_name,
                resolutionWidth=width,
                resolutionHeight=height,
                pixelAspect=aspect_x / aspect_y,
                tileRendering=False,
                tilesX=0,
                tilesY=0,
                review="review" in instance_families,
                frameStart=inst.data["frameStart"],
                frameEnd=inst.data["frameEnd"],
                handleStart=inst.data["handleStart"],
                handleEnd=inst.data["handleEnd"],
                frameStartHandle=inst.data["frameStartHandle"],
                frameEndHandle=inst.data["frameEndHandle"],
                frameStep=1,
                fps=comp_frame_format_prefs.get("Rate"),
                app_version=comp.GetApp().Version,
                publish_attributes=inst.data.get("publish_attributes", {}),

                # The source instance this render instance replaces
                source_instance=inst
            )

            render_target = inst.data["creator_attributes"]["render_target"]

            # Add render target family
            render_target_family = f"render.{render_target}"
            if render_target_family not in instance.families:
                instance.families.append(render_target_family)

            # Add render target specific data
            if render_target in {"local", "frames"}:
                instance.projectEntity = project_entity

            if render_target == "farm":
                fam = "render.farm"
                if fam not in instance.families:
                    instance.families.append(fam)
                instance.farm = True  # to skip integrate
                if "review" in instance.families:
                    # to skip ExtractReview locally
                    instance.families.remove("review")
                instance.deadline = inst.data.get("deadline")

            instances.append(instance)

        return instances

    def post_collecting_action(self):
        for instance in self._context:
            if "render.frames" in instance.data.get("families", []):
                # adding representation data to the instance
                self._update_for_frames(instance)

    def get_expected_files(self, render_instance):
        """
            Returns list of rendered files that should be created by
            Deadline. These are not published directly, they are source
            for later 'submit_publish_job'.

        Args:
            render_instance (RenderInstance): to pull anatomy and parts used
                in url

        Returns:
            (list) of absolute urls to rendered file
        """
        start = render_instance.frameStart - render_instance.handleStart
        end = render_instance.frameEnd + render_instance.handleEnd

        comp = render_instance.workfileComp
        path = comp.MapPath(
            render_instance.tool["Clip"][
                render_instance.workfileComp.TIME_UNDEFINED
            ]
        )
        output_dir = os.path.dirname(path)
        render_instance.outputDir = output_dir

        basename = os.path.basename(path)

        head, padding, ext = get_frame_path(basename)

        expected_files = []
        for frame in range(start, end + 1):
            expected_files.append(
                os.path.join(
                    output_dir,
                    f"{head}{str(frame).zfill(padding)}{ext}"
                )
            )

        return expected_files

    def _update_for_frames(self, instance):
        """Updating instance for render.frames family

        Adding representation data to the instance. Also setting
        colorspaceData to the representation based on file rules.
        """

        expected_files = instance.data["expectedFiles"]

        start = instance.data["frameStart"] - instance.data["handleStart"]

        path = expected_files[0]
        basename = os.path.basename(path)
        staging_dir = os.path.dirname(path)
        _, padding, ext = get_frame_path(basename)

        repre = {
            "name": ext[1:],
            "ext": ext[1:],
            "frameStart": f"%0{padding}d" % start,
            "files": [os.path.basename(f) for f in expected_files],
            "stagingDir": staging_dir,
        }

        self.set_representation_colorspace(
            representation=repre,
            context=instance.context,
        )

        # review representation
        if instance.data.get("review", False):
            repre["tags"] = ["review"]

        # add the repre to the instance
        if "representations" not in instance.data:
            instance.data["representations"] = []
        instance.data["representations"].append(repre)

        return instance
