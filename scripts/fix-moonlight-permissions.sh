#!/bin/bash
# Fix Moonlight macOS Gatekeeper and TCC permissions
# Run AFTER copying Moonlight.app to /Applications
# Usage: bash scripts/fix-moonlight-permissions.sh

APP_PATH="/Applications/Moonlight.app"
BUNDLE_ID="std.skyhua.MoonlightMac2"

echo "=== Moonlight 权限修复脚本 ==="
echo ""

if [ ! -d "$APP_PATH" ]; then
    echo "错误: 未找到 $APP_PATH"
    echo "请先将 Moonlight.app 复制到 /Applications"
    exit 1
fi

echo "1. 移除隔离属性 (com.apple.quarantine)..."
xattr -d com.apple.quarantine "$APP_PATH" 2>/dev/null
echo "   完成"

echo ""
echo "2. 重新注册到 LaunchServices..."
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister"
if [ -f "$LSREGISTER" ]; then
    "$LSREGISTER" -f "$APP_PATH" 2>/dev/null
    echo "   完成"
else
    echo "   lsregister 不可用，跳过"
fi

echo ""
echo "3. 重置本地网络权限..."
tccutil reset LocalNetwork "$BUNDLE_ID" 2>/dev/null
echo "   完成 (如失败，请在 系统设置 → 隐私与安全性 → 本地网络 中手动开启)"

echo ""
echo "4. 重置所有 TCC 权限..."
tccutil reset All "$BUNDLE_ID" 2>/dev/null
echo "   完成"

echo ""
echo "5. 验证 Gatekeeper 状态..."
GK_RESULT=$(spctl --assess --verbose=4 "$APP_PATH" 2>&1)
if echo "$GK_RESULT" | grep -q "accepted"; then
    echo "   Gatekeeper: ✅ 已接受"
else
    echo "   Gatekeeper: ❌ 被拒绝"
    echo ""
    echo "   请执行以下操作之一："
    echo "   方法 A (推荐): 右键点击 Moonlight → 打开 → 确认"
    echo "   方法 B: 系统设置 → 隐私与安全性 → 点击 '仍要打开' 按钮"
fi

echo ""
echo "=== 修复完成 ==="
echo "请启动 Moonlight，当弹出网络权限请求时点击 '允许'。"
