import os
import uuid
from typing import Any, Dict, Literal, Optional


class CropSettings:
    """素材的裁剪设置, 各属性均在0-1之间, 注意素材的坐标原点在左上角"""

    upper_left_x: float
    upper_left_y: float
    upper_right_x: float
    upper_right_y: float
    lower_left_x: float
    lower_left_y: float
    lower_right_x: float
    lower_right_y: float

    def __init__(
        self,
        *,
        upper_left_x: float = 0.0,
        upper_left_y: float = 0.0,
        upper_right_x: float = 1.0,
        upper_right_y: float = 0.0,
        lower_left_x: float = 0.0,
        lower_left_y: float = 1.0,
        lower_right_x: float = 1.0,
        lower_right_y: float = 1.0,
    ):
        """初始化裁剪设置, 默认参数表示不裁剪"""
        self.upper_left_x = upper_left_x
        self.upper_left_y = upper_left_y
        self.upper_right_x = upper_right_x
        self.upper_right_y = upper_right_y
        self.lower_left_x = lower_left_x
        self.lower_left_y = lower_left_y
        self.lower_right_x = lower_right_x
        self.lower_right_y = lower_right_y

    def export_json(self) -> Dict[str, Any]:
        return {
            "upper_left_x": self.upper_left_x,
            "upper_left_y": self.upper_left_y,
            "upper_right_x": self.upper_right_x,
            "upper_right_y": self.upper_right_y,
            "lower_left_x": self.lower_left_x,
            "lower_left_y": self.lower_left_y,
            "lower_right_x": self.lower_right_x,
            "lower_right_y": self.lower_right_y,
        }


class VideoMaterial:
    """本地视频素材（视频或图片）, 一份素材可以在多个片段中使用"""

    material_id: str
    """素材全局id, 自动生成"""
    local_material_id: str
    """素材本地id, 意义暂不明确"""
    material_name: str
    """素材名称"""
    path: str
    """素材文件路径"""
    remote_url: Optional[str] = None
    """远程URL地址"""
    duration: int
    """素材时长, 单位为微秒"""
    height: int
    """素材高度"""
    width: int
    """素材宽度"""
    crop_settings: CropSettings
    """素材裁剪设置"""
    material_type: Literal["video", "photo"]
    """素材类型: 视频或图片"""
    replace_path: Optional[str] = None
    """替换路径, 如果设置了这个值, 在导出json时会用这个路径替代原始path"""

    def __init__(
        self,
        material_type: Literal["video", "photo"],
        duration: int,
        width: int,
        height: int,
        path: Optional[str] = None,
        replace_path: Optional[str] = None,
        material_name: Optional[str] = None,
        crop_settings: CropSettings = CropSettings(),
        remote_url: Optional[str] = None,
    ):
        """从指定位置加载视频（或图片）素材

        Args:
            material_type (`Literal["video", "photo"]`): 素材类型.
            duration (`int`): 素材时长, 单位为微秒.
            width (`int`): 素材宽度.
            height (`int`): 素材高度.
            path (`str`, optional): 素材文件路径, 支持mp4, mov, avi等常见视频文件及jpg, jpeg, png等图片文件.
            replace_path (`str`, optional): 替换路径，用于导出JSON时替代原始path.
            material_name (`str`, optional): 素材名称, 如果不指定, 默认使用文件名作为素材名称.
            crop_settings (`Crop_settings`, optional): 素材裁剪设置, 默认不裁剪.
            remote_url (`str`, optional): 远程URL地址.

        Raises:
            `ValueError`: 不支持的素材文件类型或缺少必要参数.
            `FileNotFoundError`: 素材文件不存在.
        """
        # 确保至少提供了path或remote_url
        if not path and not remote_url:
            raise ValueError("必须提供 path 或 remote_url 中的至少一个参数")

        # 处理远程URL情况
        if remote_url:
            if not material_name:
                raise ValueError("使用 remote_url 参数时必须指定 material_name")
            self.remote_url = remote_url
            self.path = ""  # 远程资源没有本地路径
        else:
            # 处理本地文件情况
            path = os.path.abspath(path)
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到 {path}")
            self.path = path
            self.remote_url = None

        # 设置素材名称
        self.material_name = material_name if material_name else os.path.basename(path)
        self.material_id = uuid.uuid4().hex
        self.replace_path = replace_path
        self.crop_settings = crop_settings
        self.local_material_id = ""
        self.material_type = material_type
        self.duration = duration
        self.width = width
        self.height = height

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "VideoMaterial":
        """从字典创建视频素材对象

        Args:
            data (Dict[str, Any]): 包含素材信息的字典

        Returns:
            VideoMaterial: 新创建的视频素材对象
        """
        # 创建实例但不调用__init__
        instance = cls.__new__(cls)

        # 设置基本属性
        instance.material_id = data["id"]
        instance.local_material_id = data.get("local_material_id", "")
        instance.material_name = data["material_name"]
        instance.path = data["path"]
        instance.duration = data["duration"]
        instance.height = data["height"]
        instance.width = data["width"]
        instance.material_type = data["type"]
        instance.replace_path = None  # 默认不设置替换路径

        # 设置裁剪设置
        crop_data = data.get("crop", {})
        instance.crop_settings = CropSettings(
            upper_left_x=crop_data.get("upper_left_x", 0.0),
            upper_left_y=crop_data.get("upper_left_y", 0.0),
            upper_right_x=crop_data.get("upper_right_x", 1.0),
            upper_right_y=crop_data.get("upper_right_y", 0.0),
            lower_left_x=crop_data.get("lower_left_x", 0.0),
            lower_left_y=crop_data.get("lower_left_y", 1.0),
            lower_right_x=crop_data.get("lower_right_x", 1.0),
            lower_right_y=crop_data.get("lower_right_y", 1.0),
        )

        return instance

    def export_json(self) -> Dict[str, Any]:
        video_material_json = {
            "audio_fade": None,
            "category_id": "",
            "category_name": "local",
            "check_flag": 63487,
            "crop": self.crop_settings.export_json(),
            "crop_ratio": "free",
            "crop_scale": 1.0,
            "duration": self.duration,
            "height": self.height,
            "id": self.material_id,
            "local_material_id": self.local_material_id,
            "material_id": self.material_id,
            "material_name": self.material_name,
            "media_path": "",
            "path": self.replace_path if self.replace_path is not None else self.path,
            "remote_url": self.remote_url,
            "type": self.material_type,
            "width": self.width,
        }
        return video_material_json


class AudioMaterial:
    """本地音频素材"""

    material_id: str
    """素材全局id, 自动生成"""
    material_name: str
    """素材名称"""
    path: str
    """素材文件路径"""
    remote_url: Optional[str] = None
    """远程URL地址"""
    replace_path: Optional[str] = None
    """替换路径, 如果设置了这个值, 在导出json时会用这个路径替代原始path"""

    has_audio_effect: bool = False
    """是否有音频效果"""

    duration: int
    """素材时长, 单位为微秒"""

    def __init__(
        self,
        duration: int,
        path: Optional[str] = None,
        replace_path=None,
        material_name: Optional[str] = None,
        remote_url: Optional[str] = None,
    ):
        """从指定位置加载音频素材, 注意视频文件不应该作为音频素材使用

        Args:
            duration (`int`): 音频时长, 单位为微秒.
            path (`str`, optional): 素材文件路径, 支持mp3, wav等常见音频文件.
            material_name (`str`, optional): 素材名称, 如果不指定, 默认使用URL中的文件名作为素材名称.
            remote_url (`str`, optional): 远程URL地址.

        Raises:
            `ValueError`: 不支持的素材文件类型或缺少必要参数.
        """
        if not path and not remote_url:
            raise ValueError("必须提供 path 或 remote_url 中的至少一个参数")

        if path:
            path = os.path.abspath(path)
            if not os.path.exists(path):
                raise FileNotFoundError(f"找不到 {path}")

        # 从URL中获取文件名作为material_name
        if not material_name and remote_url:
            original_filename = os.path.basename(
                remote_url.split("?")[0]
            )  # 修复：使用remote_url而不是audio_url
            name_without_ext = os.path.splitext(original_filename)[
                0
            ]  # 获取不带扩展名的文件名
            material_name = (
                f"{name_without_ext}.mp3"  # 使用原始文件名+时间戳+固定mp3扩展名
            )

        self.material_name = (
            material_name
            if material_name
            else (os.path.basename(path) if path else "unknown")
        )
        self.material_id = uuid.uuid4().hex
        self.path = path if path else ""
        self.replace_path = replace_path
        self.remote_url = remote_url
        self.duration = duration

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AudioMaterial":
        """从字典创建音频素材对象

        Args:
            data (Dict[str, Any]): 包含素材信息的字典

        Returns:
            AudioMaterial: 新创建的音频素材对象
        """
        # 创建实例但不调用__init__
        instance = cls.__new__(cls)

        # 设置基本属性
        instance.material_id = data["id"]
        instance.material_name = data["name"]  # 注意这里是name而不是material_name
        instance.path = data["path"]
        instance.duration = data["duration"]
        instance.replace_path = None  # 默认不设置替换路径
        instance.remote_url = data.get("remote_url")

        return instance

    def export_json(self) -> Dict[str, Any]:
        return {
            "app_id": 0,
            "category_id": "",
            "category_name": "local",
            "check_flag": 3
            if hasattr(self, "has_audio_effect") and self.has_audio_effect
            else 1,
            "copyright_limit_type": "none",
            "duration": self.duration,
            "effect_id": "",
            "formula_id": "",
            "id": self.material_id,
            "intensifies_path": "",
            "is_ai_clone_tone": False,
            "is_text_edit_overdub": False,
            "is_ugc": False,
            "local_material_id": self.material_id,
            "music_id": self.material_id,
            "name": self.material_name,
            "path": self.replace_path if self.replace_path is not None else self.path,
            "remote_url": self.remote_url,
            "query": "",
            "request_id": "",
            "resource_id": "",
            "search_id": "",
            "source_from": "",
            "source_platform": 0,
            "team_id": "",
            "text_id": "",
            "tone_category_id": "",
            "tone_category_name": "",
            "tone_effect_id": "",
            "tone_effect_name": "",
            "tone_platform": "",
            "tone_second_category_id": "",
            "tone_second_category_name": "",
            "tone_speaker": "",
            "tone_type": "",
            "type": "extract_music",
            "video_id": "",
            "wave_points": [],
        }
