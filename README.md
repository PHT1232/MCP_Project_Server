# pcs — Bộ nhớ dự án dùng chung cho AI coding agent

**pcs** (Project Context MCP Server) là nơi lưu ngữ cảnh dự án mà mọi AI coding agent — Claude, hay bất kỳ agent nào nói được MCP — cùng đọc và cùng ghi. Thay vì mỗi phiên làm việc agent lại đoán lại từ đầu "dự án này là gì, quy ước ra sao, ai đang làm gì," pcs giữ tất cả những thứ đó lại: bền, có cấu trúc, và luôn cập nhật.

## Vấn đề pcs giải quyết

- **Agent quên sạch giữa các phiên.** Mở lại một task hôm qua, agent lại phải đọc lại toàn bộ codebase, đoán lại convention, không biết ai đã quyết định gì và vì sao. pcs giữ focus, quyết định, quy ước, bug đã biết — agent chỉ cần hỏi, không cần dò lại.
- **`grep` toàn bộ file để tìm một hàm rất tốn token.** `search_code` tìm theo từ khóa, ký hiệu, và ngữ nghĩa — trả về đúng đoạn liên quan thay vì cả file. Trên chính repo này, 202 lượt gọi thực tế đã dùng 154 nghìn token thay vì 6,8 triệu token nếu đọc trực tiếp — tiết kiệm khoảng 98%.
- **Nhiều agent cùng đụng một codebase, giẫm chân nhau.** Plan/task có DAG phụ thuộc thật, claim bằng lease hết hạn tự động, task phía sau chỉ mở khi task trước hoàn thành — hai agent không thể vô tình sửa cùng một chỗ cùng lúc.
- **"Test xanh" không có nghĩa là yêu cầu đã thật sự xong.** Mỗi requirement có invariant, acceptance criteria, và bằng chứng bắt buộc phải ghi lại (commit thật, kết quả test thật) trước khi được đóng — close gate kiểm tra, không tin lời agent tự báo.
- **Prompt bàn giao cho agent khác (kể cả agent yếu hơn) hay bị bỏ sót bước.** `prepare_task` sinh sẵn prompt tự đầy đủ: gọi tool nào, project/plan/task nào, quy ước và quyết định liên quan nào cần biết — agent nhận prompt không cần đoán.

## pcs làm được gì

| | |
|---|---|
| **Briefing & bộ nhớ dự án** | Focus, blocker, bug, quy ước, quyết định — nén gọn theo ngân sách token, không qua LLM, luôn xác định (deterministic). |
| **Tìm kiếm mã nguồn** | Từ khóa + ký hiệu + ngữ nghĩa, có xếp hạng, biết báo khi kết quả bị cắt bớt. |
| **Bản đồ code & codebase guide** | Duyệt cấu trúc repo theo tầng, agent để lại ghi chú bền trên từng file cho phiên sau. |
| **Plan & task orchestration** | DAG phụ thuộc, claim có lease, tự mở task kế tiếp khi điều kiện xong — nhiều agent làm việc an toàn trên cùng một plan. |
| **Requirement contract & close gate** | Invariant + acceptance criteria + bằng chứng bắt buộc trước khi đánh dấu hoàn thành. |
| **Theo dõi tiết kiệm token** | Đo thật, không ước lượng: mỗi lần truy xuất so với việc đọc toàn bộ file gốc. |
| **Control panel** | Giao diện web quản lý project, plan, requirement, code map — không cần thuộc lòng API. |

Chi tiết đầy đủ (tiếng Anh): [REQUIREMENTS.md](REQUIREMENTS.md) · [Architecture](docs/architecture.md) · [MCP tools reference](docs/mcp-reference.md)

## Bắt đầu nhanh

Cần Docker Compose v2.

```bash
cp .env.example .env
docker compose --env-file .env -f deploy/docker-compose.yml up --build --wait
curl -s http://127.0.0.1:8080/api/health
```

Mở [http://127.0.0.1:8080/](http://127.0.0.1:8080/) để vào control panel, hoặc trỏ MCP client tới `http://127.0.0.1:8080/mcp`.

Hướng dẫn đầy đủ — đăng ký project, kết nối MCP, tạo plan/task đầu tiên, chạy VPS với Tailscale, phát triển local — nằm ở **[docs/getting-started.md](docs/getting-started.md)**.

## Tài liệu

- [Hướng dẫn cài đặt và sử dụng đầy đủ](docs/getting-started.md)
- [Architecture](docs/architecture.md)
- [Configuration reference](docs/configuration.md)
- [MCP tools and resources](docs/mcp-reference.md)
- [HTTP API](docs/http-api.md)
- [Deployment, persistence, and Tailscale](docs/deploy.md)
- [VPS troubleshooting runbook](docs/troubleshooting.md)
- [Quy trình contributor](AGENTS.md)
