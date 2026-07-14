# 日语 / 日本市场岗位日报

## 已实现

- 抓取深圳、广州、香港公开岗位页
- 按日语 / 日本市场 / 语言、市场、分析类方向筛选
- 将岗位分成“高匹配春招”和“补充关注”
- 记录历史，标记“新发现”岗位
- 输出 `HTML + JSON`
- 生成可直接部署的静态网页 `web/`
- 提供轻量 API：`/jobhunter-api/meta`、`/jobhunter-api/latest`、`/jobhunter-api/jobs`
- 可选通过 SMTP 发邮件

## 先跑本地摘要

```bash
python3 job_digest.py
```

输出目录：

- `job_digest_output/latest.html`
- `job_digest_output/latest.json`
- `web/data/latest.json`

## 本地预览网页

```bash
python3 -m http.server 8000
```

然后打开：

- `http://127.0.0.1:8000/web/`

## 开启邮件

1. 复制模板：

```bash
cp .env.example .env
```

2. 填写 `.env`

3. 手动测试：

```bash
python3 job_digest.py --send-email
```

## 定时执行（macOS）

1. 把模板拷贝到 `~/Library/LaunchAgents/`
2. 去掉 `.template` 后缀
3. 执行：

```bash
launchctl unload ~/Library/LaunchAgents/com.cynthia.jobdigest.jpmarkets.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.cynthia.jobdigest.jpmarkets.plist
```

默认每天 `09:00` 执行一次，可在 plist 里改时间。

## 服务器部署

静态网页只需要部署整个 `web/` 目录，并确保定时任务持续刷新 `web/data/latest.json`。
