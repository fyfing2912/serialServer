"""FastAPI entry point for Serial Server Simulator."""
import asyncio
import logging
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Path
from fastapi.staticfiles import StaticFiles

from config_manager import load_config, save_config
from serial_server import SerialServerManager, list_serial_ports

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("main")

app = FastAPI(title="Software Serial Server", version="1.0")

config = load_config()
server_manager = SerialServerManager(config)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    from fastapi.responses import FileResponse
    return FileResponse("static/index.html")


@app.get("/api/ports", response_model=List[Dict[str, Any]])
async def get_ports():
    config = load_config()
    return config.get("ports", [])


@app.post("/api/ports")
async def add_port(port_config: Dict[str, Any]):
    config = load_config()
    ports = config.get("ports", [])
    
    port = port_config.get("port")
    if not port or not isinstance(port, int):
        raise HTTPException(status_code=400, detail="端口号必须为整数")
    
    for p in ports:
        if p["port"] == port:
            raise HTTPException(status_code=400, detail=f"端口 {port} 已存在")
    
    new_port = {
        "port": port,
        "enabled": port_config.get("enabled", False),
        "mode": port_config.get("mode", "simulator"),
        "serial_device": port_config.get("serial_device", ""),
        "serial_params": port_config.get("serial_params", {
            "baud_rate": 9600,
            "data_bits": 8,
            "stop_bits": "1",
            "parity": "None"
        }),
        "response_rules": port_config.get("response_rules", [])
    }
    
    ports.append(new_port)
    config["ports"] = ports
    save_config(config)
    
    if new_port["enabled"]:
        await server_manager.start_port(port)
    
    return {"success": True, "message": f"端口 {port} 已添加"}


@app.put("/api/ports/{port}")
async def update_port(
    port: int = Path(..., description="当前监听端口号"),
    port_config: Dict[str, Any] = None
):
    config = load_config()
    ports = config.get("ports", [])
    
    port_index = None
    for i, p in enumerate(ports):
        if p["port"] == port:
            port_index = i
            break
    
    if port_index is None:
        raise HTTPException(status_code=404, detail=f"端口 {port} 不存在")
    
    new_port_num = port_config.get("port")
    if new_port_num is not None and new_port_num != port:
        raise HTTPException(status_code=400, detail="监听端口号不可修改，如需更改请删除后新建")
    
    current_port = ports[port_index]
    
    if "enabled" in port_config:
        current_port["enabled"] = port_config["enabled"]
    
    if "mode" in port_config:
        current_port["mode"] = port_config["mode"]
    
    if "serial_device" in port_config:
        current_port["serial_device"] = port_config["serial_device"]
    
    if "serial_params" in port_config:
        current_port["serial_params"].update(port_config["serial_params"])
    
    if "response_rules" in port_config:
        current_port["response_rules"] = port_config["response_rules"]
    
    save_config(config)
    
    if current_port["enabled"]:
        await server_manager.restart_port(port)
    
    return {"success": True, "message": f"端口 {port} 已更新"}


@app.delete("/api/ports/{port}")
async def delete_port(port: int = Path(..., description="要删除的端口号")):
    config = load_config()
    ports = config.get("ports", [])
    
    port_index = None
    for i, p in enumerate(ports):
        if p["port"] == port:
            port_index = i
            break
    
    if port_index is None:
        raise HTTPException(status_code=404, detail=f"端口 {port} 不存在")
    
    await server_manager.stop_port(port)
    del ports[port_index]
    config["ports"] = ports
    save_config(config)
    
    return {"success": True, "message": f"端口 {port} 已删除"}


@app.get("/api/serial-ports", response_model=List[Dict[str, Any]])
async def get_serial_ports():
    """Get list of available physical serial ports."""
    return list_serial_ports()


@app.post("/api/service/start")
async def start_service():
    await server_manager.start_all()
    config = load_config()
    config["service_running"] = True
    save_config(config)
    return {"success": True, "message": "所有已启用端口已启动"}


@app.post("/api/service/stop")
async def stop_service():
    await server_manager.stop_all()
    config = load_config()
    config["service_running"] = False
    save_config(config)
    return {"success": True, "message": "所有端口已停止"}


@app.get("/api/service/status")
async def get_service_status():
    running_ports = server_manager.get_running_ports()
    return {
        "service_running": len(running_ports) > 0,
        "running_ports": running_ports
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
