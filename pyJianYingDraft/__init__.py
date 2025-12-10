from .audio_segment import AudioSegment
from .draft_folder import DraftFolder
from .effect_segment import Effect_segment, Filter_segment
from .keyframe import KeyframeProperty
from .local_materials import AudioMaterial, CropSettings, VideoMaterial
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
from .template_mode import ExtendMode, ShrinkMode
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
from .track import TrackType
from .video_segment import ClipSettings, StickerSegment, VideoSegment

__all__ = [
    "SEC",
    "AudioMaterial",
    "AudioSceneEffectType",
    "AudioSegment",
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
    "CropSettings",
    "DraftFolder",
    "Effect_segment",
    "ExtendMode",
    "FilterType",
    "Filter_segment",
    "FontType",
    "GroupAnimationType",
    "IntroType",
    "KeyframeProperty",
    "MaskType",
    "OutroType",
    "ScriptFile",
    "ShrinkMode",
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
    "TrackType",
    "TransitionType",
    "VideoCharacterEffectType",
    "VideoMaterial",
    "VideoSceneEffectType",
    "VideoSegment",
    "tim",
    "trange",
]
