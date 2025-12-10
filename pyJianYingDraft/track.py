"""轨道类及其元数据"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Generic, List, Type, TypeVar, Union

import pyJianYingDraft as draft

from .audio_segment import AudioSegment
from .effect_segment import Effect_segment, Filter_segment
from .exceptions import SegmentOverlap
from .segment import BaseSegment
from .text_segment import Text_segment
from .video_segment import StickerSegment, VideoSegment


@dataclass
class TrackMeta:
    """与轨道类型关联的轨道元数据"""

    segment_type: Union[
        Type[VideoSegment],
        Type[AudioSegment],
        Type[Effect_segment],
        Type[Filter_segment],
        Type[Text_segment],
        Type[StickerSegment],
        None,
    ]
    """与轨道关联的片段类型"""
    render_index: int
    """默认渲染顺序, 值越大越接近前景"""
    allow_modify: bool
    """当被导入时, 是否允许修改"""


class TrackType(Enum):
    """轨道类型枚举

    变量名对应type属性, 值表示相应的轨道元数据
    """

    video = TrackMeta(VideoSegment, 0, True)
    audio = TrackMeta(AudioSegment, 0, True)
    effect = TrackMeta(Effect_segment, 10000, False)
    filter = TrackMeta(Filter_segment, 11000, False)
    sticker = TrackMeta(StickerSegment, 14000, False)
    text = TrackMeta(
        Text_segment, 15000, True
    )  # 原本是14000, 避免与sticker冲突改为15000

    adjust = TrackMeta(None, 0, False)
    """仅供导入时使用, 不要尝试新建此类型的轨道"""

    @staticmethod
    def from_name(name: str) -> "TrackType":
        """根据名称获取轨道类型枚举"""
        for t in TrackType:
            if t.name == name:
                return t
        raise ValueError("Invalid track type: %s" % name)


class BaseTrack(ABC):
    """轨道基类"""

    track_type: TrackType
    """轨道类型"""
    name: str
    """轨道名称"""
    track_id: str
    """轨道全局ID"""
    render_index: int
    """渲染顺序, 值越大越接近前景"""

    @abstractmethod
    def export_json(self) -> Dict[str, Any]: ...


Seg_type = TypeVar("Seg_type", bound=BaseSegment)


class Track(BaseTrack, Generic[Seg_type]):
    """非模板模式下的轨道"""

    mute: bool
    """是否静音"""

    segments: List[Seg_type]
    """该轨道包含的片段列表"""

    pending_keyframes: List[Dict[str, Any]]
    """待处理的关键帧列表"""

    def __init__(self, track_type: TrackType, name: str, render_index: int, mute: bool):
        self.track_type = track_type
        self.name = name
        self.track_id = uuid.uuid4().hex
        self.render_index = render_index

        self.mute = mute
        self.segments = []
        self.pending_keyframes = []

    def add_pending_keyframe(self, property_type: str, time: float, value: str) -> None:
        """添加待处理的关键帧

        Args:
            property_type: 关键帧属性类型
            time: 关键帧时间点（秒）
            value: 关键帧值
        """
        self.pending_keyframes.append(
            {"property_type": property_type, "time": time, "value": value}
        )

    def process_pending_keyframes(self) -> None:
        """处理所有待处理的关键帧"""
        if not self.pending_keyframes:
            return

        for kf_info in self.pending_keyframes:
            property_type = kf_info["property_type"]
            time = kf_info["time"]
            value = kf_info["value"]

            try:
                # 找到时间点对应的片段（时间单位：微秒）
                target_time = int(time * 1000000)  # 将秒转换为微秒
                target_segment = next(
                    (
                        segment
                        for segment in self.segments
                        if segment.target_timerange.start
                        <= target_time
                        <= segment.target_timerange.end
                    ),
                    None,
                )

                if target_segment is None:
                    print(
                        f"警告：在轨道 {self.name} 的时间点 {time}s 找不到对应的片段，跳过此关键帧"
                    )
                    continue

                # 将属性类型字符串转换为枚举值
                property_enum = getattr(draft.KeyframeProperty, property_type)

                # 解析value值
                if (property_type == "alpha" and value.endswith("%")) or (
                    property_type == "volume" and value.endswith("%")
                ):
                    float_value = float(value[:-1]) / 100
                elif property_type == "rotation" and value.endswith("deg"):
                    float_value = float(value[:-3])
                elif property_type in ["saturation", "contrast", "brightness"]:
                    if value.startswith("+"):
                        float_value = float(value[1:])
                    elif value.startswith("-"):
                        float_value = -float(value[1:])
                    else:
                        float_value = float(value)
                else:
                    float_value = float(value)

                # 计算时间偏移量
                offset_time = target_time - target_segment.target_timerange.start

                # 添加关键帧
                target_segment.add_keyframe(property_enum, offset_time, float_value)
                print(f"成功添加关键帧: {property_type} 在 {time}s")
            except Exception as e:
                print(f"添加关键帧失败: {e!s}")

        # 清空待处理的关键帧
        self.pending_keyframes = []

    @property
    def end_time(self) -> int:
        """轨道结束时间, 微秒"""
        if len(self.segments) == 0:
            return 0
        return self.segments[-1].target_timerange.end

    @property
    def accept_segment_type(self) -> Type[Seg_type]:
        """返回该轨道允许的片段类型"""
        return self.track_type.value.segment_type  # type: ignore

    def add_segment(self, segment: Seg_type) -> "Track[Seg_type]":
        """向轨道中添加一个片段, 添加的片段必须匹配轨道类型且不与现有片段重叠

        Args:
            segment (Seg_type): 要添加的片段

        Raises:
            `TypeError`: 新片段类型与轨道类型不匹配
            `SegmentOverlap`: 新片段与现有片段重叠
        """
        if not isinstance(segment, self.accept_segment_type):
            raise TypeError(
                "New segment (%s) is not of the same type as the track (%s)"
                % (type(segment), self.accept_segment_type)
            )

        # 检查片段是否重叠
        for seg in self.segments:
            if seg.overlaps(segment):
                raise SegmentOverlap(
                    f"New segment overlaps with existing segment [start: {segment.target_timerange.start}, end: {segment.target_timerange.end}]. "
                    f"Conflicting existing segment range: [start: {seg.target_timerange.start}, end: {seg.target_timerange.end}]"
                )

        self.segments.append(segment)
        return self

    def export_json(self) -> Dict[str, Any]:
        # 为每个片段写入render_index
        segment_exports = [seg.export_json() for seg in self.segments]
        for seg in segment_exports:
            seg["render_index"] = self.render_index

        return {
            "attribute": int(self.mute),
            "flag": 0,
            "id": self.track_id,
            "is_default_name": len(self.name) == 0,
            "name": self.name,
            "segments": segment_exports,
            "type": self.track_type.name,
        }
