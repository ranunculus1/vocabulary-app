#!/bin/bash
# 🦋 背单词网站启动脚本

cd /home/node/.openclaw/workspace/vocabulary-app

echo "🦋 芭德卡特背单词网站"
echo "======================"
echo ""

# 检查 Flask 进程
if pgrep -f "python3 app.py" > /dev/null; then
    echo "✅ Flask 已在运行"
else
    echo "🚀 启动 Flask..."
    nohup python3 app.py > /tmp/vocabulary-app.log 2>&1 &
    sleep 2
fi

# 检查 Cloudflare 进程
if pgrep -f "cloudflared tunnel" > /dev/null; then
    echo "⚠️  Cloudflare 隧道已在运行（但 URL 可能已失效）"
    echo "   建议：pkill -f cloudflared 然后重新启动"
else
    echo "🌐 启动 Cloudflare Tunnel..."
    nohup ./cloudflared tunnel --url http://localhost:5000 > /tmp/cloudflared.log 2>&1 &
    sleep 8
fi

# 等待并显示 URL
echo ""
echo "=== 等待隧道初始化 ==="
sleep 3
URL=$(tail -10 /tmp/cloudflared.log | grep "trycloudflare.com" | sed 's/.*|  \\(https:\\/\\/[^ ]*\\).*/\\1/' | head -1)

if [ -n "$URL" ]; then
    echo ""
    echo "🎉 网站已启动！"
    echo "🌐 访问地址：$URL"
    echo ""
    echo "📱 用手机浏览器访问这个 URL"
else
    echo "⚠️  未能获取 URL，请检查 /tmp/cloudflared.log"
fi
