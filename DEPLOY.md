# 部署指南(DEPLOY.md)

面向**演示站**场景:单台云主机 + Nginx + systemd,公网可访问即可。生产级高可用/鉴权不在本文范围。

整体架构采用**同源部署**:Nginx 在同一域名下静态托管前端构建产物,并把 `/api` 反向代理到本机后端。这样前后端同源,**规避跨域**(当前后端未启用 CORS 中间件,见文末「已知现状」)。

```
浏览器 ──HTTPS──> Nginx(443)
                   ├── /            静态文件 frontend/dist/
                   └── /api/*  ──>  127.0.0.1:8000 (uvicorn 后端)
                                         └──> 百度地图 Web 服务 API
```

---

## 0. 上架前必须确认(Checklist)

逐项确认,缺一项都可能导致"本地正常、线上白屏或算路失败":

- [ ] 已备案的域名一个(国内服务器访问百度地图、走 80/443 通常需要 ICP 备案)
- [ ] **两个**百度地图 AK 已分别申请:服务端 AK(Web 服务 API)+ 浏览器端 AK(JS API)
- [ ] 服务端 AK 的 **IP 白名单**已加入服务器**公网出口 IP**
- [ ] 浏览器端 AK 的 **Referer 白名单**已加入**域名**(如 `https://你的域名/*`)
- [ ] 服务器已装 Python 3.11、Node 20(仅构建期需要)、Nginx
- [ ] HTTPS 证书已就绪(Let's Encrypt 免费证书即可)
- [ ] 后端 `.env` 在服务器上单独配置,**不从 git 拉取**

---

## 1. 百度地图 AK 配置(最易踩坑)

项目用**两个不同的 AK**,职责分离,上线时白名单类型也不同:

| AK | 用途 | 配置位置 | 白名单类型 |
|----|------|---------|-----------|
| 服务端 AK | 后端调 routematrix / direction 算路 | 服务器 `.env` 的 `BAIDU_MAP_AK` | **IP 白名单** = 服务器公网 IP |
| 浏览器端 AK | 前端加载 JS API 画底图 | 前端构建期 `frontend/.env` 的 `VITE_BAIDU_MAP_AK` | **Referer 白名单** = 域名 |

> 服务端 AK 的 IP 白名单填**服务器的公网出口 IP**(不是用户的 IP)。可在服务器上 `curl ifconfig.me` 查到。
> 浏览器端 AK 的 Referer 白名单填域名通配,如 `https://example.com/*`。配错会导致地图加载报 `APP Referer校验失败`。

---

## 2. 后端部署

### 2.1 代码与依赖

```bash
# 拉代码到服务器,例如 /opt/shuttle
git clone https://github.com/kirei886/-.git /opt/shuttle
cd /opt/shuttle

# 建虚拟环境装依赖
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2.2 配置 `.env`(不进 git)

```bash
cp .env.example .env
# 编辑 .env,仅一行:
# BAIDU_MAP_AK=你的服务端AK
```

`.env` 已在 `.gitignore`,**绝不提交**。服务器上手动维护。

### 2.3 systemd 常驻(生产不用 --reload)

`--reload` 是开发模式,生产用多 worker 常驻。新建 `/etc/systemd/system/shuttle.service`:

```ini
[Unit]
Description=Shuttle Route Planning API
After=network.target

[Service]
WorkingDirectory=/opt/shuttle
ExecStart=/opt/shuttle/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now shuttle
sudo systemctl status shuttle      # 确认 active (running)
```

> **为何多 worker**:`baidu_map.py` 的重试退避与批次间隔用的是同步 `time.sleep`,单个请求内是阻塞的。靠多 worker 承接并发(演示站 2 个足够)。绑 `127.0.0.1` 是因为对外只暴露 Nginx,后端不直接公网可达。

---

## 3. 前端构建

前端是纯静态产物,在**本地或服务器**构建一次,把 `dist/` 交给 Nginx 托管。

```bash
cd frontend

# 浏览器端 AK 写进构建环境(构建时注入,产物里是静态值)
cp .env.example .env
# 编辑 .env:
#   VITE_BAIDU_MAP_AK=你的浏览器端AK
#   VITE_API_BASE_URL=        ← 留空!走同源 /api,由 Nginx 反代

npm ci
npm run build                  # 产出 frontend/dist/
```

> `VITE_API_BASE_URL` **必须留空**:留空时 `src/api/client.ts` 默认用 `/api`,正好匹配同源 Nginx 反代,无需跨域。只有前后端分域名部署才需要填它(那时还得在后端加 CORS,见文末)。

把 `frontend/dist/` 同步到服务器,例如 `/opt/shuttle/frontend/dist`。

---

## 4. Nginx 配置

`/etc/nginx/conf.d/shuttle.conf`(HTTPS 部分由 certbot 自动补全,这里给反代与静态托管核心):

```nginx
server {
    listen 443 ssl;
    server_name 你的域名;

    # ssl_certificate / ssl_certificate_key 由 certbot 管理

    # 前端静态产物
    root /opt/shuttle/frontend/dist;
    index index.html;

    # SPA 路由回退:非文件请求一律回 index.html(支持 /plan 等前端路由刷新)
    location / {
        try_files $uri $uri/ /index.html;
    }

    # /api 反代到后端;路径含 /api/v1/... 后端原样接收,不要 rewrite 掉 /api
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 路径规划含百度算路 + OR-Tools 求解,耗时较长;放宽超时
        proxy_read_timeout 120s;
    }
}

# 80 → 443 跳转(certbot 通常会自动加)
server {
    listen 80;
    server_name 你的域名;
    return 301 https://$host$request_uri;
}
```

要点:
- **不要 rewrite 掉 `/api` 前缀**。后端路由是 `/api/v1/route/plan`,前端请求的也是 `/api/v1/...`,直接透传即可。
- `try_files ... /index.html` 让前端路由(如 `/plan`)刷新不 404。
- `proxy_read_timeout` 放宽到 120s:前端 axios 自身 timeout 是 60s(`client.ts`),Nginx 给足余量避免它先掐断。

```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 5. HTTPS(几乎必须)

百度地图 JS API 在 HTTPS 页面里加载 HTTP 资源会被浏览器当**混合内容**拦截,导致底图加载失败。演示站用 Let's Encrypt 免费证书:

```bash
sudo certbot --nginx -d 你的域名
```

certbot 会自动改写上面的 server 块补全证书路径与 80→443 跳转。

---

## 6. 上线后冒烟验证

1. `curl https://你的域名/` → 返回前端 `index.html`
2. 浏览器开 `https://你的域名/plan`,确认底图正常加载(不报 Referer 校验失败)
3. 用默认成都示例点「生成方案」→ 真实出图、多色画线、按线路摘要正常
4. 填「最晚到达 09:00」→ 确认发车/到达时刻展示
5. CSV 批量导入选个文件 → 起点追加正常
6. 看后端日志:`sudo journalctl -u shuttle -f`,确认无 AK / 算路报错

排障速查:
- 地图白屏、控制台报 Referer 校验失败 → 浏览器端 AK 的域名白名单没配对
- 算路返回 `百度地图 AK 无效` → 服务端 AK 的 IP 白名单没加服务器公网 IP
- 前端能开但点生成方案 404/502 → Nginx `/api` 反代或后端 systemd 没起
- 生成方案转圈很久后失败 → 检查 Nginx `proxy_read_timeout` 与 axios timeout

---

## 7. 已知现状(演示站可接受,真实业务需补)

这些是当前代码的真实状态,演示站可以接受,但若日后转真实业务必须补:

- **接口无鉴权**:`/api/v1/route/plan` 任何人可调,会消耗百度 AK 配额。演示站可在 Nginx 层加简单限流(`limit_req`)或 IP 白名单兜底。
- **接口无应用层限流**:同上,AK 配额可能被刷。
- **全局异常回显**:`main.py` 的 `global_exception_handler` 把 `str(exc)` 直接返回前端,可能泄露内部信息。真实业务应改为返回通用错误、详情仅记日志。
- **无持久化**:每次请求即时算,不存历史。符合当前定位。
- **前后端若分域名部署**:需在 `main.py` 加 `CORSMiddleware` 并配置允许的源;本文同源方案规避了这一步。

---

## 附:更新部署(改了代码后)

```bash
cd /opt/shuttle && git pull
# 后端依赖有变动时:.venv/bin/pip install -r requirements.txt
sudo systemctl restart shuttle
# 前端有改动时:cd frontend && npm ci && npm run build(dist 自动被 Nginx 托管,无需重启)
```
