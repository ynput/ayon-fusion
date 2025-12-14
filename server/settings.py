from ayon_server.settings import (
    BaseSettingsModel,
    SettingsField,
)

from .imageio import FusionImageIOModel


class CopyFusionSettingsModel(BaseSettingsModel):
    copy_path: str = SettingsField("", title="Local Fusion profile directory")
    copy_status: bool = SettingsField(title="Copy profile on first launch")
    force_sync: bool = SettingsField(title="Resync profile on each launch")


def _create_saver_instance_attributes_enum():
    return [
        {
            "value": "reviewable",
            "label": "Reviewable"
        },
        {
            "value": "farm_rendering",
            "label": "Farm rendering"
        }
    ]


def _image_format_enum():
    return [
        {"value": "exr", "label": "exr"},
        {"value": "tga", "label": "tga"},
        {"value": "png", "label": "png"},
        {"value": "tif", "label": "tif"},
        {"value": "jpg", "label": "jpg"},
        {"value": "dpx", "label": "dpx"},
    ]


def _frame_range_options_enum():
    return [
        {"value": "current_context", "label": "Current context"},
        {"value": "render_range", "label": "From render in/out"},
        {"value": "comp_range", "label": "From composition timeline"},
        {"value": "custom_range", "label": "Custom frame range"},
    ]


def _set_masterprefs_mode_enum():
    return [
        {"value": "set", "label": "Set AYON master prefs (override)"},
        {
            "value": "append",
            "label": "Append to existing master prefs (AYON pref is strongest)",
        },
        {
            "value": "prepend",
            "label": (
                "Prepend to existing master prefs (AYON pref is weakest)"
            ),
        },
        {
            "value": "do-not-set",
            "label": "Do not set (unmanaged)",
        },
    ]


class CreateSaverPluginModel(BaseSettingsModel):
    _isGroup = True
    temp_rendering_path_template: str = SettingsField(
        "", title="Temporary rendering path template"
    )
    default_variants: list[str] = SettingsField(
        default_factory=list,
        title="Default variants"
    )
    instance_attributes: list[str] = SettingsField(
        default_factory=list,
        enum_resolver=_create_saver_instance_attributes_enum,
        title="Instance attributes"
    )
    image_format: str = SettingsField(
        enum_resolver=_image_format_enum,
        title="Output Image Format"
    )


class HookOptionalModel(BaseSettingsModel):
    enabled: bool = SettingsField(
        True,
        title="Enabled"
    )


class HooksModel(BaseSettingsModel):
    set_fusion_master_prefs: str = SettingsField(
        "set",
        title="Set AYON Fusion MasterPrefs",
        description=(
            "A locked AYON Fusion MasterPrefs is used to set the `Config:` "
            "Path Map pref to include `$(AYON_FUSION_ROOT)/deploy/ayon` "
            "and force Python 3."
            "\n"
            "Fusion MasterPrefs can be stacked (multiple may apply) with the "
            "latter one taking precedence when applying the same preference."
            "\n"
            "When AYON's MasterPrefs are _weaker_ or _not set_ then it is up "
            "to the admin responsibility that the Config path map still "
            "points to AYON."
        ),
        enum_resolver=_set_masterprefs_mode_enum
    )
    InstallPySideToFusion: HookOptionalModel = SettingsField(
        default_factory=HookOptionalModel,
        title="Install PySide2"
    )
    FusionLaunchMenuHook: HookOptionalModel = SettingsField(
        default_factory=HookOptionalModel,
        title="Launch AYON Menu on Fusion Start",
        description="Launch the AYON menu on Fusion application startup. "
                    "This is only supported for Fusion 18+"
    )


class CreateSaverModel(CreateSaverPluginModel):
    default_frame_range_option: str = SettingsField(
        default="current_context",
        enum_resolver=_frame_range_options_enum,
        title="Default frame range source"
    )


class CreateImageSaverModel(CreateSaverPluginModel):
    default_frame: int = SettingsField(
        0,
        title="Default rendered frame"
    )


class CreatPluginsModel(BaseSettingsModel):
    CreateSaver: CreateSaverModel = SettingsField(
        default_factory=CreateSaverModel,
        title="Create Saver",
        description="Creator for render product type (eg. sequence)"
    )
    CreateImageSaver: CreateImageSaverModel = SettingsField(
        default_factory=CreateImageSaverModel,
        title="Create Image Saver",
        description="Creator for image product type (eg. single)"
    )


class FusionRenderLocalModel(BaseSettingsModel):
    suppress_dialogs: bool = SettingsField(
        True,
        title="Suppress Fusion dialogs",
        description=(
            "Suppress the Fusion 'Render Completed' and 'Render Failed'"
            " dialogs.")
    )


class PublishPluginsModel(BaseSettingsModel):
    FusionRenderLocal: FusionRenderLocalModel = SettingsField(
        default_factory=FusionRenderLocalModel,
        title="Render Local",
        description="Plug-in to render in current Fusion session."
    )


class FusionSettings(BaseSettingsModel):
    imageio: FusionImageIOModel = SettingsField(
        default_factory=FusionImageIOModel,
        title="Color Management (ImageIO)"
    )
    copy_fusion_settings: CopyFusionSettingsModel = SettingsField(
        default_factory=CopyFusionSettingsModel,
        title="Local Fusion profile settings"
    )
    hooks: HooksModel = SettingsField(
        default_factory=HooksModel,
        title="Hooks"
    )
    create: CreatPluginsModel = SettingsField(
        default_factory=CreatPluginsModel,
        title="Creator plugins"
    )
    publish: PublishPluginsModel = SettingsField(
        default_factory=PublishPluginsModel,
        title="Publish plugins"
    )


DEFAULT_VALUES = {
    "imageio": {
        "file_rules": {
            "enabled": False,
            "rules": []
        }
    },
    "copy_fusion_settings": {
        "copy_path": "~/.openpype/hosts/fusion/profiles",
        "copy_status": False,
        "force_sync": False
    },
    "hooks": {
        "set_fusion_master_prefs": "set",
        "InstallPySideToFusion": {
            "enabled": True
        },
        "FusionLaunchMenuHook": {
            "enabled": False
        }
    },
    "create": {
        "CreateSaver": {
            "temp_rendering_path_template": "{workdir}/renders/fusion/{product[name]}/{product[name]}.{frame}.{ext}",
            "default_variants": [
                "Main",
                "Mask"
            ],
            "instance_attributes": [
                "reviewable",
                "farm_rendering"
            ],
            "image_format": "exr",
            "default_frame_range_option": "current_context"
        },
        "CreateImageSaver": {
            "temp_rendering_path_template": "{workdir}/renders/fusion/{product[name]}/{product[name]}.{ext}",
            "default_variants": [
                "Main",
                "Mask"
            ],
            "instance_attributes": [
                "reviewable",
                "farm_rendering"
            ],
            "image_format": "exr",
            "default_frame": 0
        }
    },
    "publish": {
        "FusionRenderLocal": {
            "suppress_dialogs": True
        }
    }
}
