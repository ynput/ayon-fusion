import os
import sys
import re
import contextlib

from ayon_core.lib import Logger, BoolDef, UILabelDef
from ayon_core.style import load_stylesheet
from ayon_core.pipeline import registered_host
from ayon_core.pipeline.create import CreateContext
from ayon_core.pipeline.context_tools import (
    get_current_folder_path,
    get_current_task_entity
)

self = sys.modules[__name__]
self._project = None


def update_frame_range(start, end, comp=None, set_render_range=True,
                       handle_start=0, handle_end=0):
    """Set Fusion comp's start and end frame range

    Args:
        start (float, int): start frame
        end (float, int): end frame
        comp (object, Optional): comp object from fusion
        set_render_range (bool, Optional): When True this will also set the
            composition's render start and end frame.
        handle_start (float, int, Optional): frame handles before start frame
        handle_end (float, int, Optional): frame handles after end frame

    Returns:
        None

    """

    if not comp:
        comp = get_current_comp()

    # Convert any potential none type to zero
    handle_start = handle_start or 0
    handle_end = handle_end or 0

    attrs = {
        "COMPN_GlobalStart": start - handle_start,
        "COMPN_GlobalEnd": end + handle_end
    }

    # set frame range
    if set_render_range:
        attrs.update({
            "COMPN_RenderStart": start,
            "COMPN_RenderEnd": end
        })

    with comp_lock_and_undo_chunk(comp):
        comp.SetAttrs(attrs)


def set_current_context_framerange(task_entity=None):
    """Set Comp's frame range based on current task."""
    if task_entity is None:
        task_entity = get_current_task_entity(
            fields={"attrib.frameStart",
                    "attrib.frameEnd",
                    "attrib.handleStart",
                    "attrib.handleEnd"})

    task_attributes = task_entity["attrib"]
    start = task_attributes["frameStart"]
    end = task_attributes["frameEnd"]
    handle_start = task_attributes["handleStart"]
    handle_end = task_attributes["handleEnd"]
    update_frame_range(start, end, set_render_range=True,
                       handle_start=handle_start,
                       handle_end=handle_end)


def set_current_context_fps(task_entity=None):
    """Set Comp's frame rate (FPS) to based on current task"""
    if task_entity is None:
        task_entity = get_current_task_entity(fields={"attrib.fps"})

    fps = float(task_entity["attrib"].get("fps", 24.0))
    comp = get_current_comp()
    comp.SetPrefs({
        "Comp.FrameFormat.Rate": fps,
    })


def set_current_context_resolution(task_entity=None):
    """Set Comp's resolution width x height default based on current task"""
    if task_entity is None:
        task_entity = get_current_task_entity(
            fields={"attrib.resolutionWidth", "attrib.resolutionHeight"})

    task_attributes = task_entity["attrib"]
    width = task_attributes["resolutionWidth"]
    height = task_attributes["resolutionHeight"]
    comp = get_current_comp()

    print("Setting comp frame format resolution to {}x{}".format(width,
                                                                 height))
    comp.SetPrefs({
        "Comp.FrameFormat.Width": width,
        "Comp.FrameFormat.Height": height,
    })


def validate_comp_prefs(comp=None, force_repair=False):
    """Validate current comp defaults with task settings.

    Validates fps, resolutionWidth, resolutionHeight, aspectRatio.

    This does *not* validate frameStart, frameEnd, handleStart and handleEnd.
    """

    if comp is None:
        comp = get_current_comp()

    log = Logger.get_logger("validate_comp_prefs")

    fields = {
        "name",
        "attrib.fps",
        "attrib.resolutionWidth",
        "attrib.resolutionHeight",
        "attrib.pixelAspect",
    }
    task_entity = get_current_task_entity(fields=fields)
    folder_path = get_current_folder_path()
    context_path = "{} > {}".format(folder_path, task_entity["name"])

    task_attributes = task_entity["attrib"]

    comp_frame_format_prefs = comp.GetPrefs("Comp.FrameFormat")

    # Pixel aspect ratio in Fusion is set as AspectX and AspectY so we convert
    # the data to something that is more sensible to Fusion
    task_attributes["pixelAspectX"] = task_attributes.pop("pixelAspect")
    task_attributes["pixelAspectY"] = 1.0

    validations = [
        ("fps", "Rate", "FPS"),
        ("resolutionWidth", "Width", "Resolution Width"),
        ("resolutionHeight", "Height", "Resolution Height"),
        ("pixelAspectX", "AspectX", "Pixel Aspect Ratio X"),
        ("pixelAspectY", "AspectY", "Pixel Aspect Ratio Y")
    ]

    invalid = []
    for key, comp_key, label in validations:
        task_value = task_attributes[key]
        comp_value = comp_frame_format_prefs.get(comp_key)
        if task_value != comp_value:
            invalid_msg = "{} {} should be {}".format(label,
                                                      comp_value,
                                                      task_value)
            invalid.append(invalid_msg)

            if not force_repair:
                # Do not log warning if we force repair anyway
                log.warning(
                    "Comp {pref} {value} does not match "
                    "{context_path} {pref} {task_value}".format(
                        pref=label,
                        value=comp_value,
                        context_path=context_path,
                        task_value=task_value)
                )

    if invalid:

        def _on_repair():
            attributes = dict()
            for key, comp_key, _label in validations:
                value = task_attributes[key]
                comp_key_full = "Comp.FrameFormat.{}".format(comp_key)
                attributes[comp_key_full] = value
            comp.SetPrefs(attributes)

        if force_repair:
            log.info("Applying default Comp preferences..")
            _on_repair()
            return

        from . import menu
        from ayon_core.tools.utils import SimplePopup
        dialog = SimplePopup(parent=menu.menu)
        dialog.setWindowTitle("Fusion comp has invalid configuration")

        msg = "Comp preferences mismatches '{}'".format(context_path)
        msg += "\n" + "\n".join(invalid)
        dialog.set_message(msg)
        dialog.set_button_text("Repair")
        dialog.on_clicked.connect(_on_repair)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.setStyleSheet(load_stylesheet())


@contextlib.contextmanager
def maintained_selection(comp=None):
    """Reset comp selection from before the context after the context"""
    if comp is None:
        comp = get_current_comp()

    previous_selection = comp.GetToolList(True).values()
    try:
        yield
    finally:
        flow = comp.CurrentFrame.FlowView
        flow.Select()  # No args equals clearing selection
        if previous_selection:
            for tool in previous_selection:
                flow.Select(tool, True)


@contextlib.contextmanager
def maintained_comp_range(comp=None,
                          global_start=True,
                          global_end=True,
                          render_start=True,
                          render_end=True):
    """Reset comp frame ranges from before the context after the context"""
    if comp is None:
        comp = get_current_comp()

    comp_attrs = comp.GetAttrs()
    preserve_attrs = {}
    if global_start:
        preserve_attrs["COMPN_GlobalStart"] = comp_attrs["COMPN_GlobalStart"]
    if global_end:
        preserve_attrs["COMPN_GlobalEnd"] = comp_attrs["COMPN_GlobalEnd"]
    if render_start:
        preserve_attrs["COMPN_RenderStart"] = comp_attrs["COMPN_RenderStart"]
    if render_end:
        preserve_attrs["COMPN_RenderEnd"] = comp_attrs["COMPN_RenderEnd"]

    try:
        yield
    finally:
        comp.SetAttrs(preserve_attrs)


def get_frame_path(path):
    """Get filename for the Fusion Saver with padded number as '#'

    >>> get_frame_path("C:/test.exr")
    ('C:/test', 4, '.exr')

    >>> get_frame_path("filename.00.tif")
    ('filename.', 2, '.tif')

    >>> get_frame_path("foobar35.tif")
    ('foobar', 2, '.tif')

    Args:
        path (str): The path to render to.

    Returns:
        tuple: head, padding, tail (extension)

    """
    filename, ext = os.path.splitext(path)

    # Find a final number group
    match = re.match('.*?([0-9]+)$', filename)
    if match:
        padding = len(match.group(1))
        # remove number from end since fusion
        # will swap it with the frame number
        filename = filename[:-padding]
    else:
        padding = 4  # default Fusion padding

    return filename, padding, ext


def get_fusion_module():
    """Get current Fusion instance"""
    fusion = getattr(sys.modules["__main__"], "fusion", None)
    return fusion


def get_bmd_library():
    """Get bmd library"""
    bmd = getattr(sys.modules["__main__"], "bmd", None)
    return bmd


def get_current_comp():
    """Get current comp in this session"""
    fusion = get_fusion_module()
    if fusion is not None:
        comp = fusion.CurrentComp
        return comp


@contextlib.contextmanager
def comp_lock_and_undo_chunk(
    comp,
    undo_queue_name="Script CMD",
    keep_undo=True,
):
    """Lock comp and open an undo chunk during the context"""
    try:
        comp.Lock()
        comp.StartUndo(undo_queue_name)
        yield
    finally:
        comp.Unlock()
        comp.EndUndo(keep_undo)


def update_content_on_context_change():
    """Update all Creator instances to current asset"""
    host = registered_host()
    context = host.get_current_context()

    folder_path = context["folder_path"]
    task = context["task_name"]

    create_context = CreateContext(host, reset=True)

    for instance in create_context.instances:
        instance_folder_path = instance.get("folderPath")
        if instance_folder_path and instance_folder_path != folder_path:
            instance["folderPath"] = folder_path
        instance_task = instance.get("task")
        if instance_task and instance_task != task:
            instance["task"] = task

    create_context.save_changes()


def prompt_reset_context():
    """Prompt the user what context settings to reset.
    This prompt is used on saving to a different task to allow the scene to
    get matched to the new context.
    """
    # TODO: Cleanup this prototyped mess of imports and odd dialog
    from ayon_core.tools.attribute_defs.dialog import (
        AttributeDefinitionsDialog
    )
    from qtpy import QtCore

    definitions = [
        UILabelDef(
            label=(
                "You are saving your workfile into a different folder or task."
                "\n\n"
                "Would you like to update some settings to the new context?\n"
            )
        ),
        BoolDef(
            "fps", 
            label="FPS", 
            tooltip="Reset Comp FPS",
            default=True
        ),
        BoolDef(
            "frame_range", 
            label="Frame Range",
            tooltip="Reset Comp start and end frame ranges",
            default=True
        ),
        BoolDef(
            "resolution", 
            label="Comp Resolution", 
            tooltip="Reset Comp resolution",
            default=True
        ),
        BoolDef(
            "instances", 
            label="Publish instances", 
            tooltip="Update all publish instance's folder and task to match "
                    "the new folder and task", 
            default=True
        ),
    ]

    dialog = AttributeDefinitionsDialog(definitions)
    dialog.setWindowFlags(
        dialog.windowFlags() | QtCore.Qt.WindowStaysOnTopHint
    )
    dialog.setWindowTitle("Saving to different context.")
    dialog.setStyleSheet(load_stylesheet())
    if not dialog.exec_():
        return None

    options = dialog.get_values()
    task_entity = get_current_task_entity()
    if options["frame_range"]:
        set_current_context_framerange(task_entity)

    if options["fps"]:
        set_current_context_fps(task_entity)

    if options["resolution"]:
        set_current_context_resolution(task_entity)

    if options["instances"]:
        update_content_on_context_change()

    dialog.deleteLater()
    
    
@contextlib.contextmanager
def temp_expression(attribute, frame, expression):
    """Temporarily set an expression on an attribute during context"""
    # Save old comment
    old_comment = ""
    has_expression = False

    if attribute[frame] not in ["", None]:
        if attribute.GetExpression() is not None:
            has_expression = True
            old_comment = attribute.GetExpression()
            attribute.SetExpression(None)
        else:
            old_comment = attribute[frame]
            attribute[frame] = ""

    try:
        attribute.SetExpression(expression)
        yield
    finally:
        # Reset old comment
        attribute.SetExpression(None)
        if has_expression:
            attribute.SetExpression(old_comment)
        else:
            attribute[frame] = old_comment


def get_tool_resolution(tool, frame):
    """Return the 2D input resolution to a Fusion tool

    If the current tool hasn't been rendered its input resolution
    hasn't been saved. To combat this, add an expression in
    the comments field to read the resolution

    Args
        tool (Fusion Tool): The tool to query input resolution
        frame (int): The frame to query the resolution on.

    Returns:
        tuple: width, height as 2-tuple of integers

    Raises:
        ValueError: Unable to retrieve comp resolution.

    """
    comp = tool.Composition
    attribute = tool["Comments"]

    # False undo removes the undo-stack from the undo list
    with comp_lock_and_undo_chunk(comp, "Read resolution", False):

        # Get width
        with temp_expression(attribute, frame, "self.Input.OriginalWidth"):
            value = attribute[frame]
            if value is None:
                raise ValueError("Failed to read input width")
            width = int(value)

        # Get height
        with temp_expression(attribute, frame, "self.Input.OriginalHeight"):
            value = attribute[frame]
            if value is None:
                raise ValueError("Failed to read input height")
            height = int(value)

        return width, height
