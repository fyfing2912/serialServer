#!/bin/bash

set -e

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/venv"

info() {
    echo -e "\033[1;34mINFO: $1\033[0m"
}

success() {
    echo -e "\033[1;32mSUCCESS: $1\033[0m"
}

warning() {
    echo -e "\033[1;33mWARNING: $1\033[0m"
}

error() {
    echo -e "\033[1;31mERROR: $1\033[0m" >&2
    exit 1
}

info "开始安装 Serial Server..."

info "检查 Python3..."
if ! command -v python3 &>/dev/null; then
    warning "Python3 未安装，尝试检查指定版本..."
    if command -v /usr/local/bin/python3.11 &>/dev/null; then
        info "找到 Python 3.11，设置为默认"
        PYTHON_CMD="/usr/local/bin/python3.11"
    else
        error "Python3 未找到，请先安装 Python3"
    fi
else
    PYTHON_CMD="python3"
fi

info "检查 pip..."
if ! command -v pip3 &>/dev/null; then
    if command -v /usr/local/bin/pip3.11 &>/dev/null; then
        PIP_CMD="/usr/local/bin/pip3.11"
    else
        error "pip3 未安装"
    fi
else
    PIP_CMD="pip3"
fi

info "创建虚拟环境..."
$PYTHON_CMD -m venv "$VENV_DIR" || error "创建虚拟环境失败"

info "激活虚拟环境并安装依赖..."
source "$VENV_DIR/bin/activate"
pip install --upgrade pip
pip install -r "$PROJECT_DIR/requirements.txt" || error "安装依赖失败"

info "检查串口权限..."
if ! groups | grep -q dialout; then
    info "当前用户不在 dialout 组中"
    if sudo -n true 2>/dev/null; then
        info "添加当前用户到 dialout 组..."
        sudo usermod -aG dialout "$USER"
        info "用户已添加到 dialout 组，需要重新登录才能生效"
    else
        warning "没有管理员权限，无法自动添加到 dialout 组"
        warning "如果需要使用物理串口，请联系管理员执行：sudo usermod -aG dialout $USER"
    fi
fi

success "安装完成，Good!"
echo ""
info "使用方法："
info "  启动服务: $PROJECT_DIR/start_server.sh"
info "  停止服务: $PROJECT_DIR/start_server.sh stop"
info "  查看状态: $PROJECT_DIR/start_server.sh status"