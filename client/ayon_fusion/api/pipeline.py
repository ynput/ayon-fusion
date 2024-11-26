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
    register_loader_plugin_path,
    register_creator_plugin_path,
    register_inventory_action_path,
    AVALON_CONTAINER_ID,
)
from ayon_core.pipeline.load import any_outdated_containers
from ayon_core.host import HostBase, IWorkfileHost, ILoadHost, IPublishHost
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

# Track whether the workfile tool is about to save
_about_to_save = False


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
        register_event_callback("workfile.save.before", before_workfile_save)
        register_event_callback("save", on_save)
        register_event_callback("new", on_new)
        register_event_callback("taskChanged", on_task_changed)

    # region workfile io api
    def has_unsaved_changes(self):
        comp = get_current_comp()
        return comp.GetAttrs()["COMPB_Modified"]

    def get_workfile_extensions(self):
        return [".comp"]

    def save_workfile(self, dst_path=None):
        comp = get_current_comp()
        comp.Save(dst_path)

    def open_workfile(self, filepath):
        # Hack to get fusion, see
        #   ayon_fusion.api.pipeline.get_current_comp()
        fusion = getattr(sys.modules["__main__"], "fusion", None)

        return fusion.LoadComp(filepath)

    def get_current_workfile(self):
        comp = get_current_comp()
        current_filepath = comp.GetAttrs()["COMPS_FileName"]
        if not current_filepath:
            return None

        return current_filepath

    def work_root(self, session):
        work_dir = session["AYON_WORKDIR"]
        scene_dir = session.get("AVALON_SCENEDIR")
        if scene_dir:
            return os.path.join(work_dir, scene_dir)
        else:
            return work_dir
    # endregion

    @contextlib.contextmanager
    def maintained_selection(self):
        from .lib import maintained_selection
        return maintained_selection()

    def get_containers(self):
        return ls()

    def update_context_data(self, data, changes):
        comp = get_current_comp()
        comp.SetData("openpype", data)

    def get_context_data(self):
        comp = get_current_comp()
        return comp.GetData("openpype") or {}


def on_new(event):
    comp = event["Rets"]["comp"]
    validate_comp_prefs(comp, force_repair=True)


def on_save(event):
    comp = event["sender"]
    validate_comp_prefs(comp)

    # We are now starting the actual save directly
    global _about_to_save
    _about_to_save = False


def on_task_changed():
    global _about_to_save
    print(f"Task changed: {_about_to_save}")
    # TODO: Only do this if not headless
    if _about_to_save:
        # Let's prompt the user to update the context settings or not
        prompt_reset_context()


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


def before_workfile_save(event):
    # Due to Fusion's external python process design we can't really
    # detect whether the current Fusion environment matches the one the artists
    # expects it to be. For example, our pipeline python process might
    # have been shut down, and restarted - which will restart it to the
    # environment Fusion started with; not necessarily where the artist
    # is currently working.
    # The `_about_to_save` var is used to detect context changes when
    # saving into another asset. If we keep it False it will be ignored
    # as context change. As such, before we change tasks we will only
    # consider it the current filepath is within the currently known
    # AVALON_WORKDIR. This way we avoid false positives of thinking it's
    # saving to another context and instead sometimes just have false negatives
    # where we fail to show the "Update on task change" prompt.
    comp = get_current_comp()
    filepath = comp.GetAttrs()["COMPS_FileName"]
    workdir = os.environ.get("AYON_WORKDIR")
    if Path(workdir) in Path(filepath).parents:
        global _about_to_save
        _about_to_save = True


def ls():
    """List containers from active Fusion scene

    This is the host-equivalent of api.ls(), but instead of listing
    assets on disk, it lists assets already loaded in Fusion; once loaded
    they are called 'containers'

    Yields:
        dict: container

    """

    comp = get_current_comp()
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
        self._event_thread.stop()

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
