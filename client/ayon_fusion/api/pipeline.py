"""
Basic avalon integration
"""
import os
import sys
import logging
import contextlib
from pathlib import Path

import pyblish.api
from qtpy import QtCore

from ayon_core.lib import (
    Logger,
    register_event_callback,
    emit_event
)
from ayon_core.pipeline import (
    registered_host,
    register_loader_plugin_path,
    register_creator_plugin_path,
    register_inventory_action_path,
    AVALON_CONTAINER_ID,
)
from ayon_core.pipeline.load import any_outdated_containers
from ayon_core.host import (
    ContextChangeData,
    ContextChangeReason,
    HostBase,
    ILoadHost,
    IPublishHost,
    IWorkfileHost,
)
from ayon_core.tools.utils import host_tools
from ayon_fusion import FUSION_ADDON_ROOT


from .lib import (
    get_current_comp,
    validate_comp_prefs,
    prompt_reset_context
)

log = Logger.get_logger(__name__)

PLUGINS_DIR = os.path.join(FUSION_ADDON_ROOT, "plugins")

PUBLISH_PATH = os.path.join(PLUGINS_DIR, "publish")
LOAD_PATH = os.path.join(PLUGINS_DIR, "load")
CREATE_PATH = os.path.join(PLUGINS_DIR, "create")
INVENTORY_PATH = os.path.join(PLUGINS_DIR, "inventory")

COMP_CONTEXT_KEY = "ayon_context"


class FusionLogHandler(logging.Handler):
    # Keep a reference to fusion's Print function (Remote Object)
    _print = None

    @property
    def print(self):
        if self._print is not None:
            # Use cached
            return self._print

        _print = getattr(sys.modules["__main__"], "fusion").Print
        if _print is None:
            # Backwards compatibility: Print method on Fusion instance was
            # added around Fusion 17.4 and wasn't available on PyRemote Object
            # before
            _print = get_current_comp().Print
        self._print = _print
        return _print

    def emit(self, record):
        entry = self.format(record)
        self.print(entry)


class FusionHost(HostBase, IWorkfileHost, ILoadHost, IPublishHost):
    name = "fusion"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._forced_current_comp = None

    def install(self):
        """Install fusion-specific functionality of AYON.

        This is where you install menus and register families, data
        and loaders into fusion.

        It is called automatically when installing via
        `ayon_core.pipeline.install_host(ayon_fusion.api)`

        See the Maya equivalent for inspiration on how to implement this.

        """
        # Remove all handlers associated with the root logger object, because
        # that one always logs as "warnings" incorrectly.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        # Attach default logging handler that prints to active comp
        logger = logging.getLogger()
        formatter = logging.Formatter(fmt="%(message)s\n")
        handler = FusionLogHandler()
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)

        pyblish.api.register_host("fusion")
        pyblish.api.register_plugin_path(PUBLISH_PATH)
        log.info("Registering Fusion plug-ins..")

        register_loader_plugin_path(LOAD_PATH)
        register_creator_plugin_path(CREATE_PATH)
        register_inventory_action_path(INVENTORY_PATH)

        # Register events
        register_event_callback("open", on_after_open)
        register_event_callback("save", on_save)
        register_event_callback("new", on_new)

    # region workfile io api
    def has_unsaved_changes(self):
        comp = self.get_current_comp()
        return comp.GetAttrs()["COMPB_Modified"]

    def get_workfile_extensions(self):
        return [".comp"]

    def save_workfile(self, dst_path=None):
        comp = self.get_current_comp()
        # Save the context with the comp, also when the comp has none stored
        # yet and uses the fallback context.
        context = self._get_comp_context(comp)
        self._set_comp_context(
            comp, context["folder_path"], context["task_name"]
        )
        comp.Save(dst_path)

    def open_workfile(self, filepath):
        # Hack to get fusion, see
        #   ayon_fusion.api.pipeline.get_current_comp()
        fusion = getattr(sys.modules["__main__"], "fusion", None)

        return fusion.LoadComp(filepath)

    def get_current_workfile(self):
        comp = self.get_current_comp()
        current_filepath = comp.GetAttrs()["COMPS_FileName"]
        if not current_filepath:
            return None

        return current_filepath
    # endregion

    @contextlib.contextmanager
    def maintained_selection(self):
        from .lib import maintained_selection
        with maintained_selection(comp=self.get_current_comp()):
            yield

    def get_containers(self):
        return ls()

    def update_context_data(self, data, changes):
        comp = self.get_current_comp()
        comp.SetData("openpype", data)

    def get_context_data(self):
        comp = self.get_current_comp()
        return comp.GetData("openpype") or {}

    # region context
    def get_current_folder_path(self):
        return self.get_current_context()["folder_path"]

    def get_current_task_name(self):
        return self.get_current_context()["task_name"]

    def get_current_context(self):
        """Return the context stored in the current comp.

        Fusion can have multiple comps open, each of a different context.
        Without a comp, or when the comp has no context of the current project
        stored, this falls back to the last context set in AYON.

        Returns:
            HostContextData: Current context with 'project_name',
                'folder_path' and 'task_name'.

        """
        return self._get_comp_context(self.get_current_comp())

    def _get_comp_context(self, comp):
        project_name = self.get_current_project_name()
        if comp is not None:
            comp_context = comp.GetData(COMP_CONTEXT_KEY)
            if (
                comp_context
                and comp_context.get("project_name") == project_name
            ):
                return {
                    "project_name": project_name,
                    "folder_path": comp_context.get("folder_path"),
                    "task_name": comp_context.get("task_name"),
                }

        return {
            "project_name": project_name,
            "folder_path": super().get_current_folder_path(),
            "task_name": super().get_current_task_name(),
        }

    def _set_comp_context(self, comp, folder_path, task_name):
        if comp is None:
            return
        comp.SetData(COMP_CONTEXT_KEY, {
            "project_name": self.get_current_project_name(),
            "folder_path": folder_path,
            "task_name": task_name,
        })

    def _set_current_context(self, context_change_data: ContextChangeData):
        super()._set_current_context(context_change_data)
        # On workfile open the context changes before the workfile is opened,
        # so the current comp is not the comp of the new context yet.
        if context_change_data.reason == ContextChangeReason.workfile_open:
            return

        self._set_comp_context(
            self.get_current_comp(),
            context_change_data.folder_entity["path"],
            context_change_data.task_entity["name"],
        )

    def _after_workfile_open(self, open_workfile_context):
        super()._after_workfile_open(open_workfile_context)
        # Fusion's `LoadComp` may return an already loaded comp without
        # making it the current comp, so only store the context when the
        # current comp is the opened workfile.
        comp = self.get_current_comp()
        if comp is None:
            return
        filepath = comp.GetAttrs()["COMPS_FileName"]
        if Path(filepath) != Path(open_workfile_context.filepath):
            return
        self._set_comp_context(
            comp,
            open_workfile_context.folder_entity["path"],
            open_workfile_context.task_entity["name"],
        )

    def _after_context_change(self, context_change_data: ContextChangeData):
        """Offer to match the comp to the new context when saving into it.

        Args:
            context_change_data (ContextChangeData): Object with information
                about context change.
        """
        super()._after_context_change(context_change_data)
        if context_change_data.reason != ContextChangeReason.workfile_save:
            return

        # Fusion can have multiple comps open while AYON tracks a single
        # context. Also, due to Fusion's external python process design our
        # pipeline python process might have been shut down and restarted,
        # which restarts it to the environment Fusion started with; not
        # necessarily where the artist is currently working.
        # As such, AYON changing context does not mean the comp being saved
        # changes context, e.g. when saving the comp of another task that is
        # open in another tab back into its own task. So we only prompt when
        # the comp is not already saved inside the target work directory,
        # which `save_workfile_with_context` sets as `AYON_WORKDIR` before
        # the context change. The comp is not saved yet at this point.
        comp = self.get_current_comp()
        filepath = comp.GetAttrs()["COMPS_FileName"]
        workdir = os.environ["AYON_WORKDIR"]
        if Path(workdir) in Path(filepath).parents:
            return

        prompt_reset_context()
    # endregion

    def get_current_comp(self):
        if self._forced_current_comp is not None:
            return self._forced_current_comp
        return get_current_comp()

    @contextlib.contextmanager
    def current_comp(self, comp):
        """Fusion context manager to temporarily enforce 'current' comp.

        During this context the workfile methods like `get_current_workfile`
        and `save_workfile`, and `get_current_context` will use the specifiec
        `comp` instead of the actual active comp tab in Fusion itself. This is
        useful during e.g. publishing where a user may have initiated a publish
        from one comp and then as the publishing is running they switch to
        another comp tab.
        """
        old_comp = self._forced_current_comp
        try:
            self._forced_current_comp = comp
            yield
        finally:
            self._forced_current_comp = old_comp


def on_new(event):
    comp = event["Rets"]["comp"]
    validate_comp_prefs(comp, force_repair=True)


def on_save(event):
    comp = event["sender"]
    validate_comp_prefs(comp)


def on_after_open(event):
    comp = event["sender"]
    validate_comp_prefs(comp)

    if any_outdated_containers():
        log.warning("Scene has outdated content.")

        # Find AYON menu to attach to
        from . import menu

        def _on_show_scene_inventory():
            # ensure that comp is active
            frame = comp.CurrentFrame
            if not frame:
                print("Comp is closed, skipping show scene inventory")
                return
            frame.ActivateFrame()   # raise comp window
            host_tools.show_scene_inventory()

        from ayon_core.tools.utils import SimplePopup
        from ayon_core.style import load_stylesheet
        dialog = SimplePopup(parent=menu.menu)
        dialog.setWindowTitle("Fusion comp has outdated content")
        dialog.set_message("There are outdated containers in "
                          "your Fusion comp.")
        dialog.on_clicked.connect(_on_show_scene_inventory)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        dialog.setStyleSheet(load_stylesheet())


def ls():
    """List containers from active Fusion scene

    This is the host-equivalent of api.ls(), but instead of listing
    assets on disk, it lists assets already loaded in Fusion; once loaded
    they are called 'containers'

    Yields:
        dict: container

    """
    host = registered_host()
    comp = host.get_current_comp()
    tools = comp.GetToolList(False).values()

    for tool in tools:
        container = parse_container(tool)
        if container:
            yield container


def imprint_container(tool,
                      name,
                      namespace,
                      context,
                      loader=None):
    """Imprint a Loader with metadata

    Containerisation enables a tracking of version, author and origin
    for loaded assets.

    Arguments:
        tool (object): The node in Fusion to imprint as container, usually a
            Loader.
        name (str): Name of resulting assembly
        namespace (str): Namespace under which to host container
        context (dict): Asset information
        loader (str, optional): Name of loader used to produce this container.

    Returns:
        None

    """

    data = [
        ("schema", "openpype:container-2.0"),
        ("id", AVALON_CONTAINER_ID),
        ("name", str(name)),
        ("namespace", str(namespace)),
        ("loader", str(loader)),
        ("representation", context["representation"]["id"]),
        ("project_name", context["project"]["name"]),
    ]

    for key, value in data:
        tool.SetData("avalon.{}".format(key), value)


def parse_container(tool):
    """Returns imprinted container data of a tool

    This reads the imprinted data from `imprint_container`.

    """

    data = tool.GetData('avalon')
    if not isinstance(data, dict):
        return

    # If not all required data return the empty container
    required = ['schema', 'id', 'name',
                'namespace', 'loader', 'representation']
    if not all(key in data for key in required):
        return

    container = {key: data[key] for key in required}

    # Add optional keys, like `project_name`
    optional = ["project_name"]
    for key in optional:
        if key in data:
            container[key] = data[key]

    # Store the tool's name
    container["objectName"] = tool.Name

    # Store reference to the tool object
    container["_tool"] = tool

    return container


class FusionEventThread(QtCore.QThread):
    """QThread which will periodically ping Fusion app for any events.
    The fusion.UIManager must be set up to be notified of events before they'll
    be reported by this thread, for example:
        fusion.UIManager.AddNotify("Comp_Save", None)

    """

    on_event = QtCore.Signal(dict)

    def run(self):

        app = getattr(sys.modules["__main__"], "app", None)
        if app is None:
            # No Fusion app found
            return

        # As optimization store the GetEvent method directly because every
        # getattr of UIManager.GetEvent tries to resolve the Remote Function
        # through the PyRemoteObject
        get_event = app.UIManager.GetEvent
        delay = int(os.environ.get("AYON_FUSION_CALLBACK_INTERVAL", 1000))
        while True:
            if self.isInterruptionRequested():
                return

            # Process all events that have been queued up until now
            while True:
                event = get_event(False)
                if not event:
                    break
                self.on_event.emit(event)

            # Wait some time before processing events again
            # to not keep blocking the UI
            self.msleep(delay)


class FusionEventHandler(QtCore.QObject):
    """Emits AYON events based on Fusion events captured in a QThread.

    This will emit the following AYON events based on Fusion actions:
        save: Comp_Save, Comp_SaveAs
        open: Comp_Opened
        new: Comp_New

    To use this you can attach it to you Qt UI so it runs in the background.
    E.g.
        >>> handler = FusionEventHandler(parent=window)
        >>> handler.start()

    """
    ACTION_IDS = [
        "Comp_Save",
        "Comp_SaveAs",
        "Comp_New",
        "Comp_Opened"
    ]

    def __init__(self, parent=None):
        super(FusionEventHandler, self).__init__(parent=parent)

        # Set up Fusion event callbacks
        fusion = getattr(sys.modules["__main__"], "fusion", None)
        ui = fusion.UIManager

        # Add notifications for the ones we want to listen to
        notifiers = []
        for action_id in self.ACTION_IDS:
            notifier = ui.AddNotify(action_id, None)
            notifiers.append(notifier)

        # TODO: Not entirely sure whether these must be kept to avoid
        #       garbage collection
        self._notifiers = notifiers

        self._event_thread = FusionEventThread(parent=self)
        self._event_thread.on_event.connect(self._on_event)

    def start(self):
        self._event_thread.start()

    def stop(self):
        self._event_thread.requestInterruption()

    def _on_event(self, event):
        """Handle Fusion events to emit AYON events"""
        if not event:
            return

        what = event["what"]

        # Comp Save
        if what in {"Comp_Save", "Comp_SaveAs"}:
            if not event["Rets"].get("success"):
                # If the Save action is cancelled it will still emit an
                # event but with "success": False so we ignore those cases
                return
            # Comp was saved
            emit_event("save", data=event)
            return

        # Comp New
        elif what in {"Comp_New"}:
            emit_event("new", data=event)

        # Comp Opened
        elif what in {"Comp_Opened"}:
            emit_event("open", data=event)
