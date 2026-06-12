# 嘟嘟巴士企业班车路径规划

基于 Google OR-Tools 与百度地图的企业班车路径优化工具。支持**多个上车点、单一企业终点**的场景,计算最优经停顺序,输出总耗时、总距离与分段路径轨迹。

## 技术栈

| 层 | 技术 |
|----|------|
| 后端 | Python 3.11 · FastAPI · OR-Tools · 百度地图 Web 服务 API |
| 前端 | Vue 3 · Vite · TypeScript · vue-router · axios |

## 目录结构

```
.
├── main.py              # FastAPI 入口,路由 /api/v1/route/plan
├── models.py            # Pydantic 请求/响应模型(接口契约)
├── config.py            # 配置:AK、成本权重、重试参数等
├── baidu_map.py         # 百度地图接口封装(矩阵 / 路径详情)
├── cost_matrix.py       # 成本矩阵构建 + 不可达检测
├── solver.py            # OR-Tools 路径求解
├── requirements.txt
├── .env.example         # 后端环境变量模板
└── frontend/            # Vue 3 + Vite 前端
    ├── src/
    │   ├── api/         # axios 封装 + 路径规划接口
    │   ├── composables/ # 百度地图 JS API 加载器
    │   ├── types/       # 对齐后端契约的 TS 类型
    │   └── views/
    └── .env.example     # 前端环境变量模板
```

## 后端启动

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置百度地图服务端 AK
cp .env.example .env
# 编辑 .env,填入 BAIDU_MAP_AK(服务端 AK,非浏览器端)

# 3. 启动服务
uvicorn main:app --reload
```

服务默认运行在 `http://127.0.0.1:8000`,交互式文档见 `http://127.0.0.1:8000/docs`。

> **AK 说明**:百度地图 AK 由后端从环境变量读取,前端不再传入。服务端 AK 与前端浏览器端 AK 是两个不同的 AK,需分别申请。

## 前端启动

```bash
cd frontend

# 1. 安装依赖
npm install

# 2. 配置前端环境变量(浏览器端 AK 等)
cp .env.example .env.local

# 3. 开发模式(默认 http://localhost:5173,/api 代理到后端 8000)
npm run dev

# 构建生产包(含 vue-tsc 类型检查)
npm run build
```

## 接口契约

**POST** `/api/v1/route/plan`

请求(简要):

```json
{
  "start_points": [{ "id": "s1", "lat": 22.5, "lng": 114.0 }],
  "end_point": { "id": "company", "lat": 22.6, "lng": 114.1 },
  "optimize_type": "time",
  "max_solve_time": 30
}
```

响应(简要):

```json
{
  "status": "success",
  "message": "...",
  "route_order": ["s1", "company"],
  "total_distance": 12345.6,
  "total_duration": 1800.0,
  "segments": [{ "from_id": "s1", "to_id": "company", "distance": 0, "duration": 0, "path": [] }],
  "unreachable_points": []
}
```

`status` 取值:`success` / `no_solution` / `error`。完整字段定义见 `models.py`。

## CI

`.github/workflows/ci.yml` 在 push / PR 到 `main` 时自动运行:后端依赖安装与编译检查、前端 `npm ci` 与 `npm run build`。

## 部署

上架演示站(云主机 + Nginx + systemd 同源部署)的完整指引见 [DEPLOY.md](DEPLOY.md),含两个百度地图 AK 的白名单配置、HTTPS、上线冒烟验证与排障速查。
