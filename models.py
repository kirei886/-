from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class StartPoint(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0, description="纬度")
    lng: float = Field(..., ge=-180.0, le=180.0, description="经度")
    passenger_count: Optional[int] = Field(default=None, ge=0, description="预计乘车人数，当前版本仅透传")


class EndPoint(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0, description="纬度")
    lng: float = Field(..., ge=-180.0, le=180.0, description="经度")


class RouteRequest(BaseModel):
    start_points: List[StartPoint] = Field(..., min_length=1, description="起点列表，至少 1 个")
    end_point: EndPoint
    optimize_type: Literal["time", "distance", "cost"] = Field(default="time", description="优化目标")
    baidu_map_ak: str = Field(..., min_length=1, description="百度地图 AK")
    max_solve_time: Optional[int] = Field(default=30, ge=1, le=300, description="OR-Tools 最大求解时间（秒）")

    @field_validator("start_points")
    @classmethod
    def check_no_duplicate_ids(cls, v: List[StartPoint]) -> List[StartPoint]:
        ids = [p.id for p in v]
        if len(ids) != len(set(ids)):
            raise ValueError("start_points 中存在重复的 id")
        return v

    @model_validator(mode="after")
    def check_end_point_id_not_in_start(self) -> "RouteRequest":
        start_ids = {p.id for p in self.start_points}
        if self.end_point.id in start_ids:
            raise ValueError("end_point 的 id 不能与 start_points 中的 id 重复")
        return self


class Segment(BaseModel):
    from_id: str
    to_id: str
    distance: float = Field(description="分段距离（米）")
    duration: float = Field(description="分段耗时（秒）")
    path: List[Any] = Field(default_factory=list, description="百度地图返回的路径轨迹点")


class RouteResponse(BaseModel):
    status: Literal["success", "no_solution", "error"]
    message: str
    route_order: List[str] = Field(default_factory=list, description="推荐站点 ID 顺序（含终点）")
    total_distance: float = Field(default=0.0, description="总距离（米）")
    total_duration: float = Field(default=0.0, description="总耗时（秒）")
    segments: List[Segment] = Field(default_factory=list)
    unreachable_points: List[str] = Field(default_factory=list, description="不可达点位 ID 列表")
