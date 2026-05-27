#!/bin/bash

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)
PROJECT_DIR="$SCRIPT_DIR"
VENV_DIR="$PROJECT_DIR/venv"
PID_FILE="$PROJECT_DIR/server.pid"
LOG_FILE="$PROJECT_DIR/server.log"

info() {
    echo -e "\033[1;34mINFO: $1\033[0m"
}

success() {
    echo -e "\033[1;32mSUCCESS: $1\033[0m"
}

error() {
    echo -e "\033[1;31mERROR: $1\033[0m" >&2
}

start_server_background() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            error "服务已在运行中 (PID: $PID)"
            return 1
        else
            info "发现旧的 PID 文件，正在清理..."
            rm -f "$PID_FILE"
        fi
    fi

    info "启动 Serial Server (后台模式)..."
    
    if [ ! -d "$VENV_DIR" ]; then
        error "虚拟环境不存在，请先运行 install.sh"
        return 1
    fi

    source "$VENV_DIR/bin/activate"
    
    nohup python "$PROJECT_DIR/main.py" > "$LOG_FILE" 2>&1 &
    PID=$!
    echo "$PID" > "$PID_FILE"
    
    sleep 2
    
    if kill -0 "$PID" 2>/dev/null; then
        success "服务启动成功 (PID: $PID)"
        info "日志文件: $LOG_FILE"
        info "访问地址: http://localhost:8000"
    else
        error "服务启动失败，请查看日志: $LOG_FILE"
        rm -f "$PID_FILE"
        return 1
    fi
}

start_server_foreground() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            error "服务已在运行中 (PID: $PID)"
            return 1
        fi
    fi

    info "启动 Serial Server (前台模式)..."
    info "按 Ctrl+C 停止服务"
    
    if [ ! -d "$VENV_DIR" ]; then
        error "虚拟环境不存在，请先运行 install.sh"
        return 1
    fi

    source "$VENV_DIR/bin/activate"
    python "$PROJECT_DIR/main.py"
}

stop_server() {
    if [ ! -f "$PID_FILE" ]; then
        error "服务未运行"
        return 1
    fi

    PID=$(cat "$PID_FILE")
    
    if kill -0 "$PID" 2>/dev/null; then
        info "停止服务 (PID: $PID)..."
        kill "$PID"
        
        for i in {1..10}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                success "服务已停止"
                rm -f "$PID_FILE"
                return 0
            fi
            sleep 1
        done
        
        error "强制停止服务..."
        kill -9 "$PID"
        rm -f "$PID_FILE"
        success "服务已强制停止"
    else
        info "服务已停止"
        rm -f "$PID_FILE"
    fi
}

status_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            success "服务运行中 (PID: $PID)"
            return 0
        else
            error "服务未运行 (PID 文件存在但进程不存在)"
            return 1
        fi
    else
        error "服务未运行"
        return 1
    fi
}

case "$1" in
    start)
        start_server_background
        ;;
    foreground|fg)
        start_server_foreground
        ;;
    stop)
        stop_server
        ;;
    restart)
        stop_server
        sleep 1
        start_server_background
        ;;
    status)
        status_server
        ;;
    *)
        echo "用法: $0 {start|foreground|fg|stop|restart|status}"
        echo ""
        echo "命令说明:"
        echo "  start       - 后台启动服务"
        echo "  foreground  - 前台启动服务 (调试用，Ctrl+C 停止)"
        echo "  fg          - 前台启动服务 (简写)"
        echo "  stop        - 停止服务"
        echo "  restart     - 重启服务"
        echo "  status      - 查看服务状态"
        exit 1
        ;;
esac