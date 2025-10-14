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
        "name": "add_video",
        "description": "添加视频到草稿，支持转场、蒙版、背景模糊等效果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "video_url": {"type": "string", "description": "视频资源URL（用于获取视频素材）"},
                "start": {"type": "number", "default": 0, "description": "视频素材的起始截取时间（秒）"},
                "end": {"type": "number", "default": 0, "description": "视频素材的结束截取时间（秒，0表示截取至视频末尾）"},
                "width": {"type": "integer", "default": 1080, "description": "画布宽度"},
                "height": {"type": "integer", "default": 1920, "description": "画布高度"},
                "draft_id": {"type": "string", "description": "草稿ID"},
                "transform_x": {"type": "number", "default": 0, "description": "X轴位置偏移"},
                "transform_y": {"type": "number", "default": 0, "description": "Y轴位置偏移"},
                "scale_x": {"type": "number", "default": 1, "description": "X轴缩放比例"},
                "scale_y": {"type": "number", "default": 1, "description": "Y轴缩放比例"},
                "speed": {"type": "number", "default": 1.0, "description": "视频播放速度（大于1为加速，小于1为减速）"},
                "target_start": {"type": "number", "default": 0, "description": "视频在时间线上的起始位置（秒）"},
                "track_name": {"type": "string", "default": "video_main", "description": "轨道名称"},
                "relative_index": {"type": "integer", "default": 0, "description": "相对索引（用于控制轨道内素材的排列顺序）"},
                "intro_animation": {"type": "string", "description": "入场动画"},
                "intro_animation_duration": {"type": "number", "default": 0.5, "description": "入场动画时长（秒）"},
                "outro_animation": {"type": "string", "description": "出场动画"},
                "outro_animation_duration": {"type": "number", "default": 0.5, "description": "出场动画时长（秒）"},
                "combo_animation": {"type": "string", "description": "组合动画"},
                "combo_animation_duration": {"type": "number", "default": 0.5, "description": "组合动画时长（秒）"},
                "duration": {"type": ["number", "null"], "default": None, "description": "视频素材的总时长（秒，主动设置可提升运行速度）"},
                "transition": {"type": "string", "description": "转场类型（需与支持的类型匹配）"},
                "transition_duration": {"type": "number", "default": 0.5, "description": "转场持续时间（秒）"},
                "volume": {"type": "number", "default": 1.0, "description": "视频音量（0.0-1.0）"},
                "filter_type": {"type": "string", "description": "滤镜类型（需与支持的类型匹配）"},
                "filter_intensity": {"type": "number", "default": 100.0, "description": "滤镜强度（0-100）"},
                "fade_in_duration": {"type": "number", "default": 0.0, "description": "音频淡入时长（秒）"},
                "fade_out_duration": {"type": "number", "default": 0.0, "description": "音频淡出时长（秒）"},
                "mask_type": {"type": "string", "description": "蒙版类型（如圆形、矩形等）"},
                "mask_center_x": {"type": "number", "default": 0.5, "description": "蒙版中心X坐标（0-1）"},
                "mask_center_y": {"type": "number", "default": 0.5, "description": "蒙版中心Y坐标（0-1）"},
                "mask_size": {"type": "number", "default": 1.0, "description": "蒙版大小（相对尺寸0-1）"},
                "mask_rotation": {"type": "number", "default": 0.0, "description": "蒙版旋转角度（度）"},
                "mask_feather": {"type": "number", "default": 0.0, "description": "蒙版羽化程度（0-1）"},
                "mask_invert": {"type": "boolean", "default": False, "description": "是否反转蒙版"},
                "mask_rect_width": {"type": ["number", "null"], "default": None, "description": "矩形蒙版宽度（仅矩形有效）"},
                "mask_round_corner": {"type": ["number", "null"], "default": None, "description": "矩形蒙版圆角（0-100，仅矩形有效）"},
                "background_blur": {"type": "integer", "description": "背景模糊级别(数字范围1-4)"}
            },
            "required": ["video_url", "draft_id"]
        }
    },
    {
        "name": "add_audio",
        "description": "添加音频到草稿，支持音效处理",
        "inputSchema": {
            "type": "object",
            "properties": {
                "audio_url": {"type": "string", "description": "音频文件URL"},
                "draft_id": {"type": "string", "description": "草稿ID"},
                "start": {"type": "number", "default": 0, "description": "音频素材的起始截取时间（秒）"},
                "end": {"type": "number", "description": "音频素材的结束截取时间（秒，默认取完整音频长度）"},
                "target_start": {"type": "number", "default": 0, "description": "音频在时间线上的起始位置（秒）"},
                "volume": {"type": "number", "default": 1.0, "description": "音量大小"},
                "speed": {"type": "number", "default": 1.0, "description": "音频速度（>1加速，<1减速）"},
                "track_name": {"type": "string", "default": "audio_main", "description": "轨道名称"},
                "duration": {"type": ["number", "null"], "default": None, "description": "音频素材的总时长（秒），主动设置可以提升请求速度"},
                "effect_type": {"type": "string", "description": "音效类型"},
                "effect_params": {"type": "array", "description": "音效参数（根据effect_type设置）"},
                "width": {"type": "integer", "default": 1080, "description": "视频宽度"},
                "height": {"type": "integer", "default": 1920, "description": "视频高度"}
            },
            "required": ["audio_url", "draft_id"]
        }
    },
    {
        "name": "add_image",
        "description": "添加图片到草稿，支持动画、转场、蒙版等效果",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_url": {"type": "string", "description": "图片URL"},
                "draft_id": {"type": "string", "description": "草稿ID"},
                "start": {"type": "number", "default": 0, "description": "开始时间（秒）"},
                "end": {"type": "number", "default": 3.0, "description": "结束时间（秒）"},
                "width": {"type": "integer", "default": 1080, "description": "视频宽度"},
                "height": {"type": "integer", "default": 1920, "description": "视频高度"},
                "transform_x": {"type": "number", "default": 0, "description": "X轴位置"},
                "transform_y": {"type": "number", "default": 0, "description": "Y轴位置"},
                "scale_x": {"type": "number", "default": 1, "description": "X轴缩放"},
                "scale_y": {"type": "number", "default": 1, "description": "Y轴缩放"},
                "track_name": {"type": "string", "default": "main", "description": "轨道名称"},
                "relative_index": {"type": "integer", "default": 0, "description": "相对索引（用于控制轨道内素材的排列顺序）"},
                "intro_animation": {"type": "string", "description": "入场动画"},
                "intro_animation_duration": {"type": "number", "default": 0.5, "description": "入场动画时长（秒）"},
                "outro_animation": {"type": "string", "description": "出场动画"},
                "outro_animation_duration": {"type": "number", "default": 0.5, "description": "出场动画时长（秒）"},
                "combo_animation": {"type": "string", "description": "组合动画"},
                "combo_animation_duration": {"type": "number", "default": 0.5, "description": "组合动画时长（秒）"},
                "transition": {"type": "string", "description": "转场类型"},
                "transition_duration": {"type": "number", "default": 0.5, "description": "转场持续时间（秒）"},
                "mask_type": {"type": "string", "description": "蒙版类型"},
                "mask_center_x": {"type": "number", "default": 0.0, "description": "蒙版中心X坐标（0-1）"},
                "mask_center_y": {"type": "number", "default": 0.0, "description": "蒙版中心Y坐标（0-1）"},
                "mask_size": {"type": "number", "default": 0.5, "description": "蒙版主尺寸（相对大小0-1）"},
                "mask_rotation": {"type": "number", "default": 0.0, "description": "蒙版旋转角度（度）"},
                "mask_feather": {"type": "number", "default": 0.0, "description": "蒙版羽化程度（0-100）"},
                "mask_invert": {"type": "boolean", "default": False, "description": "是否反转蒙版"},
                "mask_rect_width": {"type": ["number", "null"], "default": None, "description": "矩形蒙版宽度（仅矩形有效）"},
                "mask_round_corner": {"type": ["number", "null"], "default": None, "description": "矩形蒙版圆角（0-100，仅矩形有效）"}
            },
            "required": ["image_url", "draft_id"]
        }
    },
    {
        "name": "add_text",
        "description": "添加文本到草稿，支持文本多样式、阴影、背景与入出场动画。-艺术字效果可以局中放置在显眼位置 -字幕格式可以挑选正经一点的字体",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "文本内容"},
                "start": {"type": "number", "description": "文本在时间线的起始时间（秒）"},
                "end": {"type": "number", "description": "文本在时间线的结束时间（秒）"},
                "draft_id": {"type": "string", "description": "草稿ID"},
                "transform_y": {"type": "number", "default": -0.8, "description": "Y轴变换参数"},
                "transform_x": {"type": "number", "default": 0, "description": "X轴变换参数"},
                "font": {"type": "string", "description": "字体"},
                "font_color": {"type": "string", "default": "#ffffff", "description": "字体颜色"},
                "font_size": {"type": "number", "default": 8.0, "description": "字体大小"},
                "track_name": {"type": "string", "default": "text_main", "description": "轨道名称"},
                "align": {"type": "integer", "default": 1, "description": "对齐方式：0左 1中 2右"},
                "vertical": {"type": "boolean", "default": False, "description": "是否垂直显示"},
                "font_alpha": {"type": "number", "default": 1.0, "description": "字体透明度"},
                "fixed_width": {"type": "number", "default": 0.7, "description": "固定宽度比例（-1表示不固定）"},
                "fixed_height": {"type": "number", "default": -1, "description": "固定高度比例（-1表示不固定）"},
                "border_alpha": {"type": "number", "default": 1.0, "description": "描边透明度"},
                "border_color": {"type": "string", "default": "#000000", "description": "描边颜色"},
                "border_width": {"type": "number", "default": 0.0, "description": "描边宽度"},
                "background_color": {"type": "string", "default": "#000000", "description": "背景颜色"},
                "background_style": {"type": "integer", "default": 1, "description": "背景样式"},
                "background_alpha": {"type": "number", "default": 0.0, "description": "背景透明度"},
                "background_round_radius": {"type": "number", "default": 0.0, "description": "背景圆角半径"},
                "background_height": {"type": "number", "default": 0.14, "description": "背景高度"},
                "background_width": {"type": "number", "default": 0.14, "description": "背景宽度"},
                "background_horizontal_offset": {"type": "number", "default": 0.5, "description": "背景水平偏移"},
                "background_vertical_offset": {"type": "number", "default": 0.5, "description": "背景垂直偏移"},
                "shadow_enabled": {"type": "boolean", "default": False, "description": "是否启用阴影"},
                "shadow_alpha": {"type": "number", "default": 0.9, "description": "阴影透明度"},
                "shadow_angle": {"type": "number", "default": -45.0, "description": "阴影角度"},
                "shadow_color": {"type": "string", "default": "#000000", "description": "阴影颜色"},
                "shadow_distance": {"type": "number", "default": 5.0, "description": "阴影距离"},
                "shadow_smoothing": {"type": "number", "default": 0.15, "description": "阴影平滑度"},
                "intro_animation": {"type": "string", "description": "入场动画类型"},
                "intro_duration": {"type": "number", "default": 0.5, "description": "入场动画持续时间（秒）"},
                "outro_animation": {"type": "string", "description": "出场动画类型"},
                "outro_duration": {"type": "number", "default": 0.5, "description": "出场动画持续时间（秒）"},
                "width": {"type": "integer", "default": 1080, "description": "画布宽度"},
                "height": {"type": "integer", "default": 1920, "description": "画布高度"},
                "italic": {"type": "boolean", "default": False, "description": "是否斜体（与bold/underline互斥）"},
                "bold": {"type": "boolean", "default": False, "description": "是否加粗"},
                "underline": {"type": "boolean", "default": False, "description": "是否下划线"},
                # "text_styles": {
                #     "type": "array",
                #     "description": "文本多样式配置列表",
                #     "items": {
                #         "type": "object",
                #         "properties": {
                #             "start": {"type": "integer", "description": "开始字符位置（包含）"},
                #             "end": {"type": "integer", "description": "结束字符位置（不包含）"},
                #             "style": {
                #                 "type": "object",
                #                 "properties": {
                #                     "size": {"type": "number", "description": "字体大小"},
                #                     "bold": {"type": "boolean"},
                #                     "italic": {"type": "boolean"},
                #                     "underline": {"type": "boolean"},
                #                     "color": {"type": "string", "description": "字体颜色#RRGGBB"}
                #                 }
                #             },
                #             "border": {
                #                 "type": "object",
                #                 "properties": {
                #                     "alpha": {"type": "number"},
                #                     "color": {"type": "string"},
                #                     "width": {"type": "number"}
                #                 }
                #             },
                #             "font": {"type": "string", "description": "局部字体"}
                #         }
                #     }
                # }
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
    #             "width": {"type": "integer", "default": 1080, "description": "画布宽度"},
    #             "height": {"type": "integer", "default": 1920, "description": "画布高度"}
    #         },
    #         "required": ["srt"]
    #     }
    # },
    {
        "name": "add_effect",
        "description": "添加特效到草稿。推荐：5种可以在视频开头使用的特效,冲刺、放大镜、逐渐放大、聚光灯、夸夸弹幕",
        "inputSchema": {
            "type": "object",
            "properties": {
                "effect_type": {"type": "string", "description": "特效类型名称（从系统支持的特效列表中选择，如: MV封面）"},
                "start": {"type": "number", "default": 0, "description": "特效开始时间（秒）"},
                "end": {"type": "number", "default": 3.0, "description": "特效结束时间（秒）"},
                "draft_id": {"type": "string", "description": "草稿ID（未传或不存在时可能自动创建新草稿）"},
                "track_name": {"type": "string", "default": "effect_01", "description": "特效轨道名称"},
                "params": {"type": "array", "description": "特效参数列表"},
                "width": {"type": "integer", "default": 1080, "description": "画布宽度"},
                "height": {"type": "integer", "default": 1920, "description": "画布高度"},
                "effect_category": {"type": "string", "default": "scene", "description": "特效分类：scene 或 character"}
            },
            "required": ["effect_type"]
        }
    },
    {
        "name": "add_sticker",
        "description": "添加贴纸到草稿",
        "inputSchema": {
            "type": "object",
            "properties": {
                "resource_id": {"type": "string", "description": "贴纸资源ID"},
                "draft_id": {"type": "string", "description": "草稿ID"},
                "start": {"type": "number", "description": "开始时间（秒）"},
                "end": {"type": "number", "description": "结束时间（秒）"},
                "transform_x": {"type": "number", "default": 0, "description": "X轴位置"},
                "transform_y": {"type": "number", "default": 0, "description": "Y轴位置"},
                "scale_x": {"type": "number", "default": 1.0, "description": "X轴缩放"},
                "scale_y": {"type": "number", "default": 1.0, "description": "Y轴缩放"},
                "alpha": {"type": "number", "default": 1.0, "description": "透明度"},
                "rotation": {"type": "number", "default": 0.0, "description": "旋转角度"},
                "track_name": {"type": "string", "default": "sticker_main", "description": "轨道名称"},
                "width": {"type": "integer", "default": 1080, "description": "视频宽度"},
                "height": {"type": "integer", "default": 1920, "description": "视频高度"}
            },
            "required": ["resource_id", "start", "end", "draft_id"]
        }
    },
    {
        "name": "add_video_keyframe",
        "description": "添加视频关键帧，支持位置、缩放、旋转、透明度等属性动画",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "草稿ID"},
                "track_name": {"type": "string", "default": "main", "description": "轨道名称"},
                "property_type": {"type": "string", "description": "关键帧属性类型(position_x, position_y, rotation, scale_x, scale_y, uniform_scale, alpha, saturation, contrast, brightness, volume)"},
                "time": {"type": "number", "default": 0.0, "description": "关键帧时间点（秒）"},
                "value": {"type": "string", "description": "关键帧值"},
                "property_types": {"type": "array", "description": "批量模式：关键帧属性类型列表"},
                "times": {"type": "array", "description": "批量模式：关键帧时间点列表"},
                "values": {"type": "array", "description": "批量模式：关键帧值列表"}
            },
            "required": ["draft_id", "track_name"]
        }
    },
    {
        "name": "generate_video",
        "description": "生成视频",
        "inputSchema": {
            "type": "object",
            "properties": {
                "draft_id": {"type": "string", "description": "草稿ID"},
                "resolution": {"type": "string", "enum": ["1080P", "2K", "4K"], "description": "分辨率，可选值1080P、2K、4K", "default": "1080P"},
                "framerate": {"type": "string", "enum": ["30fps", "50fps", "60fps"], "description": "帧率（可选值30fps、50fps、60fps）", "default": "30fps"},
                "name": {"type": "string", "description": "视频名称"}
            },
            "required": ["draft_id"]
        }
    },
    {
        "name": "get_font_types",
        "description": "获取字体类型列表",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "get_audio_effect_types",
        "description": "获取音频特效类型列表",
        "inputSchema": {
            "type": "object",
            "properties": {}
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

        if not CAPCUT_AVAILABLE:
            return {"success": False, "error": "CapCut modules not available"}

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
