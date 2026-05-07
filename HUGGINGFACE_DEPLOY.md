# 📚 背单词网站 - Hugging Face Spaces 部署指南

## 步骤 1：创建 Hugging Face 账号
打开 https://huggingface.co/join 注册账号（用 GitHub 登录最快）

## 步骤 2：创建 Space
1. 打开 https://huggingface.co/spaces
2. 点击 **"Create new Space"**
3. 填写：
   - **Owner:** 你的用户名
   - **Space name:** `vocabulary-app`
   - **License:** MIT
   - **Space SDK:** 选择 **Docker**
   - **Visibility:** Public

4. 点击 **"Create Space"**

## 步骤 3：连接 GitHub 仓库
1. 在 Space 页面，点击 **"Files"**
2. 点击 **"Add file"** → **"Import from GitHub"**
3. 输入仓库地址：`ranunculus1/vocabulary-app`
4. 点击 **"Import"**

## 步骤 4：等待部署
Hugging Face 会自动构建 Docker 镜像并部署，大约需要 5-10 分钟。

## 步骤 5：获取域名
部署完成后，域名格式：
```
https://huggingface.co/spaces/你的用户名/vocabulary-app
```

---

## ⚠️ 注意事项

### 1. 端口配置
Hugging Face Spaces 使用 **7860** 端口，`app.py` 需要支持 `--port` 和 `--host` 参数。

### 2. 数据库持久化
Hugging Face Spaces 是临时的，**重启后数据会丢失**！

**解决方案：**
- 使用 Hugging Face Datasets 存储数据
- 或者使用外部数据库（如 Neon PostgreSQL）

### 3. 免费限制
- **CPU Spaces:** 每月 100 小时免费
- **休眠:** 30 天无活动会自动休眠

---

## 🔧 修改 app.py 支持 Hugging Face

需要修改 `app.py` 让它支持命令行参数：

```python
if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--host', type=str, default='127.0.0.1')
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=False)
```

---

_最后更新：2026-05-07_
