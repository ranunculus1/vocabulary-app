# 🦋 背单词网站部署到 Cloudflare Tunnel

## 前提条件
- Cloudflare 账号（免费）
- 一个域名（可选，不用域名也可以用 quick link）

## 步骤

### 1. 安装 cloudflared
```bash
# 下载
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
chmod +x cloudflared-linux-amd64
sudo mv cloudflared-linux-amd64 /usr/local/bin/cloudflared
```

### 2. 登录 Cloudflare
```bash
cloudflared tunnel login
```
会打开浏览器让饭团登录 Cloudflare 账号

### 3. 创建隧道
```bash
cloudflared tunnel create vocabulary
```
会输出隧道 ID，记下来！

### 4. 配置隧道
创建配置文件 `~/.cloudflared/config.yml`：
```yaml
tunnel: <隧道 ID>
credentials-file: /home/node/.cloudflared/<隧道 ID>.json

ingress:
  - hostname: vocabulary.yourdomain.com  # 如果有域名
    service: http://localhost:5000
  - service: http_status:404
```

**不用域名的话用 quick link：**
```bash
cloudflared tunnel --url http://localhost:5000
```
会生成一个随机但固定的 URL！

### 5. 运行隧道
```bash
cloudflared tunnel run vocabulary
```

### 6. 后台运行（可选）
```bash
nohup cloudflared tunnel run vocabulary > /tmp/cloudflared.log 2>&1 &
```

---

## 更简单的方案：直接用 quick link

```bash
# 一条命令搞定
cloudflared tunnel --url http://localhost:5000
```

**输出会是一个固定的 URL，类似：**
`https://xxxx-xxxx-xxxx.trycloudflare.com`

**这个 URL 重启后还是一样的！**

---

## 自动化脚本

创建 `/home/node/.openclaw/workspace/vocabulary-app/start-cloudflare.sh`：
```bash
#!/bin/bash
cd $(dirname $0)

# 启动 Flask
nohup python3 app.py > /tmp/flask.log 2>&1 &
echo "Flask 已启动 (PID: $!)"

# 启动 Cloudflare Tunnel
cloudflared tunnel --url http://localhost:5000
```

---

## 验证

访问生成的 URL，应该能看到背单词网站！
