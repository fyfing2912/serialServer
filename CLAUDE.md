# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Software Serial Server - A Python TCP server simulator that implements Telnet/RFC2217 protocol to simulate serial port devices. Allows clients like PuTTY to connect via Telnet and receive rule-based responses or passthrough to real serial hardware.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server (development)
python main.py

# Start/stop/restart/status via script
./start_server.sh start|stop|restart|status

# First-time setup (creates config.json, installs service)
./install.sh
```

## Architecture

```
Client (PuTTY) → Telnet/RFC2217 → TCP Server (serial_server.py)
                                           ↓
                              SerialServerProtocol (Telnet state machine)
                                           ↓
              VirtualSerialPort (simulator) / PhysicalSerialPort (real hw)
                                           ↓
                              Rule Engine (match_rule) → response OR pass-through
```

## Key Modules

- **main.py** - FastAPI app (port 8000), REST API endpoints, static file serving
- **serial_server.py** - TCP server, RFC2217/Telnet state machine, rule engine (~760 lines)
- **config_manager.py** - JSON config read/write
- **static/index.html** - Web UI (Bootstrap 5, vanilla JS)
- **start_server.sh** - System V init script (start/stop/restart/status)
- **serial-server.service** - systemd service file for deployment

## API Endpoints

```
GET  /api/ports              - List all port configs
POST /api/ports              - Add new port
PUT  /api/ports/{port}       - Update port config
DELETE /api/ports/{port}     - Delete port
POST /api/service/start      - Start all enabled ports
POST /api/service/stop       - Stop all ports
GET  /api/serial-ports       - List available physical serial ports
```

## Configuration

Config stored in `config.json`. Each port has:
- `port`: listening port (must be unique)
- `enabled`: whether to start on service start
- `mode`: "simulator" (rule-based) or "passthrough" (real serial device)
- `serial_params`: baud_rate, data_bits, stop_bits, parity
- `response_rules`: ordered list of `{type: exact|contains|wildcard, match, reply}`

## Telnet/RFC2217 State Machine

States: `NORMAL / IAC / SB / SB_COM_PORT`

- `0xFF` (IAC) enters IAC state for protocol negotiation
- RFC2217 sub-negotiation (SETBAUD, SETDATASIZE, SETPARITY, etc.) handled in SB_COM_PORT state
- Non-IAC bytes go to rule engine for response

## No Test Framework

This project has no test files or test framework configured.

## Documentation

Design spec in `docs/设计规格说明书.md` (Chinese) - contains detailed protocol specifications and implementation details.