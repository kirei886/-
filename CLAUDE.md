# CLAUDE.md

企业班车路径规划(嘟嘟巴士)——基于 OR-Tools 与百度地图的多起点单终点班车路径优化工具。供 Claude Code 快速了解项目约定。

## 技术栈

- **后端**:Python 3.11 · FastAPI · OR-Tools · 百度地图 Web 服务 API
- **前端**:Vue 3 · Vite · TypeScript · vue-router · axios(目录 `frontend/`)

## 常用命令

**后端**(项目根目录):
```bash
pip install -r requirements.txt
cp .env.example .env        # 填入 BAIDU_MAP_AK(服务端 AK)
uvicorn main:app --reload   # http://127.0.0.1:8000,文档 /docs
```

**前端**(`frontend/`):
```bash
npm install
npm run dev      # http://localhost:5173,/api 代理到后端 8000
npm run build    # 含 vue-tsc 类型检查,CI 也跑这条
```

## 架构与数据流

后端核心链路(`main.py` → `cost_matrix.py` → `solver.py`):
1. 接收多起点 + 单终点 → 百度地图批量算路构建成本矩阵(`cost_matrix.py`)
2. 不可达检测:某起点到终点不通则剔除
3. OR-Tools 求解最优经停顺序(`solver.py`,虚拟节点建模,强制经过所有可达起点)
4. 相邻站点连通性二次校验(拦截被迫走死路)
5. 补充分段路径 polyline(`baidu_map.py`),失败时降级用矩阵估算数据

关键模块:
- `main.py` — FastAPI 入口,路由 `POST /api/v1/route/plan`
- `models.py` — Pydantic 请求/响应模型,**前后端接口契约的唯一真相来源**
- `config.py` — AK、成本权重、重试/分批参数
- `frontend/src/types/route.ts` — TS 类型,必须与 `models.py` 严格对齐

## 约定

- **百度地图 AK 已解耦**:后端用服务端 AK(`.env` 的 `BAIDU_MAP_AK`),前端用浏览器端 AK(`VITE_BAIDU_MAP_AK`),两者是不同的 AK。请求体不传 AK。
- **接口契约**:改 `models.py` 时同步改 `frontend/src/types/route.ts`。
- **AK 与密钥**:`.env`、`.env.local` 不进 git(已在 .gitignore),改动请走 `.env.example`。
- **优化目标**:`time` / `distance` / `cost`;响应状态 `success` / `no_solution` / `error`。

## 工程流程

- commit message 用中文 + conventional 前缀(feat/refactor/chore/fix)。
- PR 合并用 merge commit(`gh pr merge --merge`),保持与历史风格一致。
- 走完整闭环:issue → 分支 → PR(`Closes #N`)→ CI 绿灯 → merge → 删分支。
- CI 见 `.github/workflows/ci.yml`,PR/push 到 main 自动跑后端检查 + 前端构建。
