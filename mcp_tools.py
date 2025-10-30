#!/usr/bin/env python3
"""
CapCut API MCP Server (Complete Version)

完整版本的MCP服务器，集成所有CapCut API接口
"""

import contextlib
import io
import os
import sys
import traceback
from typing import Any, Dict

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 导入CapCut API功能
try:
    from pyJianYingDraft.text_segment import Text_border, Text_style, TextStyleRange
    from services.add_audio_track import add_audio_track
    from services.add_image_impl import add_image_impl
    from services.add_sticker_impl import add_sticker_impl
    from services.add_subtitle_impl import add_subtitle_impl
    from services.add_video_keyframe_impl import add_video_keyframe_impl
    from util import hex_to_rgb
    CAPCUT_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import CapCut modules: {e}", file=sys.stderr)
    CAPCUT_AVAILABLE = False

# 完整的工具定义
TOOLS = [
    {
        "name": "create_draft",
        "description": "创建新的CapCut草稿",
        "inputSchema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "default": 1080, "description": "视频宽度"},
                "height": {"type": "integer", "default": 1920, "description": "视频高度"},
                "name": {"type": "string", "description": "草稿名称"},
                "framerate": {"type": "string", "description": "帧率（可选值30.0、50.0、60.0）", "enum": ["30.0", "50.0", "60.0"], "default": "30.0"}
            },
            "required": ["width", "height"]
        }
    },
    {
        "name": "batch_add_videos",
        "description": """批量添加多个视频素材到track。适用于需要连续添加多个视频的场景。每个视频可以独立设置video_url、start、end、target_start、speed参数，其他参数（如转场、蒙版、缩放等）在所有视频间共享。
        
        【使用场景】
        • 视频拼接：将多个视频片段按顺序拼接成完整视频
        • 批量导入：一次性导入多个视频素材
        • 幻灯片：制作图片或视频幻灯片效果
        
        【videos数组说明】
        每个视频对象包含：
        • video_url（必需）：视频素材URL或本地路径
        • start（可选，默认0）：从视频第几秒开始截取
        • end（可选，默认0）：到视频第几秒结束截取（0表示到末尾）
        • target_start（可选，默认0）：该片段在时间线上的起始位置
        • speed（可选，默认1.0）：播放速度
        • mode（可选，默认cover）：速度计算模式。cover=使用speed参数，fill=根据target_duration自动计算speed
        • target_duration（默认None）：fill模式专用，素材在轨道上的目标时长（秒）
        • duration（默认None）：视频素材总时长（秒）
        
        【共享参数】
        其他参数（transform_x/y、scale_x/y、transition、mask_type等）在根级别设置，应用于所有视频
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "videos": {
                    "type": "array",
                    "description": "视频素材列表数组",
                    "items": {
                        "type": "object",
                        "properties": {
                            "video_url": {"type": "string", "description": "视频素材URL或本地路径"},
                            "start": {"type": "number", "default": 0, "description": "从视频素材第几秒开始截取"},
                            "end": {"type": "number", "default": 0, "description": "到视频素材第几秒结束截取（0=到末尾）"},
                            "target_start": {"type": "number", "default": 0, "description": "该片段在时间线上的起始位置"},
                            "speed": {"type": "number", "default": 1.0, "description": "播放速度"},
                            "mode": {"type": "string", "enum": ["cover", "fill"], "default": "cover", "description": "速度计算模式。cover=使用speed参数，fill=根据target_duration自动计算speed"},
                            "target_duration": {"type": ["number", "null"], "default": None, "description": "fill模式专用，素材在轨道上的目标时长（秒）"},
                            "duration": {"type": ["number", "null"], "default": None, "description": "视频素材总时长（秒）"}
                        },
                        "required": ["video_url", "start", "end", "target_start", "mode", "target_duration", "duration"]
                    }
                },
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "transform_x": {"type": "number", "default": 0, "description": "【共享】水平位置偏移（应用于所有视频）"},
                "transform_y": {"type": "number", "default": 0, "description": "【共享】垂直位置偏移（应用于所有视频）"},
                "scale_x": {"type": "number", "default": 1, "description": "【共享】水平缩放倍数（应用于所有视频）"},
                "scale_y": {"type": "number", "default": 1, "description": "【共享】垂直缩放倍数（应用于所有视频）"},
                "track_name": {"type": "string", "default": "video_main", "description": "【共享】轨道名称"},
                "relative_index": {"type": "integer", "default": 0, "description": "【共享】相对排序索引"},
                "transition": {"type": "string", "description": "【共享】转场效果类型"},
                "transition_duration": {"type": "number", "default": 0.5, "description": "【共享】转场时长（秒）"},
                "volume": {"type": "number", "default": 1.0, "description": "【共享】音量增益"},
                "intro_animation": {"type": "string", "description": "【共享】入场动画效果"},
                "intro_animation_duration": {"type": "number", "default": 0.5, "description": "【共享】入场动画时长"},
                "outro_animation": {"type": "string", "description": "【共享】出场动画效果"},
                "outro_animation_duration": {"type": "number", "default": 0.5, "description": "【共享】出场动画时长"},
                "combo_animation": {"type": "string", "description": "【共享】组合动画效果"},
                "combo_animation_duration": {"type": "number", "default": 0.5, "description": "【共享】组合动画时长"},
                "mask_type": {"type": "string", "description": "【共享】蒙版形状类型"},
                "mask_center_x": {"type": "number", "default": 0.5, "description": "【共享】蒙版中心X坐标"},
                "mask_center_y": {"type": "number", "default": 0.5, "description": "【共享】蒙版中心Y坐标"},
                "mask_size": {"type": "number", "default": 1.0, "description": "【共享】蒙版大小"},
                "mask_rotation": {"type": "number", "default": 0.0, "description": "【共享】蒙版旋转角度"},
                "mask_feather": {"type": "number", "default": 0.0, "description": "【共享】蒙版羽化程度"},
                "mask_invert": {"type": "boolean", "default": False, "description": "【共享】是否反转蒙版"},
                "mask_rect_width": {"type": ["number", "null"], "default": None, "description": "【共享】矩形蒙版宽度"},
                "mask_round_corner": {"type": ["number", "null"], "default": None, "description": "【共享】矩形圆角半径"},
                "filter_type": {"type": "string", "description": "【共享】滤镜效果类型"},
                "filter_intensity": {"type": "number", "default": 100.0, "description": "【共享】滤镜强度"},
                "fade_in_duration": {"type": "number", "default": 0.0, "description": "【共享】音频淡入时长"},
                "fade_out_duration": {"type": "number", "default": 0.0, "description": "【共享】音频淡出时长"},
                "background_blur": {"type": "integer", "description": "【共享】背景模糊强度（1-4）"}
            },
            "required": ["videos"]
        }
    },
    {
        "name": "add_video",
        "description": """添加视频素材到track。支持素材裁剪、转场效果、蒙版遮罩、背景模糊等高级视频编辑功能。
        1️⃣ 基础用法（截取部分片段）：
        • start=10, end=20, duration=60 → 从60秒视频中截取第10-20秒

        2️⃣ 截取到末尾用法：
        • start=10, end=0, duration=60 → 截取第10秒到末尾（第60秒）✅ 最常用
        • start=10, duration=60 → 同上（end可省略，默认为0）

        3️⃣ 完整播放用法：
        • duration=60 → 播放完整60秒视频（start和end可省略，默认为0）
        • start=0, end=0, duration=60 → 同上（显式指定）

        【关键约束】
        ⚠️  当 end=0 或 end=None 时，必须提供 duration 参数，否则会导致黑屏
        ⚠️  start 必须 < end（当end>0时）且 < duration（当提供duration时）
        ✅  建议：始终提供 duration
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "视频素材文件的URL地址或本地文件路径"},
                "start": {
                    "type": "number",
                    "default": 0,
                    "description": """从原始视频素材的第几秒开始截取（>=0）。
                        示例：
                        • start=0 → 从视频开头开始
                        • start=10 → 从第10秒开始
                        """
                },
                "end": {
                    "type": "number",
                    "default": 0,
                    "description": """到原始视频素材的第几秒结束截取。

                    语义说明：
                    • end=0（默认） → 截取到视频末尾（⚠️ 需提供duration参数）
                    • end>0 → 截取到指定秒数（例如end=5.0表示截取到第5秒）

                    示例：
                    • start=0, end=5 → 截取前5秒
                    • start=2, end=8 → 截取第2-8秒（共6秒）
                    • start=10, end=0, duration=60 → 截取第10-60秒（共50秒）✅ 推荐用法

                    ⚠️ 约束：
                    • 当end>0时，必须满足 end > start
                    • 当end=0时，必须提供duration参数，否则会导致黑屏
                """
                },
                "mode": {
                    "type": "string",
                    "enum": ["cover", "fill"],
                    "default": "cover",
                    "description": """速度计算模式。
                    • "cover"（默认）：使用speed参数控制播放速度
                    • "fill"：根据target_duration自动计算speed，使视频片段正好填充指定时长
                    
                    示例：
                    • mode="cover", speed=2.0 → 视频以2倍速播放
                    • mode="fill", target_duration=10 → 自动调整速度使片段时长为10秒
                """
                },
                "target_duration": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": """【fill模式专用】成片目标时长（秒）。
                    
                    当mode="fill"时必需：
                    • 系统会自动计算speed = source_duration / target_duration
                    • 例如：5秒素材，target_duration=10 → speed=0.5x（慢放）
                    • 例如：20秒素材，target_duration=10 → speed=2.0x（快放）
                    
                    当mode="cover"时忽略此参数
                """
                },
                "duration": {
                    "type": ["number", "null"],
                    "default": None,
                    "description": """原始视频素材的总时长（秒）。
                    作用：
                    • 计算依据：当end=0时，作为裁剪终点的计算依据（必需）
                    示例：
                    • duration=60.5 → 视频总时长60.5秒
                """
                },
                "target_start": {
                    "type": "number",
                    "default": 0,
                    "description": """该视频片段在track上的起始时间点（秒）。
                        示例：
                        • target_start=0 → track从第0秒开始播放此片段
                        • target_start=10 → track从第10秒开始播放此片段
                        """
                },
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "transform_x": {"type": "number", "default": 0, "description": "【空间定位-X轴】视频素材在画布上的水平位置偏移。单位：半个画布宽度。0为画布中心，-1为向左偏移半个画布宽（画布最左侧），1为向右偏移半个画布宽（画布最右侧），2为向右偏移整个画布宽"},
                "transform_y": {"type": "number", "default": 0, "description": "【空间定位-Y轴】视频素材在画布上的垂直位置偏移。单位：半个画布高度。0为画布中心，-1为向上偏移半个画布高（画布顶部），1为向下偏移半个画布高（画布底部）。参考：字幕常用-0.8"},
                "scale_x": {"type": "number", "default": 1, "description": "【缩放-X轴】水平缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "scale_y": {"type": "number", "default": 1, "description": "【缩放-Y轴】垂直缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "speed": {"type": "number", "default": 1.0, "description": "视频播放速率。范围：0.1-100。1.0为正常速度，2.0为2倍速（加速），0.5为0.5倍速（慢动作）"},
                "track_name": {"type": "string", "default": "video_main", "description": "轨道名称标识。建议命名：video_main（主视频轨）、video_pip（画中画轨）、video_overlay（叠加轨）"},
                "relative_index": {"type": "integer", "default": 0, "description": "同轨道内素材的相对排序索引。0为最早，数值越大越靠后。用于精确控制素材在轨道内的前后顺序"},
                "intro_animation": {"type": "string", "description": "入场动画效果名称。素材出现时的动画效果，需与系统支持的动画类型匹配"},
                "intro_animation_duration": {"type": "number", "default": 0.5, "description": "入场动画持续时长（秒）。建议范围：0.3-2.0秒"},
                "outro_animation": {"type": "string", "description": "出场动画效果名称。素材消失时的动画效果，需与系统支持的动画类型匹配"},
                "outro_animation_duration": {"type": "number", "default": 0.5, "description": "出场动画持续时长（秒）。建议范围：0.3-2.0秒"},
                "combo_animation": {"type": "string", "description": "组合动画效果名称。同时包含入场和出场的预设动画组合"},
                "combo_animation_duration": {"type": "number", "default": 0.5, "description": "组合动画总持续时长（秒）。会平均分配给入场和出场"},
                "transition": {"type": "string", "description": "转场效果类型名称。应用于当前素材与前一个素材之间的过渡效果，需与系统支持的转场类型匹配"},
                "transition_duration": {"type": "number", "default": 0.5, "description": "转场效果持续时长（秒）。建议范围：0.3-2.0秒。转场会占用前后两个素材各一半的时长"},
                "volume": {"type": "number", "default": 1.0, "description": "视频原声音量增益。范围：0.0-2.0。0.0为静音，1.0为原始音量，2.0为放大两倍"},
                "filter_type": {"type": "string", "description": "滤镜效果类型名称。应用的颜色滤镜或风格化效果，需与系统支持的滤镜类型匹配"},
                "filter_intensity": {"type": "number", "default": 100.0, "description": "滤镜效果强度。范围：0-100。0为无效果，100为最大强度"},
                "fade_in_duration": {"type": "number", "default": 0.0, "description": "音频淡入时长（秒）。视频开始时音量从0逐渐增加到设定值的过渡时间"},
                "fade_out_duration": {"type": "number", "default": 0.0, "description": "音频淡出时长（秒）。视频结束时音量从设定值逐渐减少到0的过渡时间"},
                "mask_type": {"type": "string", "description": "蒙版形状类型。可选：circle（圆形）、rectangle（矩形）、heart（心形）等，需与系统支持的蒙版类型匹配"},
                "mask_center_x": {"type": "number", "default": 0.5, "description": "【歧义警告】蒙版中心点-X坐标。代码逻辑显示应输入像素值(例如1080px宽画布的中心应输入540),但示例代码使用0.5表示居中,与内部转换公式center_x/(画布宽/2)矛盾。建议:按归一化使用(0.0=最左,0.5=中心,1.0=最右),或测试后根据实际效果调整"},
                "mask_center_y": {"type": "number", "default": 0.5, "description": "【歧义警告】蒙版中心点-Y坐标。代码逻辑显示应输入像素值(例如1920px高画布的中心应输入960),但示例代码使用0.5表示居中,与内部转换公式center_y/(画布高/2)矛盾。建议:按归一化使用(0.0=最上,0.5=中心,1.0=最下),或测试后根据实际效果调整"},
                "mask_size": {"type": "number", "default": 1.0, "description": "蒙版主尺寸大小。归一化比例：0.0为不可见，1.0为覆盖整个画布，支持超过1.0"},
                "mask_rotation": {"type": "number", "default": 0.0, "description": "蒙版旋转角度（度）。范围：0-360。顺时针旋转"},
                "mask_feather": {"type": "number", "default": 0.0, "description": "蒙版边缘羽化程度。范围：0.0-1.0。0.0为锐利边缘，1.0为最大柔化"},
                "mask_invert": {"type": "boolean", "default": False, "description": "是否反转蒙版。false：显示蒙版内部区域，true：显示蒙版外部区域"},
                "mask_rect_width": {"type": ["number", "null"], "default": None, "description": "【矩形蒙版专用】矩形宽度。归一化比例：1.0为画布宽度。仅当mask_type为rectangle时有效"},
                "mask_round_corner": {"type": ["number", "null"], "default": None, "description": "【矩形蒙版专用】矩形圆角半径。范围：0-100。0为直角，100为最圆润。仅当mask_type为rectangle时有效"},
                "background_blur": {"type": "integer", "description": "背景模糊强度等级。范围：1-4。1为轻微模糊，4为最强模糊。用于创建素材周围的虚化背景效果"}
            },
            "required": ["video_url", "draft_id", "duration", "target_start"]
        }
    },
    {
        "name": "add_audio",
        "description": "添加音频轨道到草稿时间线。支持音频裁剪、音效处理、音量控制、变速等功能。可用于背景音乐、配音、音效等场景。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_url": {"type": "string", "description": "音频素材文件的URL地址或本地文件路径。支持常见音频格式：mp3、wav、aac、m4a等"},
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "start": {"type": "number", "default": 0, "description": "【素材裁剪-入点】从原始音频素材的第几秒开始截取。对应source_timerange的起始位置。例如：2.5表示从素材的2.5秒位置开始裁剪"},
                "end": {"type": ["number", "null"], "default": None, "description": "【素材裁剪-出点】到原始音频素材的第几秒结束截取。None、0或负数表示截取到素材末尾。例如：5.0表示裁剪到素材的5秒位置。注意：如果end<=start会导致空片段"},
                "target_start": {"type": "number", "default": 0, "description": "【时间线位置】该音频片段在成片时间线上的起始时间点（秒）。对应target_timerange的起始位置。例如：10.0表示这段音频从成片的第10秒开始播放"},
                "volume": {"type": "number", "default": 1.0, "description": "音量增益倍数。范围：0.0-2.0（实现中为0.0-1.0，但支持>1.0）。0.0为静音，1.0为原始音量，>1.0为放大"},
                "speed": {"type": "number", "default": 1.0, "description": "音频播放速率。范围：0.1-100（理论值）。1.0为正常速度，2.0为2倍速（加速），0.5为0.5倍速（减速）。影响最终片段时长：target_duration = source_duration / speed"},
                "track_name": {"type": "string", "default": "audio_main", "description": "音频轨道名称标识。建议命名：audio_main（主背景音乐）、audio_voice（人声配音）、audio_sfx（音效轨）。会自动创建不存在的轨道"},
                "duration": {"type": ["number", "null"], "default": None, "description": "【性能优化】原始音频素材的总时长（秒）。提前提供可避免重复解析素材，显著提升处理速度。null表示使用默认值0.0，实际时长在下载时获取"},
                "effect_type": {"type": "string", "description": "音效处理类型名称。根据IS_CAPCUT_ENV自动选择：CapCut环境支持CapCutVoiceFiltersEffectType/CapCutVoiceCharactersEffectType/CapCutSpeechToSongEffectType；剪映环境支持AudioSceneEffectType/ToneEffectType/SpeechToSongType"},
                "effect_params": {"type": "array", "description": "音效参数数组。参数的具体含义和数量取决于effect_type。格式：List[Optional[float]]。例如：某些效果可能需要[0.5, 1.0]"},
            },
            "required": ["audio_url", "draft_id", "start", "target_start"]
        }
    },
    {
        "name": "batch_add_audios",
        "description": """批量添加多个音频素材到track。适用于需要连续添加多个音频的场景。每个音频可以独立设置audio_url、start、end、target_start、speed、duration参数，其他参数（如音量、音效等）在所有音频间共享。
        
        【使用场景】
        • 音频拼接：将多个音频片段按顺序拼接成完整音轨
        • 批量导入：一次性导入多个音频素材
        • 配乐组合：制作多段配乐混合效果
        
        【audios数组说明】
        每个音频对象包含：
        • audio_url（必需）：音频素材URL或本地路径
        • start（可选，默认0）：从音频第几秒开始截取
        • end（可选，默认None）：到音频第几秒结束截取（None表示到末尾）
        • target_start（可选，默认0）：该片段在时间线上的起始位置
        • speed（可选，默认1.0）：播放速度
        • duration（可选，默认None）：音频素材总时长
        
        【共享参数】
        其他参数（volume、track_name、effect_type、effect_params等）在根级别设置，应用于所有音频
        """,
        "inputSchema": {
            "type": "object",
            "properties": {
                "audios": {
                    "type": "array",
                    "description": "音频素材列表数组",
                    "items": {
                        "type": "object",
                        "properties": {
                            "audio_url": {"type": "string", "description": "音频素材URL或本地路径"},
                            "start": {"type": "number", "default": 0, "description": "从音频素材第几秒开始截取"},
                            "end": {"type": ["number", "null"], "default": None, "description": "到音频素材第几秒结束截取（None=到末尾）"},
                            "target_start": {"type": "number", "default": 0, "description": "该片段在时间线上的起始位置"},
                            "speed": {"type": "number", "default": 1.0, "description": "播放速度"},
                            "duration": {"type": ["number", "null"], "default": None, "description": "音频素材总时长（秒）"}
                        },
                        "required": ["audio_url", "start", "target_start", "end", "speed", "duration"]
                    }
                },
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "volume": {"type": "number", "default": 1.0, "description": "【共享】音量增益（应用于所有音频）"},
                "track_name": {"type": "string", "default": "audio_main", "description": "【共享】轨道名称"},
                "effect_type": {"type": "string", "description": "【共享】音效处理类型"},
                "effect_params": {"type": "array", "description": "【共享】音效参数数组"}
            },
            "required": ["audios", "draft_id"]
        }
    },
    {
        "name": "add_image",
        "description": "添加图片素材到草稿时间线。支持图片动画、转场效果、蒙版遮罩、背景模糊等视觉效果。适用于静态图片展示、照片墙、图片过渡等场景。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_url": {"type": "string", "description": "图片素材文件的URL地址或本地文件路径。支持常见图片格式：png、jpg、jpeg、webp等"},
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "start": {"type": "number", "default": 0, "description": "【时间线位置-起点】图片在成片时间线上的起始时间点（秒）。对应target_timerange的起始位置。例如：0表示从成片开头开始显示"},
                "end": {"type": "number", "default": 3.0, "description": "【时间线位置-终点】图片在成片时间线上的结束时间点（秒）。对应target_timerange的结束位置。例如：3.0表示显示到成片的第3秒。图片显示时长 = end - start"},
                "transform_x": {"type": "number", "default": 0, "description": "【空间定位-X轴】图片素材在画布上的水平位置偏移。单位：半个画布宽度。0为画布中心，-1为向左偏移半个画布宽，1为向右偏移半个画布宽"},
                "transform_y": {"type": "number", "default": 0, "description": "【空间定位-Y轴】图片素材在画布上的垂直位置偏移。单位：半个画布高度。0为画布中心，-1为向上偏移半个画布高，1为向下偏移半个画布高"},
                "scale_x": {"type": "number", "default": 1, "description": "【缩放-X轴】水平缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "scale_y": {"type": "number", "default": 1, "description": "【缩放-Y轴】垂直缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "track_name": {"type": "string", "default": "main", "description": "视频轨道名称标识。建议命名：main（主轨道）、overlay（叠加层）、background（背景层）。会自动创建不存在的轨道"},
                "relative_index": {"type": "integer", "default": 0, "description": "同轨道内素材的相对排序索引。0为最早，数值越大越靠后。用于精确控制素材在轨道内的前后顺序和Z轴层级"},
                "intro_animation": {"type": "string", "description": "入场动画效果名称。图片出现时的动画效果，需与系统支持的动画类型匹配。根据IS_CAPCUT_ENV自动选择CapCutIntroType或IntroType"},
                "intro_animation_duration": {"type": "number", "default": 0.5, "description": "入场动画持续时长（秒）。建议范围：0.3-2.0秒。单位会自动转换为微秒（×1e6）"},
                "outro_animation": {"type": "string", "description": "出场动画效果名称。图片消失时的动画效果，需与系统支持的动画类型匹配。根据IS_CAPCUT_ENV自动选择CapCutOutroType或OutroType"},
                "outro_animation_duration": {"type": "number", "default": 0.5, "description": "出场动画持续时长（秒）。建议范围：0.3-2.0秒。单位会自动转换为微秒（×1e6）"},
                "combo_animation": {"type": "string", "description": "组合动画效果名称。同时包含入场和出场的预设动画组合。根据IS_CAPCUT_ENV自动选择CapCutGroupAnimationType或GroupAnimationType"},
                "combo_animation_duration": {"type": "number", "default": 0.5, "description": "组合动画总持续时长（秒）。会平均分配给入场和出场。单位会自动转换为微秒（×1e6）"},
                "transition": {"type": "string", "description": "转场效果类型名称。应用于当前素材与前一个素材之间的过渡效果。根据IS_CAPCUT_ENV自动选择CapCutTransitionType或TransitionType"},
                "transition_duration": {"type": "number", "default": 0.5, "description": "转场效果持续时长（秒）。建议范围：0.3-2.0秒。转场会占用前后两个素材各一半的时长。单位会自动转换为微秒（×1e6）"},
                "mask_type": {"type": "string", "description": "蒙版形状类型。可选：Linear（线性）、Mirror（镜像）、Circle（圆形）、Rectangle（矩形）、Heart（心形）、Star（星形）。根据IS_CAPCUT_ENV自动选择CapCutMaskType或MaskType"},
                "mask_center_x": {"type": "number", "default": 0.0, "description": "【歧义警告】蒙版中心点-X坐标。代码逻辑显示应输入像素值,但转换公式center_x/(画布宽/2)与示例代码0.5=居中矛盾。建议:按归一化使用(0.0=画布最左,0.5=画布中心,1.0=画布最右),或测试后根据实际效果调整"},
                "mask_center_y": {"type": "number", "default": 0.0, "description": "【歧义警告】蒙版中心点-Y坐标。代码逻辑显示应输入像素值,但转换公式center_y/(画布高/2)与示例代码0.5=居中矛盾。建议:按归一化使用(0.0=画布最上,0.5=画布中心,1.0=画布最下),或测试后根据实际效果调整"},
                "mask_size": {"type": "number", "default": 0.5, "description": "蒙版主尺寸大小。表示为素材高度的比例。0.0为不可见，0.5为素材高度的一半，1.0为素材高度。支持超过1.0"},
                "mask_rotation": {"type": "number", "default": 0.0, "description": "蒙版旋转角度（度）。范围：0-360。顺时针旋转"},
                "mask_feather": {"type": "number", "default": 0.0, "description": "蒙版边缘羽化程度。范围：0.0-100.0。0.0为锐利边缘，100.0为最大柔化"},
                "mask_invert": {"type": "boolean", "default": False, "description": "是否反转蒙版。false：显示蒙版内部区域，true：显示蒙版外部区域"},
                "mask_rect_width": {"type": ["number", "null"], "default": None, "description": "【矩形蒙版专用】矩形宽度。表示为素材宽度的比例。例如：1.0为素材全宽。仅当mask_type为Rectangle时有效"},
                "mask_round_corner": {"type": ["number", "null"], "default": None, "description": "【矩形蒙版专用】矩形圆角半径。范围：0-100。0为直角，100为最圆润。仅当mask_type为Rectangle时有效"},
                "background_blur": {"type": "integer", "description": "背景模糊强度等级。范围：1-4。对应模糊值：1=0.0625（轻微），2=0.375（中等），3=0.75（强烈），4=1.0（最大）。用于创建素材周围的虚化背景效果"}
            },
            "required": ["image_url", "draft_id", "start", "end"]
        }
    },
    {
        "name": "add_text",
        "description": "添加文本字幕到草稿时间线。支持丰富的文本样式、描边、背景、阴影、入出场动画等。适用于字幕、标题、艺术字等场景。建议：艺术字可居中放置在显眼位置，常规字幕应选择清晰易读的字体。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "文本内容。支持多行文本"},
                "start": {"type": "number", "description": "【时间线位置-起点】文本在成片时间线上的起始时间点（秒）。对应trange的起始位置"},
                "end": {"type": "number", "description": "【时间线位置-终点】文本在成片时间线上的结束时间点（秒）。对应trange的结束位置。文本显示时长 = end - start"},
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "default": "text_main", "description": "文本轨道名称标识。建议命名：text_main（主字幕轨）、text_title（标题轨）、text_caption（说明轨）。会自动创建不存在的轨道。必需参数"},
                "font": {"type": "string", "description": "字体名称。必须是FontType中支持的字体。不设置则使用null（系统默认字体）。必需参数"},
                "font_size": {"type": "integer", "default": 8, "description": "字体大小。建议范围：4.0-20.0。数值越大字体越大"},
                "font_color": {"type": "string", "default": "#ffffff", "description": "字体颜色。十六进制格式：#RRGGBB。例如：#ffffff为白色，#000000为黑色。会自动转换为RGB元组"},
                "font_alpha": {"type": "number", "default": 1.0, "description": "字体透明度。范围：0.0-1.0。0.0为完全透明，1.0为完全不透明。有效性会被验证"},
                "transform_x": {"type": "number", "default": 0, "description": "【空间定位-X轴】文本在画布上的水平位置偏移。单位：半个画布宽度。0为画布中心，-1为向左偏移半个画布宽，1为向右偏移半个画布宽"},
                "transform_y": {"type": "number", "default": -0.8, "description": "【空间定位-Y轴】文本在画布上的垂直位置偏移。单位：半个画布高度。0为画布中心，-1为画布顶部，1为画布底部。默认-0.8表示屏幕底部位置（字幕常用，向上偏移0.4倍画布高）"},
                "align": {"type": "integer", "default": 1, "description": "文本对齐方式。0=左对齐，1=居中对齐，2=右对齐"},
                "vertical": {"type": "boolean", "default": False, "description": "是否垂直显示文本。false=水平文本，true=垂直文本"},
                "fixed_width": {"type": "number", "default": 0.7, "description": "文本框固定宽度比例。范围：0.0-1.0（相对画布宽度）。-1表示不固定宽度（自动适应）。默认0.7表示占画布宽度70%"},
                "fixed_height": {"type": "number", "default": -1, "description": "文本框固定高度比例。范围：0.0-1.0（相对画布高度）。-1表示不固定高度（自动适应）。会转换为像素值"},
                "border_alpha": {"type": "number", "default": 1.0, "description": "描边透明度。范围：0.0-1.0。0.0为完全透明，1.0为完全不透明。有效性会被验证"},
                "border_color": {"type": "string", "default": "#000000", "description": "描边颜色。十六进制格式：#RRGGBB。例如：#000000为黑色。会自动转换为RGB元组"},
                "border_width": {"type": "number", "default": 0.0, "description": "描边宽度。0.0表示无描边。大于0时会创建Text_border对象"},
                "background_color": {"type": "string", "default": "#000000", "description": "背景颜色。十六进制格式：#RRGGBB"},
                "background_style": {"type": "integer", "default": 1, "description": "背景样式类型。具体样式需与实现支持的样式匹配"},
                "background_alpha": {"type": "number", "default": 0.0, "description": "背景透明度。范围：0.0-1.0。0.0为无背景（默认），1.0为完全不透明。大于0时会创建Text_background对象。有效性会被验证"},
                "background_round_radius": {"type": "number", "default": 0.0, "description": "背景圆角半径。范围：0.0-1.0。0.0为直角，1.0为最圆"},
                "background_height": {"type": "number", "default": 0.14, "description": "背景高度比例。范围：0.0-1.0（相对画布高度）"},
                "background_width": {"type": "number", "default": 0.14, "description": "背景宽度比例。范围：0.0-1.0（相对画布宽度）"},
                "background_horizontal_offset": {"type": "number", "default": 0.5, "description": "背景水平偏移。范围：0.0-1.0。0.5表示居中"},
                "background_vertical_offset": {"type": "number", "default": 0.5, "description": "背景垂直偏移。范围：0.0-1.0。0.5表示居中"},
                "shadow_enabled": {"type": "boolean", "default": False, "description": "是否启用阴影效果。true时会创建Text_shadow对象"},
                "shadow_alpha": {"type": "number", "default": 0.9, "description": "阴影透明度。范围：0.0-1.0。建议值：0.7-0.9"},
                "shadow_angle": {"type": "number", "default": -45.0, "description": "阴影投射角度。范围：-180.0至180.0（度）。-45表示左上方"},
                "shadow_color": {"type": "string", "default": "#000000", "description": "阴影颜色。十六进制格式：#RRGGBB"},
                "shadow_distance": {"type": "number", "default": 5.0, "description": "阴影距离。数值越大阴影越远"},
                "shadow_smoothing": {"type": "number", "default": 0.15, "description": "阴影平滑度（模糊程度）。范围：0.0-1.0。0.0为锐利，1.0为最柔和"},
                "intro_animation": {"type": "string", "description": "入场动画类型名称。文本出现时的动画效果。根据IS_CAPCUT_ENV自动选择CapCutTextIntro或TextIntro"},
                "intro_duration": {"type": "number", "default": 0.5, "description": "入场动画持续时长（秒）。单位会自动转换为微秒（×1e6）"},
                "outro_animation": {"type": "string", "description": "出场动画类型名称。文本消失时的动画效果。根据IS_CAPCUT_ENV自动选择CapCutTextOutro或TextOutro"},
                "outro_duration": {"type": "number", "default": 0.5, "description": "出场动画持续时长（秒）。单位会自动转换为微秒（×1e6）"},
                "italic": {"type": "boolean", "default": False, "description": "是否斜体。应用于Text_style。注意：与bold/underline可能存在互斥关系（取决于字体）"},
                "bold": {"type": "boolean", "default": False, "description": "是否加粗。应用于Text_style"},
                "underline": {"type": "boolean", "default": False, "description": "是否下划线。应用于Text_style"}
            },
            "required": ["text", "font", "start", "end", "track_name"]
        }
    },
    # {
    #     "name": "add_subtitle",
    #     "description": "添加字幕到草稿，支持SRT文件和样式设置",
    #     "inputSchema": {
    #         "type": "object",
    #         "properties": {
    #             "srt": {"type": "string", "description": "字幕内容或SRT文件URL（支持直接传字幕文本或文件路径/URL）"},
    #             "draft_id": {"type": "string", "description": "草稿ID（用于指定要添加字幕的草稿）"},
    #             "time_offset": {"type": "number", "default": 0.0, "description": "字幕时间偏移量（秒，可整体调整字幕显示时间）"},
    #             "font_size": {"type": "number", "default": 8.0, "description": "字体大小"},
    #             "font": {"type": "string", "description": "字体"},
    #             "bold": {"type": "boolean", "default": False, "description": "是否加粗"},
    #             "italic": {"type": "boolean", "default": False, "description": "是否斜体"},
    #             "underline": {"type": "boolean", "default": False, "description": "是否下划线"},
    #             "font_color": {"type": "string", "default": "#FFFFFF", "description": "字体颜色（支持十六进制色值）"},
    #             "align": {"type": "integer", "default": 1, "description": "对齐方式：0左 1中 2右"},
    #             "vertical": {"type": "boolean", "default": False, "description": "是否垂直显示"},
    #             "alpha": {"type": "number", "default": 1.0, "description": "字体透明度（范围0-1）"},
    #             "border_alpha": {"type": "number", "default": 1.0, "description": "边框透明度"},
    #             "border_color": {"type": "string", "default": "#000000", "description": "边框颜色"},
    #             "border_width": {"type": "number", "default": 0.0, "description": "边框宽度"},
    #             "background_color": {"type": "string", "default": "#000000", "description": "背景颜色"},
    #             "background_style": {"type": "integer", "default": 1, "description": "背景样式（需与实现支持的样式匹配）"},
    #             "background_alpha": {"type": "number", "default": 0.0, "description": "背景透明度"},
    #             "transform_x": {"type": "number", "default": 0.0, "description": "X轴位置偏移"},
    #             "transform_y": {"type": "number", "default": -0.8, "description": "Y轴位置偏移"},
    #             "scale_x": {"type": "number", "default": 1.0, "description": "X轴缩放比例"},
    #             "scale_y": {"type": "number", "default": 1.0, "description": "Y轴缩放比例"},
    #             "rotation": {"type": "number", "default": 0.0, "description": "旋转角度（度）"},
    #             "track_name": {"type": "string", "default": "subtitle", "description": "轨道名称"},
    #         },
    #         "required": ["srt"]
    #     }
    # },
    {
        "name": "add_effect",
        "description": "添加视频特效到草稿时间线。支持场景特效和人物特效两大类。推荐开头使用的5种特效：冲刺、放大镜、逐渐放大、聚光灯、夸夸弹幕。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "effect_type": {"type": "string", "description": "特效类型名称。根据effect_category和IS_CAPCUT_ENV自动选择：scene分类使用VideoSceneEffectType或CapCutVideoSceneEffectType；character分类使用VideoCharacterEffectType或CapCutVideoCharacterEffectType"},
                "effect_category": {"type": "string", "default": "scene", "enum": ["scene", "character"], "description": "特效分类。scene=场景特效（如光效、粒子），character=人物特效（如美颜、变形）"},
                "start": {"type": "number", "default": 0, "description": "【时间线位置-起点】特效在成片时间线上的起始时间点（秒）。对应trange的起始位置"},
                "end": {"type": "number", "default": 3.0, "description": "【时间线位置-终点】特效在成片时间线上的结束时间点（秒）。对应trange的结束位置。特效显示时长 = end - start"},
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符。未传或不存在时自动创建新草稿"},
                "track_name": {"type": "string", "default": "effect_01", "description": "特效轨道名称标识。建议命名：effect_01、effect_scene、effect_character。会自动创建不存在的轨道"},
                "params": {"type": "array", "description": "特效参数数组。格式：List[Optional[float]]。参数的具体含义取决于effect_type。未提供或为None的参数项将使用默认值"},
            },
            "required": ["effect_type"]
        }
    },
    {
        "name": "add_sticker",
        "description": "添加贴纸到草稿时间线。支持位置、缩放、旋转、透明度、翻转等变换。适用于装饰、表情、图标等场景。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource_id": {"type": "string", "description": "贴纸资源的唯一标识符。需要从系统资源库获取有效的resource_id"},
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "start": {"type": "number", "description": "【时间线位置-起点】贴纸在成片时间线上的起始时间点（秒）。对应trange的起始位置"},
                "end": {"type": "number", "description": "【时间线位置-终点】贴纸在成片时间线上的结束时间点（秒）。对应trange的结束位置。贴纸显示时长 = end - start"},
                "transform_x": {"type": "number", "default": 0, "description": "【空间定位-X轴】贴纸在画布上的水平位置偏移。单位：半个画布宽度。0为画布中心，-1为向左偏移半个画布宽，1为向右偏移半个画布宽"},
                "transform_y": {"type": "number", "default": 0, "description": "【空间定位-Y轴】贴纸在画布上的垂直位置偏移。单位：半个画布高度。0为画布中心，-1为向上偏移半个画布高，1为向下偏移半个画布高"},
                "scale_x": {"type": "number", "default": 1.0, "description": "【缩放-X轴】水平缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "scale_y": {"type": "number", "default": 1.0, "description": "【缩放-Y轴】垂直缩放倍数。1.0为原始大小，0.5为缩小一半，2.0为放大两倍"},
                "alpha": {"type": "number", "default": 1.0, "description": "贴纸透明度。范围：0.0-1.0。0.0为完全透明，1.0为完全不透明"},
                "rotation": {"type": "number", "default": 0.0, "description": "贴纸旋转角度（度）。顺时针旋转，可以是正值或负值"},
                "track_name": {"type": "string", "default": "sticker_main", "description": "贴纸轨道名称标识。建议命名：sticker_main、sticker_emoji、sticker_decoration。会自动创建不存在的轨道"},
            },
            "required": ["resource_id", "start", "end", "draft_id"]
        }
    },
    {
        "name": "add_video_keyframe",
        "description": "添加视频关键帧动画。支持位置、缩放、旋转、透明度、饱和度、对比度、亮度、音量等属性的关键帧动画。可实现平滑的属性变化效果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "default": "main", "description": "视频轨道名称。指定要添加关键帧的轨道"},
                "property_type": {"type": "string", "description": "【单个模式】关键帧属性类型。可选值：position_x（X位置）、position_y（Y位置）、rotation（旋转）、scale_x（X缩放）、scale_y（Y缩放）、uniform_scale（统一缩放）、alpha（透明度）、saturation（饱和度）、contrast（对比度）、brightness（亮度）、volume（音量）"},
                "time": {"type": "number", "default": 0.0, "description": "【单个模式】关键帧时间点（秒）。在时间线上的绝对时间位置"},
                "value": {"type": "string", "description": "【单个模式】关键帧值。具体格式取决于property_type。例如：位置可能是数值，颜色可能是#RRGGBB"},
                "property_types": {"type": "array", "description": "【批量模式】关键帧属性类型列表。与times和values一一对应，用于批量添加多个关键帧"},
                "times": {"type": "array", "description": "【批量模式】关键帧时间点列表（秒）。与property_types和values一一对应"},
                "values": {"type": "array", "description": "【批量模式】关键帧值列表。与property_types和times一一对应"}
            },
            "required": ["draft_id", "track_name"]
        }
    },
    {
        "name": "generate_video",
        "description": "导出草稿为视频文件。将编辑好的草稿渲染成最终的视频文件，支持多种分辨率和帧率配置。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "要导出的草稿的唯一标识符"},
                "resolution": {"type": "string", "enum": ["1080P", "2K", "4K"], "description": "导出视频分辨率。1080P=1920×1080，2K=2560×1440，4K=3840×2160", "default": "1080P"},
                "framerate": {"type": "string", "enum": ["30fps", "50fps", "60fps"], "description": "导出视频帧率。30fps适合常规视频，50/60fps适合高动态画面", "default": "30fps"},
                "name": {"type": "string", "description": "导出视频的文件名称（不含扩展名）"}
            },
            "required": ["draft_id"]
        }
    },
    {
        "name": "get_video_task_status",
        "description": "查询视频渲染任务的状态。返回任务的详细信息，包括渲染状态、进度、错误信息等。用于跟踪generate_video生成的任务进度。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "视频任务的唯一标识符。由generate_video返回的final_task_id"}
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "get_font_types",
        "description": "获取系统支持的字体类型列表。返回FontType枚举中所有可用的字体名称，用于add_text的font参数。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_audio_effect_types",
        "description": "获取系统支持的音频特效类型列表。返回AudioSceneEffectType、ToneEffectType、SpeechToSongType等枚举中的音效名称，用于add_audio的effect_type参数。",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_tracks",
        "description": "获取草稿中的所有轨道信息。返回轨道列表，包括轨道名称、类型、渲染索引、静音状态、片段数量和结束时间等详细信息。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"}
            },
            "required": ["draft_id"]
        }
    },
    {
        "name": "delete_track",
        "description": "从草稿中删除指定的轨道。删除轨道及其所有片段，并更新草稿的总时长。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "description": "要删除的轨道名称"}
            },
            "required": ["draft_id", "track_name"]
        }
    },
    {
        "name": "get_track_details",
        "description": "获取指定轨道的详细信息。返回轨道的完整信息，包括所有片段的详细信息（开始时间、结束时间、持续时间和类型）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "description": "要查询的轨道名称"}
            },
            "required": ["draft_id", "track_name"]
        }
    },
    {
        "name": "get_segment_details",
        "description": "获取指定片段的详细信息。返回片段的完整属性，包括时间范围、素材信息、视觉效果、动画、滤镜、蒙版、特效等。支持视频、音频、文本、贴纸、特效等各类片段。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "description": "包含该片段的轨道名称"},
                "segment_id": {"type": "string", "description": "要查询的片段的唯一标识符"}
            },
            "required": ["draft_id", "track_name", "segment_id"]
        }
    },
    {
        "name": "delete_segment",
        "description": "从轨道中删除指定的片段。可以通过片段索引（segment_index）或片段ID（segment_id）来删除。删除后会自动更新草稿状态并返回剩余片段数量。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "目标草稿的唯一标识符"},
                "track_name": {"type": "string", "description": "包含该片段的轨道名称"},
                "segment_index": {"type": ["integer", "null"], "default": None, "description": "要删除的片段在轨道中的索引位置（从0开始）。与segment_id互斥，二者必须且只能提供一个"},
                "segment_id": {"type": ["string", "null"], "default": None, "description": "要删除的片段的唯一标识符。与segment_index互斥，二者必须且只能提供一个"}
            },
            "required": ["draft_id", "track_name"]
        }
    }
]

@contextlib.contextmanager
def capture_stdout():
    """捕获标准输出，防止CapCut API的调试信息干扰JSON响应"""
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        yield sys.stdout
    finally:
        sys.stdout = old_stdout


def format_validation_error(error_type: str, current_values: dict, suggestions: list[str]) -> str:
    """格式化验证错误消息

    Args:
        error_type: 错误类型描述
        current_values: 当前参数值字典
        suggestions: 修复建议列表

    Returns:
        格式化的错误消息字符串
    """
    error_msg = f"❌ 参数错误：{error_type}\n"

    if current_values:
        error_msg += "当前："
        error_msg += ", ".join([f"{k}={v}" for k, v in current_values.items()])
        error_msg += "\n"

    if suggestions:
        error_msg += "建议：\n"
        for suggestion in suggestions:
            error_msg += f"  • {suggestion}\n"

    return error_msg.rstrip()


def convert_text_styles(text_styles_data):
    """将字典格式的text_styles转换为TextStyleRange对象列表"""
    if not text_styles_data:
        return None

    try:
        text_style_ranges = []
        for style_dict in text_styles_data:
            start_idx = style_dict.get("start", 0)
            end_idx = style_dict.get("end", 0)

            style_obj = style_dict.get("style", {})
            border_obj = style_dict.get("border")
            font_str = style_dict.get("font")

            # 构建 Text_style
            text_style = Text_style(
                size=style_obj.get("size", 8.0),
                bold=style_obj.get("bold", False),
                italic=style_obj.get("italic", False),
                underline=style_obj.get("underline", False),
                color=hex_to_rgb(style_obj.get("color", "#FFFFFF")),
                alpha=1.0,
                align=1,
                vertical=False,
                letter_spacing=0,
                line_spacing=0,
            )

            # 构建 Text_border（可选）
            text_border = None
            if border_obj:
                text_border = Text_border(
                    alpha=border_obj.get("alpha", 1.0),
                    color=hex_to_rgb(border_obj.get("color", "#000000")),
                    width=border_obj.get("width", 0.0)
                )

            style_range = TextStyleRange(
                start=start_idx,
                end=end_idx,
                style=text_style,
                border=text_border,
                font_str=font_str
            )
            text_style_ranges.append(style_range)
        return text_style_ranges
    except Exception as e:
        print(f"[ERROR] Error converting text_styles: {e}", file=sys.stderr)
        return None

def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """执行具体的工具"""
    try:
        print(f"[DEBUG] Executing tool: {tool_name} with args: {arguments}", file=sys.stderr)

        # ========== 检查CapCut模块可用性 ==========
        if not CAPCUT_AVAILABLE:
            return {"success": False, "error": "CapCut modules not available"}

        # ========== 原有的工具执行逻辑 ==========
        # 捕获标准输出，防止调试信息干扰
        with capture_stdout():
            if tool_name == "add_audio":
                # 将 effect_type/effect_params 映射为实现所需的 sound_effects
                effect_type = arguments.pop("effect_type", None)
                effect_params = arguments.pop("effect_params", None)
                if effect_type:
                    if effect_params is None:
                        effect_params = []
                    # 如果已存在 sound_effects，追加；否则创建
                    existing_effects = arguments.get("sound_effects")
                    if existing_effects:
                        existing_effects.append((effect_type, effect_params))
                    else:
                        arguments["sound_effects"] = [(effect_type, effect_params)]
                result = add_audio_track(**arguments)

            elif tool_name == "add_image":
                result = add_image_impl(**arguments)

            elif tool_name == "add_subtitle":
                # 兼容字段：将 srt 映射为实现参数 srt_path
                if "srt" in arguments and "srt_path" not in arguments:
                    arguments["srt_path"] = arguments.pop("srt")
                result = add_subtitle_impl(**arguments)

            elif tool_name == "add_sticker":
                result = add_sticker_impl(**arguments)

            elif tool_name == "add_video_keyframe":
                result = add_video_keyframe_impl(**arguments)

            elif tool_name == "get_video_task_status":
                from services.get_video_task_status_impl import get_video_task_status_impl
                result = get_video_task_status_impl(**arguments)
                return result

            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}

        return {
            "success": True,
            "result": result
        }

    except Exception as e:
        print(f"[ERROR] Tool execution error: {e}", file=sys.stderr)
        print(f"[ERROR] Traceback: {traceback.format_exc()}", file=sys.stderr)
        return {"success": False, "error": str(e)}
