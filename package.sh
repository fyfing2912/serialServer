#!/bin/bash

set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
PROJECT_DIR="$SCRIPT_DIR"
PACKAGE_NAME="serial-server"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

info() {
    echo -e "\033[1;34mINFO: $1\033[0m"
}

success() {
    echo -e "\033[1;32mSUCCESS: $1\033[0m"
}

error() {
    echo -e "\033[1;31mERROR: $1\033[0m" >&2
    exit 1
}

info "开始打包 Serial Server..."

if [ ! -f "$PROJECT_DIR/main.py" ]; then
    error "项目主文件不存在"
fi

if [ ! -f "$PROJECT_DIR/requirements.txt" ]; then
    error "依赖文件不存在"
fi

rm -rf "$PROJECT_DIR/dist"
mkdir -p "$PROJECT_DIR/dist"

info "清理 macOS 扩展属性..."
find "$PROJECT_DIR" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.json" -o -name "*.html" -o -name "*.service" \) -exec xattr -c {} \; 2>/dev/null || true

info "创建项目压缩包..."
cd "$PROJECT_DIR/.."

if command -v gtar &>/dev/null; then
    TAR_CMD="gtar"
    info "使用 GNU tar"
else
    TAR_CMD="tar"
    info "使用系统 tar"
fi

COPYFILE_DISABLE=1 $TAR_CMD -czf "$PROJECT_DIR/dist/${PACKAGE_NAME}_${TIMESTAMP}.tar.gz" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='venv' \
    --exclude='*.log' \
    --exclude='*.pid' \
    --exclude='dist' \
    --exclude='*.pcap' \
    --exclude='.DS_Store' \
    --exclude='._*' \
    --exclude='*.tar.gz' \
    "$(basename "$PROJECT_DIR")"

if [ $? -eq 0 ]; then
    success "打包完成！"
    echo ""
    info "打包文件位置:"
    ls -la "$PROJECT_DIR/dist/"
    echo ""
    info "部署命令:"
    info "  scp dist/${PACKAGE_NAME}_${TIMESTAMP}.tar.gz user@server:/tmp/"
    info "  ssh user@server 'mkdir -p /opt/serial-server && tar -xzf /tmp/${PACKAGE_NAME}_${TIMESTAMP}.tar.gz -C /opt/serial-server --strip-components=1'"
else
    error "打包失败"
fi