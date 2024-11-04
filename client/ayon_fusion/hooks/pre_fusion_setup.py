import os
from ayon_applications import (
    PreLaunchHook,
    LaunchTypes,
    ApplicationLaunchFailed,
)
from ayon_fusion import (
    FUSION_ADDON_ROOT,
    FUSION_VERSIONS_DICT,
    FUSION_FALLBACK_VERSION,
    get_fusion_version,
)


class FusionPrelaunch(PreLaunchHook):
    """
    Prepares AYON Fusion environment.
    Requires correct Python home variable to be defined in the environment
    settings for Fusion to point at a valid Python 3 build for Fusion.
    Python3 versions that are supported by Fusion:
    Fusion 9, 16, 17 : Python 3.6
    Fusion 18        : Python 3.6 - 3.10
    """

    app_groups = {"fusion"}
    order = 1
    launch_types = {LaunchTypes.local,
                    LaunchTypes.farm_render,
                    # This seems to be incorrectly configured for
                    # ayon_applications addon, see `ayon_applications/#2`
                    LaunchTypes.farm_publish}

    def execute(self):
        # making sure python 3 is installed at provided path
        # Py 3.3-3.10 for Fusion 18+ or Py 3.6 for Fu 16-17
        app_data = self.launch_context.env.get("AYON_APP_NAME")
        app_version = get_fusion_version(app_data)
        if not app_version:
            self.log.warning(
                f"Fusion version information not found for '{app_data}'.\n"
                "The key field in the 'applications/fusion/variants' should "
                "consist of a number, corresponding to major Fusion version. "
                f"Assuming fallback version: {FUSION_FALLBACK_VERSION}."
            )
            app_version = FUSION_FALLBACK_VERSION

        py3_var, _ = FUSION_VERSIONS_DICT[app_version]
        fusion_python3_home = self.launch_context.env.get(py3_var, "")

        for path in fusion_python3_home.split(os.pathsep):
            # Allow defining multiple paths, separated by os.pathsep,
            # to allow "fallback" to other path.
            # But make to set only a single path as final variable.
            py3_dir = os.path.normpath(path)
            if os.path.isdir(py3_dir):
                break
        else:
            raise ApplicationLaunchFailed(
                "Python 3 is not installed at the provided path.\n"
                "Make sure the environment in fusion settings has "
                "'FUSION_PYTHON3_HOME' set correctly and make sure "
                "Python 3 is installed in the given path."
                f"\n\nPYTHON PATH: {fusion_python3_home}"
            )

        self.log.info(f"Setting {py3_var}: '{py3_dir}'...")
        self.launch_context.env[py3_var] = py3_dir

        # Fusion 18+ requires FUSION_PYTHON3_HOME to also be on PATH
        if app_version >= 18:
            self.launch_context.env["PATH"] += os.pathsep + py3_dir

        self.launch_context.env[py3_var] = py3_dir

        # for hook installing PySide2
        self.data["fusion_python3_home"] = py3_dir

        self.log.info(f"Setting AYON_FUSION_ROOT: {FUSION_ADDON_ROOT}")
        self.launch_context.env["AYON_FUSION_ROOT"] = FUSION_ADDON_ROOT
