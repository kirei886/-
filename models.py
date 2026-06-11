from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class StartPoint(BaseModel):
    id: str
    name: str
    address: Optional[str] = None
    lat: float = Field(..., ge=-90.0, le=90.0, description="纬度")
    lng: float = Field(..., ge=-180.0, le=180.0, description="经度")
    passenger_count: Optional[int] = Field(
        default=None, ge=0, description="乘车人数，缺省按 1 人计入容量需求"
    )


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
    max_solve_time: Optional[int] = Field(default=30, ge=1, le=300, description="OR-Tools 最大求解时间（秒）")
    num_vehicles: Optional[int] = Field(
        default=None, ge=1, le=50, description="车队车辆数；为空时由 vehicle_capacities 长度或服务端默认值决定"
    )
    vehicle_capacities: Optional[List[int]] = Field(
        default=None,
        min_length=1,
        description="各车座位数数组（混合车型，每元素 ≥1）；为空时取服务端默认值",
    )

    @field_validator("vehicle_capacities")
    @classmethod
    def check_capacities_positive(cls, v: Optional[List[int]]) -> Optional[List[int]]:
        if v is not None and any(c < 1 for c in v):
            raise ValueError("vehicle_capacities 中每辆车座位数必须 ≥ 1")
        return v

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

    @model_validator(mode="after")
    def check_vehicles_consistency(self) -> "RouteRequest":
        if (
            self.num_vehicles is not None
            and self.vehicle_capacities is not None
            and len(self.vehicle_capacities) != self.num_vehicles
        ):
            raise ValueError(
                f"num_vehicles({self.num_vehicles}) 与 vehicle_capacities 长度"
                f"({len(self.vehicle_capacities)}) 不一致"
            )
        return self


class Segment(BaseModel):
    from_id: str
    to_id: str
    distance: float = Field(description="分段距离（米）")
    duration: float = Field(description="分段耗时（秒）")
    path: List[Any] = Field(default_factory=list, description="百度地图返回的路径轨迹点")


class VehicleRoute(BaseModel):
    """单辆车的子路线。"""
    vehicle_index: int = Field(description="车辆序号，从 0 开始")
    route_order: List[str] = Field(
        default_factory=list, description="该车经停站点 ID 顺序，末位为企业终点"
    )
    total_distance: float = Field(default=0.0, description="该车总距离（米）")
    total_duration: float = Field(default=0.0, description="该车总耗时（秒）")
    segments: List[Segment] = Field(default_factory=list)
    load: int = Field(default=0, description="该车承载总人数（各经停站点乘车人数之和）")


class RouteResponse(BaseModel):
    status: Literal["success", "no_solution", "error"]
    message: str
    routes: List[VehicleRoute] = Field(default_factory=list, description="各车辆子路线")
    total_distance: float = Field(default=0.0, description="车队总距离（米），各路线之和")
    total_duration: float = Field(default=0.0, description="车队总耗时（秒），各路线之和")
    unreachable_points: List[str] = Field(default_factory=list, description="不可达点位 ID 列表")
