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
    latest_arrival_time: Optional[str] = Field(
        default=None,
        description="企业最晚到达时刻 HH:MM（24 小时制，从当日 0 点算）；给定则启用时间窗约束，求解器保证各车在此前抵达终点",
    )

    @field_validator("latest_arrival_time")
    @classmethod
    def check_arrival_format(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        parts = v.split(":")
        if len(parts) != 2 or not all(p.isdigit() for p in parts):
            raise ValueError("latest_arrival_time 需为 HH:MM 格式，如 09:00")
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            raise ValueError("latest_arrival_time 时分超出范围（HH 0-23，MM 0-59）")
        return v


class VehicleType(BaseModel):
    """车型池中的一种车型（阶段三：车型池自动选型）。"""
    seats: int = Field(..., ge=1, description="该车型座位数")
    count: int = Field(..., ge=1, description="该车型可用台数")
    fixed_cost: int = Field(
        default=0,
        ge=0,
        description="单辆启用成本，单位与优化目标一致（time=秒/distance=米/cost=加权值）；求解器据此自动选型",
    )


class RouteRequest(BaseModel):
    start_points: List[StartPoint] = Field(..., min_length=1, description="起点列表，至少 1 个")
    end_point: EndPoint
    optimize_type: Literal["time", "distance", "cost"] = Field(default="time", description="优化目标")
    max_solve_time: Optional[int] = Field(default=5, ge=1, le=300, description="OR-Tools 最大求解时间（秒），作收敛兜底；求解器达 solution_limit 即提前返回")
    num_vehicles: Optional[int] = Field(
        default=None, ge=1, le=50, description="车队车辆数；为空时由 vehicle_capacities 长度或服务端默认值决定"
    )
    vehicle_capacities: Optional[List[int]] = Field(
        default=None,
        min_length=1,
        description="各车座位数数组（混合车型，每元素 ≥1）；为空时取服务端默认值",
    )
    vehicle_types: Optional[List[VehicleType]] = Field(
        default=None,
        min_length=1,
        description="车型池（阶段三）：求解器据各车型座位数/台数/启用成本自动选型；与 vehicle_capacities 互斥",
    )
    service_time: Optional[int] = Field(
        default=None,
        ge=0,
        le=3600,
        description="每个上车点固定停靠时间（秒，全局统一，阶段四时间窗）；缺省取服务端默认。仅在终点设置 latest_arrival_time 时参与时间窗计算",
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

    @model_validator(mode="after")
    def check_fleet_source_exclusive(self) -> "RouteRequest":
        # 车型池与显式容量数组语义重叠，同时给会产生歧义，禁止并存。
        if self.vehicle_types is not None and self.vehicle_capacities is not None:
            raise ValueError("vehicle_types 与 vehicle_capacities 不能同时提供")
        return self


class Segment(BaseModel):
    from_id: str
    to_id: str
    distance: float = Field(description="分段距离（米）")
    duration: float = Field(description="分段耗时（秒）")
    path: List[Any] = Field(default_factory=list, description="百度地图返回的路径轨迹点")
    arrival_time: Optional[int] = Field(
        default=None,
        description="到达 to_id 的预计时刻（当日秒数，前端转 HH:MM，阶段四时间窗）；未启用时间窗时为 null",
    )


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
    capacity: int = Field(default=0, description="该车座位数（阶段三体现自动选中的车型容量）")
    fixed_cost: int = Field(
        default=0, description="该车启用成本，单位与优化目标一致；阶段二回退路径为 0"
    )
    departure_time: Optional[int] = Field(
        default=None,
        description="该车发车时刻（当日秒数，前端转 HH:MM，阶段四时间窗）；倒推自终点最晚到达，未启用时间窗时为 null",
    )


class RouteResponse(BaseModel):
    status: Literal["success", "no_solution", "error"]
    message: str
    routes: List[VehicleRoute] = Field(default_factory=list, description="各车辆子路线")
    total_distance: float = Field(default=0.0, description="车队总距离（米），各路线之和")
    total_duration: float = Field(default=0.0, description="车队总耗时（秒），各路线之和")
    unreachable_points: List[str] = Field(default_factory=list, description="不可达点位 ID 列表")
