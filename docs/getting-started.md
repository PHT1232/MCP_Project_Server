# Hướng dẫn cài đặt và sử dụng `pcs`

Tài liệu kỹ thuật đầy đủ (tiếng Anh): [REQUIREMENTS.md](../REQUIREMENTS.md). Quy trình contributor: [AGENTS.md](../AGENTS.md).

## 1. Bạn sẽ có gì sau khi chạy xong

| Đường dẫn | Việc dùng |
|---|---|
| `http://127.0.0.1:8080/` | Giao diện web (control panel) |
| `http://127.0.0.1:8080/api` | HTTP JSON API |
| `http://127.0.0.1:8080/mcp` | MCP (streamable HTTP) |
| `127.0.0.1:5432` | PostgreSQL (chỉ loopback) |

Cổng mặc định là `8080`. Đổi bằng `PCS_PORT` trong `.env`.

## 2. Chuẩn bị

Cần Docker Compose v2. Clone repo, rồi tạo file cấu hình từ mẫu:

```bash
cp .env.example .env
```

Sửa `.env` cho máy của bạn. Không commit file `.env`.

Ít nhất hãy xem các biến sau:

- `PCS_PORT` — cổng xuất ra **máy host** (mặc định `8080`)
- `PCS_REPOS_DIR` — thư mục trên host chứa các repo cần index (mặc định `../repos`, tức `repos/` ở gốc repo này)
- `PCS_BIND_MODE=localhost` — chỉ lắng nghe loopback (an toàn cho máy local / VPS)

Compose **không** tự đọc `.env` ở gốc repo. Mọi lệnh `docker compose` đều phải có `--env-file .env`, nếu không biến môi trường sẽ bị bỏ qua im lặng.

## 3. Chạy Docker

Từ **gốc repo**:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml up --build --wait
```

Lệnh này build image, chạy Postgres + server, đợi healthcheck, rồi entrypoint chạy `alembic upgrade head` trước khi mở HTTP.

Kiểm tra Compose đã nạp `.env`:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml config \
  | grep PCS_AI_PROVIDER_ALLOWED_HOSTS
```

Sau khi sửa `.env`, recreate stack:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml \
  up -d --build --force-recreate --wait
```

Dừng stack (giữ volume dữ liệu):

```bash
docker compose --env-file .env -f deploy/docker-compose.yml down
```

`down -v` sẽ **xóa** volume Postgres — mất briefing, index, plan.

## 4. Kiểm tra server sống

```bash
curl -s http://127.0.0.1:8080/api/health
```

Mở trình duyệt: [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

Nếu bạn đổi `PCS_PORT=8989`, thay `8080` bằng `8989` trong mọi URL phía host.

## 5. Đăng ký một project

Container nhìn thấy `PCS_REPOS_DIR` tại `/repos`. Đăng ký đường dẫn **trong container**, không phải đường dẫn host.

Ví dụ repo demo nằm ở `repos/` trên host (tương ứng `/repos` trong container):

```bash
curl -s -X POST http://127.0.0.1:8080/api/projects \
  -H 'content-type: application/json' \
  -d '{"name":"demo","root_path":"/repos","overview":"Project demo local."}'

curl -s http://127.0.0.1:8080/api/projects/demo/briefing
```

Khi host chứa nhiều repo, đặt `PCS_REPOS_DIR` tới thư mục cha rồi đăng ký `/repos/<tên-thư-mục>`.

Tìm kiếm ngữ nghĩa (embedding) tắt mặc định. Tìm theo từ khóa và cấu trúc vẫn dùng được.

Gỡ đăng ký **không** xóa file trên đĩa — chỉ xóa dữ liệu pcs (briefing, index, plan). Tên project được dùng lại:

```bash
curl -s -X DELETE http://127.0.0.1:8080/api/projects/demo
```

Trên UI: chọn project → Unregister / xóa, rồi gõ đúng tên project để xác nhận.

## 6. Kết nối MCP

### Streamable HTTP (stack Docker)

```text
http://127.0.0.1:8080/mcp
```

### stdio (chạy trên host, cùng máy với repo)

Thư mục làm việc phải là `server/`:

```json
{
  "command": "uv",
  "args": ["run", "pcs", "stdio"],
  "cwd": "/đường/dẫn/tuyệt/đối/tới/mcp_server/server"
}
```

Mọi lời gọi MCP dùng **đúng** tên hoặc id project. Frontend JSON API nằm riêng dưới `/api`.

Lần đầu mở session agent, gọi tool `onboard` với tên project.

## 7. Plan và task

Tách việc thành plan + DAG task, claim bằng lease hết hạn, rồi đẩy tới hoàn thành — qua MCP, HTTP, hoặc trang Plans (`/projects/:project/plans`). Hoàn thành task **không** đổi trạng thái requirement.

```bash
PLAN=$(curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans/with-tasks \
  -H 'content-type: application/json' \
  -d '{"title":"Ship checkout","goal":"Migrate off the legacy gateway","tasks":[
        {"local_task_id":"t1","title":"Add pricing helper","objective":"Implement unit_price."}
      ]}')
PLAN_ID=$(echo "$PLAN" | jq -r .id)
curl -s -X POST http://127.0.0.1:8080/api/projects/demo/plans/$PLAN_ID/activate
curl -s http://127.0.0.1:8080/api/projects/demo/ready-tasks
```

Nhà cung cấp AI cấu hình ở [AI Settings](http-api.md#global-ai-provider-settings-t20) có thể đề xuất nháp (`generate_plan_draft` / `POST .../plans/generate-draft`). Nháp chỉ mang tính gợi ý cho đến khi bạn duyệt và tạo plan thật bằng `create_plan_with_tasks`. Chi tiết: [Architecture](architecture.md#plan--task-orchestration).

## 8. VPS: cổng tùy chỉnh và Tailscale có sẵn trên host

Muốn xuất PCS trên loopback VPS cổng `8989`, ghi vào `.env`:

```dotenv
PCS_PORT=8989
PCS_BIND_MODE=localhost
PCS_BIND_ADDRESS=0.0.0.0
```

`PCS_PORT=8989` là cổng **host**. Bên trong container, server vẫn lắng nghe `8080`:

```yaml
environment:
  PCS_PORT: "8080"
ports:
  - "127.0.0.1:${PCS_PORT:-8080}:8080"
```

Áp dụng `.env` rồi kiểm tra:

```bash
docker compose --env-file .env -f deploy/docker-compose.yml \
  up -d --build --force-recreate --wait
curl http://127.0.0.1:8989/api/health
```

Mapping đúng: `127.0.0.1:8989->8080/tcp`. `PCS_BIND_ADDRESS=0.0.0.0` chỉ áp dụng **trong** container; Docker vẫn chỉ publish ra loopback của VPS.

Nếu Tailscale **đã** chạy trên VPS, **đừng** dùng `deploy/docker-compose.tailscale.yml` và **đừng** đặt `TS_AUTHKEY`. Proxy dịch vụ loopback qua daemon có sẵn:

```bash
tailscale status
sudo tailscale serve --bg http://127.0.0.1:8989
tailscale serve status
```

Từ máy khác trên cùng tailnet, mở URL HTTPS mà `tailscale serve status` in ra:

```text
https://<tên-vps>.<tailnet>.ts.net/
https://<tên-vps>.<tailnet>.ts.net/api/health
https://<tên-vps>.<tailnet>.ts.net/mcp
```

Không bật `tailscale funnel` — Funnel công khai dịch vụ ra internet. Gỡ proxy riêng bằng `sudo tailscale serve reset`.

File overlay `deploy/docker-compose.tailscale.yml` chỉ dành cho host cần PCS chạy như một node Tailscale tách biệt.

## 9. Phát triển trên máy (không dùng image production)

Cài dependency và Postgres:

```bash
just setup
just up
just migrate
```

Chạy server ở hai terminal, từ gốc repo:

```bash
# Terminal 1
(cd server && uv run pcs http)

# Terminal 2
(cd web && npm run dev)
```

Vite proxy `/api` tới `http://127.0.0.1:8080`. Cổng kiểm tra toàn repo:

```bash
just check
```

## 10. Tài liệu chi tiết (tiếng Anh)

- [Architecture](architecture.md)
- [Configuration reference](configuration.md)
- [MCP tools and resources](mcp-reference.md)
- [HTTP API](http-api.md)
- [Deployment, persistence, and Tailscale](deploy.md)
- [VPS troubleshooting runbook](troubleshooting.md)
