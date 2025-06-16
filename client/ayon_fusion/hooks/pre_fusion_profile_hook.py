import os
import shutil
import platform
from typing import Optional, Literal
from pathlib import Path
from ayon_fusion import (
    FUSION_ADDON_ROOT,
    FUSION_VERSIONS_DICT,
    get_fusion_version,
)
from ayon_applications import (
    PreLaunchHook,
    LaunchTypes,
    ApplicationLaunchFailed,
)


class FusionCopyPrefsPrelaunch(PreLaunchHook):
    """
    Prepares local Fusion profile directory, copies existing Fusion profile.
    This also sets FUSION MasterPrefs variable, which is used
    to apply Master.prefs file to override some Fusion profile settings to:
        - enable the AYON menu
        - force Python 3 over Python 2
        - force English interface
    Master.prefs is defined in openpype/hosts/fusion/deploy/fusion_shared.prefs
    """

    app_groups = {"fusion"}
    order = 2
    launch_types = {LaunchTypes.local,
                    LaunchTypes.farm_render,
                    # This seems to be incorrectly configured for
                    # ayon_applications addon, see `ayon_applications/#2`
                    LaunchTypes.farm_publish}

    def get_fusion_profile_name(self, profile_version: int) -> str:
        # Returns 'Default', unless FUSION16_PROFILE is set
        return os.getenv(f"FUSION{profile_version}_PROFILE", "Default")

    def get_fusion_profile_dir(self, profile_version) -> Optional[Path]:
        # Get FUSION_PROFILE_DIR variable
        fusion_profile = self.get_fusion_profile_name(profile_version)
        fusion_var_prefs_dir = os.getenv(
            f"FUSION{profile_version}_PROFILE_DIR"
        )

        # Check if FUSION_PROFILE_DIR exists
        if fusion_var_prefs_dir and Path(fusion_var_prefs_dir).is_dir():
            fu_prefs_dir = Path(fusion_var_prefs_dir, fusion_profile)
            self.log.info(f"{fusion_var_prefs_dir} is set to {fu_prefs_dir}")
            return fu_prefs_dir
        return None

    def get_profile_source(self, profile_version: int) -> Path:
        """Get Fusion preferences profile location.
        See Per-User_Preferences_and_Paths on VFXpedia for reference.
        """
        fusion_profile = self.get_fusion_profile_name(profile_version)
        profile_source = self.get_fusion_profile_dir(profile_version)
        if profile_source:
            return profile_source
        # otherwise get default location of the profile folder
        fu_prefs_dir = f"Blackmagic Design/Fusion/Profiles/{fusion_profile}"
        if platform.system() == "Windows":
            profile_source = Path(os.getenv("AppData"), fu_prefs_dir)
        elif platform.system() == "Darwin":
            profile_source = Path(
                "~/Library/Application Support/", fu_prefs_dir
            ).expanduser()
        elif platform.system() == "Linux":
            profile_source = Path("~/.fusion", fu_prefs_dir).expanduser()
        self.log.info(
            f"Locating source Fusion prefs directory: {profile_source}"
        )
        return profile_source

    def get_copy_fusion_prefs_settings(self):
        # Get copy preferences options from the global application settings

        copy_fusion_settings = self.data["project_settings"]["fusion"].get(
            "copy_fusion_settings", {}
        )
        if not copy_fusion_settings:
            self.log.error("Copy prefs settings not found")
        copy_status = copy_fusion_settings.get("copy_status", False)
        force_sync = copy_fusion_settings.get("force_sync", False)
        copy_path = copy_fusion_settings.get("copy_path") or None
        if copy_path:
            copy_path = Path(copy_path).expanduser()
        return copy_status, copy_path, force_sync

    def copy_fusion_profile(
        self, copy_from: Path, copy_to: Path, force_sync: bool
    ) -> None:
        """On the first Fusion launch copy the contents of Fusion profile
        directory to the working predefined location. If the Openpype profile
        folder exists, skip copying, unless re-sync is checked.
        If the prefs were not copied on the first launch,
        clean Fusion profile will be created in fu_profile_dir.
        """
        if copy_to.exists() and not force_sync:
            self.log.info(
                "Destination Fusion preferences folder already exists: "
                f"{copy_to} "
            )
            return
        self.log.info("Starting copying Fusion preferences")
        self.log.debug(f"force_sync option is set to {force_sync}")
        try:
            copy_to.mkdir(exist_ok=True, parents=True)
        except PermissionError:
            self.log.warning(f"Creating the folder not permitted at {copy_to}")
            return
        if not copy_from.exists():
            self.log.warning(f"Fusion preferences not found in {copy_from}")
            return
        for file in copy_from.iterdir():
            if file.suffix in (
                ".prefs",
                ".def",
                ".blocklist",
                ".fu",
                ".toolbars",
            ):
                # convert Path to str to be compatible with Python 3.6+
                shutil.copy(str(file), str(copy_to))
        self.log.info(
            f"Successfully copied preferences: {copy_from} to {copy_to}"
        )

    def execute(self):
        (
            copy_status,
            fu_profile_dir,
            force_sync,
        ) = self.get_copy_fusion_prefs_settings()

        # Get launched application context and return correct app version
        app_name = self.launch_context.env.get("AYON_APP_NAME")
        app_version = get_fusion_version(app_name)
        if app_version is None:
            version_names = ", ".join(str(x) for x in FUSION_VERSIONS_DICT)
            raise ApplicationLaunchFailed(
                "Unable to detect valid Fusion version number from app "
                f"name: {app_name}.\nMake sure to include at least a digit "
                "to indicate the Fusion version like '18'.\n"
                f"Detectable Fusion versions are: {version_names}"
            )

        _, profile_version = FUSION_VERSIONS_DICT[app_version]
        if fu_profile_dir is not None:
            fu_profile = self.get_fusion_profile_name(profile_version)

            # Add temporary profile directory variables to customize Fusion
            # to define where it can read custom scripts and tools from
            fu_profile_dir_variable = f"FUSION{profile_version}_PROFILE_DIR"
            self.log.info(
                f"Setting {fu_profile_dir_variable}: {fu_profile_dir}"
            )
            self.launch_context.env[fu_profile_dir_variable] = (
                str(fu_profile_dir)
            )

            # do a copy of Fusion profile if copy_status toggle is enabled
            if copy_status:
                profile_source = self.get_profile_source(profile_version)
                dest_folder = Path(fu_profile_dir, fu_profile)
                self.copy_fusion_profile(profile_source, dest_folder, force_sync)
        else:
            self.log.info(
                "AYON Fusion profile directory is not set, "
                "using default Fusion profile location."
            )

        self._set_master_prefs_variable(profile_version)

    def _set_master_prefs_variable(self, profile_version: int):
        """Set the MasterPrefs variable for Fusion."""

        mode: Literal["set", "append", "prepend", "do-not-set"] = (
            self.data["project_settings"]["fusion"]["hooks"].get(
                "set_fusion_master_prefs", "set"
            )
        )
        master_prefs_variable = f"FUSION{profile_version}_MasterPrefs"
        if mode == "do-not-set":
            # If mode is do-not-set, we do not set the variable at all
            self.log.info(
                f"Not setting {master_prefs_variable} variable value."
            )
            return

        # Set AYON Fusion Master Prefs
        master_prefs: str = os.path.join(
            FUSION_ADDON_ROOT, "deploy", "ayon", "fusion_shared.prefs"
        )
        if mode in {"prepend", "append"}:
            existing_master_prefs: str = self.launch_context.env.get(
                master_prefs_variable, "")
            if existing_master_prefs:
                if mode == "append":
                    self.log.info(
                        f"Appending to existing {master_prefs_variable} "
                        f"variable value: {existing_master_prefs}"
                    )
                    master_prefs = (
                        f"{existing_master_prefs}{os.pathsep}{master_prefs}"
                    )
                elif mode == "prepend":
                    self.log.info(
                        f"Prepending to existing {master_prefs_variable} "
                        f"variable value: {existing_master_prefs}"
                    )
                    master_prefs = (
                        f"{master_prefs}{os.pathsep}{existing_master_prefs}"
                    )

        self.log.info(f"Setting {master_prefs_variable}: {master_prefs}")
        self.launch_context.env[master_prefs_variable] = str(master_prefs)
