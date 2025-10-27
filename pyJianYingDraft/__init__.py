from .audio_segment import Audio_segment
from .draft_folder import Draft_folder
from .effect_segment import Effect_segment, Filter_segment
from .keyframe import Keyframe_property
from .local_materials import Audio_material, Crop_settings, Video_material
from .metadata import (
    AudioSceneEffectType,
    CapCutGroupAnimationType,
    CapCutIntroType,
    CapCutMaskType,
    CapCutOutroType,
    CapCutSpeechToSongEffectType,
    CapCutTextIntro,
    CapCutTextLoopAnim,
    CapCutTextOutro,
    CapCutTransitionType,
    CapCutVideoCharacterEffectType,
    CapCutVideoSceneEffectType,
    CapCutVoiceCharactersEffectType,
    CapCutVoiceFiltersEffectType,
    FilterType,
    FontType,
    GroupAnimationType,
    IntroType,
    MaskType,
    OutroType,
    SpeechToSongType,
    TextIntro,
    TextLoopAnim,
    TextOutro,
    ToneEffectType,
    TransitionType,
    VideoCharacterEffectType,
    VideoSceneEffectType,
)
from .script_file import ScriptFile
from .template_mode import Extend_mode, Shrink_mode
from .text_segment import (
    Text_background,
    Text_border,
    Text_segment,
    Text_shadow,
    Text_style,
)

# 仅在Windows系统下导入jianying_controller
# ISWIN = (sys.platform == 'win32')
# if ISWIN:
#     from .jianying_controller import Jianying_controller, Export_resolution, Export_framerate
from .time_util import SEC, Timerange, tim, trange
from .track import Track_type
from .video_segment import ClipSettings, StickerSegment, VideoSegment

__all__ = [
    "SEC",
    "AudioSceneEffectType",
    "Audio_material",
    "Audio_segment",
    "CapCutGroupAnimationType",
    "CapCutIntroType",
    "CapCutMaskType",
    "CapCutOutroType",
    "CapCutSpeechToSongEffectType",
    "CapCutTextIntro",
    "CapCutTextLoopAnim",
    "CapCutTextOutro",
    "CapCutTransitionType",
    "CapCutVideoCharacterEffectType",
    "CapCutVideoSceneEffectType",
    "CapCutVoiceCharactersEffectType",
    "CapCutVoiceFiltersEffectType",
    "ClipSettings",
    "Crop_settings",
    "Draft_folder",
    "Effect_segment",
    "Extend_mode",
    "FilterType",
    "Filter_segment",
    "FontType",
    "GroupAnimationType",
    "IntroType",
    "Keyframe_property",
    "MaskType",
    "OutroType",
    "ScriptFile",
    "Shrink_mode",
    "SpeechToSongType",
    "StickerSegment",
    "TextIntro",
    "TextLoopAnim",
    "TextOutro",
    "Text_background",
    "Text_border",
    "Text_segment",
    "Text_shadow",
    "Text_style",
    "Timerange",
    "ToneEffectType",
    "Track_type",
    "TransitionType",
    "VideoCharacterEffectType",
    "VideoSceneEffectType",
    "VideoSegment",
    "Video_material",
    "tim",
    "trange"
]

# # 仅在Windows系统下添加jianying_controller相关的导出
# if ISWIN:
#     __all__.extend([
#         "JianyingController",
#         "ExportResolution",
#         "ExportFramerate",
#         "Jianying_controller",
#         "Export_resolution",
#         "Export_framerate",
#     ])
