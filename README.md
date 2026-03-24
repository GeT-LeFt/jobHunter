# JobHunter

自动抓取深圳、广州、香港范围内与日语或日本市场相关的公开岗位，筛成每日岗位摘要，并输出网页、JSON 和可选邮件。

## 当前能力

- 抓取公开岗位源并合并结果
- 按日语 / 日本市场 / 市场、销售、运营、翻译、分析等方向做筛选
- 分成 `高匹配春招` 和 `补充关注`
- 记录历史并标记 `is_new`
- 输出静态网页数据到 `web/data/`
- 提供轻量 API，便于网页和后续小程序复用
- 支持手动刷新和定时刷新
- 配了 SMTP 时可自动发邮件

## 目录说明

- `job_digest.py`: 抓取、筛选、生成 JSON / HTML / 邮件
- `api_server.py`: Python 标准库实现的轻量 API
- `run_job_digest.sh`: 统一刷新入口，会执行抓取并同步 `web/` 到服务器静态目录
- `jobhunter-api.service`: systemd 服务文件
- `web/`: 前端静态页面
- `web/data/latest.json`: 岗位列表
- `web/data/meta.json`: 刷新时间、岗位总数等元信息
- `job_digest_output/`: 本地运行生成的 HTML / JSON / 历史状态

## 本地运行

先生成最新数据：

```bash
python3 job_digest.py
```

输出文件：

- `job_digest_output/latest.html`
- `job_digest_output/latest.json`
- `web/data/latest.json`
- `web/data/meta.json`

本地预览网页：

```bash
python3 -m http.server 8000
```

打开：

- `http://127.0.0.1:8000/web/`

## 邮件发送

只有在配置以下环境变量后，`run_job_digest.sh` 才会自动发邮件：

- `JOBDIGEST_SMTP_HOST`
- `JOBDIGEST_SMTP_PORT`
- `JOBDIGEST_SMTP_USER`
- `JOBDIGEST_SMTP_PASSWORD`
- `JOBDIGEST_MAIL_FROM`
- `JOBDIGEST_MAIL_TO`

手动测试：

```bash
python3 job_digest.py --send-email
```

如果没配置 SMTP，脚本只会刷新数据，不会报错退出。

## API

默认由 `api_server.py` 提供：

- `GET /jobhunter-api/health`
- `GET /jobhunter-api/meta`
- `GET /jobhunter-api/latest`
- `GET /jobhunter-api/jobs?region=深圳&category=高匹配春招`
- `POST /jobhunter-api/refresh`

其中 `meta` 会返回：

- `generated_at`
- `generated_at_display`
- `timezone`
- `total_jobs`
- `priority_jobs`
- `new_jobs`

## 上线后访问方式

请替换成你自己的域名或服务器地址：

- `https://your-domain.example/jobhunter/`
- `http://your-server-ip/jobhunter/`

API 示例：

- `https://your-domain.example/jobhunter-api/meta`
- `https://your-domain.example/jobhunter-api/latest`

## 运维说明

完整部署、systemd、cron、Nginx 反代、GitHub 更新流程见 [DEPLOY.md](./DEPLOY.md)。

## macOS 定时执行

仓库里保留了 `com.cynthia.jobdigest.jpmarkets.plist.template`，本地如果要继续用 `launchd`：

```bash
cp com.cynthia.jobdigest.jpmarkets.plist.template ~/Library/LaunchAgents/com.cynthia.jobdigest.jpmarkets.plist
launchctl unload ~/Library/LaunchAgents/com.cynthia.jobdigest.jpmarkets.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.cynthia.jobdigest.jpmarkets.plist
```
