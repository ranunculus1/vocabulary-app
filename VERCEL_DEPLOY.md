# 📚 背单词网站 - Vercel 部署指南

## 步骤 1：准备 GitHub 仓库

### 1.1 创建新仓库
1. 打开 https://github.com/new
2. 仓库名：`vocabulary-app`
3. 设为 **Public**（Vercel 免费计划需要）
4. 点击 **Create repository**

### 1.2 上传代码
```bash
cd /home/node/.openclaw/workspace/vocabulary-app
git init
git add .
git commit -m "Initial commit - vocabulary app for Vercel"
git branch -M main
git remote add origin https://github.com/你的用户名/vocabulary-app.git
git push -u origin main
```

---

## 步骤 2：连接 Vercel

### 2.1 注册/登录 Vercel
1. 打开 https://vercel.com
2. 点击 **Login** → 选择 **GitHub**
3. 授权 Vercel 访问 GitHub

### 2.2 导入项目
1. 点击 **Add New Project**
2. 选择 **Import Git Repository**
3. 找到 `vocabulary-app` 仓库
4. 点击 **Import**

### 2.3 配置项目
- **Framework Preset**: `Other`
- **Root Directory**: `./`
- **Build Command**: 留空
- **Output Directory**: 留空
- **Install Command**: `pip install -r requirements.txt`

### 2.4 添加环境变量（重要！）
在 Vercel 项目设置 → **Environment Variables** 添加：
- `DATABASE_URL`: 数据库连接字符串（如果用 Neon）

### 2.5 点击 Deploy

---

## 步骤 3：获取域名

部署成功后，Vercel 会给你：
- **生产域名**: `vocabulary-app-xxx.vercel.app`
- **预览域名**: `vocabulary-app-git-main-xxx.vercel.app`

---

## ⚠️ 注意事项

### SQLite 问题
Vercel 是 Serverless 架构，**SQLite 文件不会持久化**！

**解决方案：**
1. **方案 A**：使用 Vercel Blob 存储 SQLite 文件
2. **方案 B**：迁移到 PostgreSQL（推荐 Neon）
3. **方案 C**：把单词数据硬编码到代码里（只读）

### 当前状态
- ✅ 前端页面可以正常部署
- ⚠️ 后端 API 需要改造为 Serverless 函数
- ⚠️ 数据库需要迁移到云服务

---

## 🚀 快速测试（只部署前端）

如果只是想测试，可以先只部署前端静态文件：

```bash
# 安装 Vercel CLI
npm i -g vercel

# 部署
cd /home/node/.openclaw/workspace/vocabulary-app
vercel --prod
```

---

_最后更新：2026-05-06_
