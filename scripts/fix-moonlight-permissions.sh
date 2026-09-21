#!/bin/bash
# Fix Moonlight macOS Gatekeeper and TCC permissions
# Run AFTER copying the built .app to /Applications
# Usage: bash scripts/fix-moonlight-permissions.sh

APP_NAME="$(bash "$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-$0}")" && pwd)/product-name.sh" 2>/dev/null || echo MoonlightEnhanced)"
APP_PATH="${1:-/Applications/${APP_NAME}.app}"
BUNDLE_ID="${MOONLIGHT_BUNDLE_ID:-std.skyhua.MoonlightMac2}"

echo "=== Moonlight 权限修复脚本 ==="
echo ""

if [ ! -d "$APP_PATH" ]; then
    echo "错误: 未找到 $APP_PATH"
    echo "请先将 ${APP_NAME}.app 复制到 /Applications（或把完整路径作为参数传给本脚本）"
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
echo "4. 校验代码签名..."
# Gatekeeper assessment is deliberately not consulted. A build signed with an
# Apple Development certificate always fails it, which is normal and not a
# block; reporting "rejected" only sent users hunting for a dialog that macOS
# never showed. Signature integrity is the thing worth checking here.
SIGN_RESULT=$(codesign --verify --strict --verbose=2 "$APP_PATH" 2>&1)
if [ $? -eq 0 ]; then
    echo "   签名: 通过完整性校验"
else
    echo "   签名: 校验失败"
    echo "$SIGN_RESULT" | sed 's/^/      /'
    echo ""
    echo "   若为自签或 ad-hoc 构建，首次启动请右键点击 Moonlight → 打开 → 确认。"
fi

echo ""
echo "5. 其他权限 (麦克风 / 输入监控) 的处理方式..."
# tccutil reset All would also revoke microphone and input monitoring, which is
# far broader than fixing local network access and forces the user to redo
# unrelated grants. Only mention the escape hatch instead of pulling it.
echo "   这些权限请在应用内首次请求时授权。"
echo "   如确需重置全部权限，请手动执行: tccutil reset All \"$BUNDLE_ID\""

echo ""
echo "=== 修复完成 ==="
echo "请启动 Moonlight，当弹出网络权限请求时点击 '允许'。"
