# Deployment Notes

本文档记录一套可复用的 JobHunter 部署方式。仓库里不保存真实生产 IP、域名、服务器用户名或绝对路径，请按你自己的环境替换。

## 1. 部署变量

- 服务器登录: `deploy@your-server-ip`
- 项目目录: `/opt/jobhunter`
- 静态页面目录: `/var/www/jobhunter`
- Nginx 站点配置: `/etc/nginx/conf.d/jobhunter.conf`
- Nginx 容器名: `your-nginx-container`
- API 监听端口: `8090`
- systemd 服务名: `jobhunter-api.service`

上线后访问入口通常类似：

- `https://your-domain.example/jobhunter/`
- `https://your-domain.example/jobhunter-api/meta`
- `https://your-domain.example/jobhunter-api/latest`

## 2. 线上目录职责

`/opt/jobhunter` 存放源代码、抓取脚本、API 服务和定时刷新脚本。

`/var/www/jobhunter` 由 Nginx 对外提供静态页面。`run_job_digest.sh` 会把 `/opt/jobhunter/web/` 同步到这里。

## 3. 线上刷新机制

统一刷新入口：

```bash
cd /opt/jobhunter
JOBHUNTER_NGINX_HTML_DIR=/var/www/jobhunter /opt/jobhunter/run_job_digest.sh
```

脚本行为：

1. 读取项目根目录下的 `.env`
2. 执行 `python3 job_digest.py`
3. 如果 SMTP 环境变量完整，则附带发送邮件
4. 用 `rsync` 把 `web/` 同步到 Nginx 静态目录

## 4. cron

当前服务器上的定时任务是：

```cron
15 9 * * * cd /opt/jobhunter && JOBHUNTER_NGINX_HTML_DIR=/var/www/jobhunter /opt/jobhunter/run_job_digest.sh >> /opt/jobhunter/cron.log 2>&1
```

查看：

```bash
crontab -l
```

编辑：

```bash
crontab -e
```

## 5. API 服务

服务文件内容来自仓库内的 `jobhunter-api.service`。

安装 / 更新：

```bash
cp /opt/jobhunter/jobhunter-api.service /etc/systemd/system/jobhunter-api.service
systemctl daemon-reload
systemctl enable jobhunter-api.service
systemctl restart jobhunter-api.service
```

常用检查：

```bash
systemctl status jobhunter-api.service
journalctl -u jobhunter-api.service -n 200 --no-pager
curl -s http://127.0.0.1:8090/jobhunter-api/health
```

## 6. Nginx 反代

通常不直接暴露 `8090`，而是由现有 Docker 内 Nginx 统一转发。

注意：

- 因为 Nginx 跑在 Docker 容器里，反代 API 不能写 `127.0.0.1:8090`
- 常见做法是把宿主机地址写成 Docker 可访问的网关地址，例如 `172.17.0.1:8090`

如果改完配置，需要重载容器内 Nginx。

## 7. GitHub 更新流程

本地仓库远端：

```bash
git remote -v
```

当前 `origin`：

```text
git@github.com:GeT-LeFt/jobHunter.git
```

常规提交流程：

```bash
git status
git add .
git commit -m "docs: update deployment notes"
git push origin main
```

如果默认分支不是 `main`，先看：

```bash
git branch --show-current
```

再把 `main` 改成实际分支名。

## 8. 从 GitHub 拉到服务器

如果服务器已经配置好 GitHub SSH key，可以直接：

```bash
cd /opt/jobhunter
git pull origin main
```

如果服务器不走 `git pull`，也可以继续沿用当前做法，用 `scp` 直接覆盖上传：

```bash
scp api_server.py job_digest.py run_job_digest.sh deploy@your-server-ip:/opt/jobhunter/
scp -r web deploy@your-server-ip:/opt/jobhunter/
```

上传后手动执行一次：

```bash
ssh deploy@your-server-ip
cd /opt/jobhunter
JOBHUNTER_NGINX_HTML_DIR=/var/www/jobhunter ./run_job_digest.sh
systemctl restart jobhunter-api.service
```

## 9. 快速排障

页面有数据但按钮或布局没更新：

- 先确认静态目录文件是否同步
- 再确认浏览器是否命中了旧缓存
- 强刷页面再看

页面打不开 API：

- 先查 `systemctl status jobhunter-api.service`
- 再查 Nginx 反代配置
- 最后直接在服务器本机 `curl http://127.0.0.1:8090/jobhunter-api/health`

数据没刷新：

- 先手动执行 `/opt/jobhunter/run_job_digest.sh`
- 看 `/opt/jobhunter/cron.log`
- 看 `web/data/meta.json` 的 `generated_at_display`
