"""TCP Server with RFC2217 Telnet protocol support and physical serial port integration."""
import asyncio
import logging
import struct
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

try:
    import serial
    import serial.tools.list_ports
    PYSERIAL_AVAILABLE = True
except ImportError:
    PYSERIAL_AVAILABLE = False

logger = logging.getLogger("serial_server")

# Telnet constants
IAC = 0xFF
WILL = 0xFB
WONT = 0xFC
DO = 0xFD
DONT = 0xFE
SB = 0xFA
SE = 0xF0

# RFC2217 constants
COM_PORT_OPTION = 44  # 0x2C, RFC2217 COM-PORT-OPTION
COM_PORT_CMD = 0x00

# RFC2217 sub-option commands
SETBAUD = 1
SETDATASIZE = 2
SETPARITY = 3
SETSTOPSIZE = 4
SETCONTROL = 5
SETFLOW = 6
SUSPEND = 7

PARITY_MAP = {0: "None", 1: "Odd", 2: "Even", 3: "Mark", 4: "Space"}
PARITY_REVERSE = {v: k for k, v in PARITY_MAP.items()}


def unescape(s: str) -> str:
    s = s.replace('\\r', '\r')
    s = s.replace('\\n', '\n')
    s = s.replace('\\\\', '\\')
    return s


def match_rule(data: bytes, rules: List[Dict[str, str]]) -> bytes:
    try:
        text = data.decode('utf-8', errors='replace')
    except:
        return data
    
    for rule in rules:
        match_pattern = rule.get('match', '')
        reply_pattern = rule.get('reply', '')
        
        rule_type = rule.get('type', 'exact')
        
        if rule_type == 'exact':
            if text == match_pattern:
                logger.debug(f"Rule matched: exact '{match_pattern}'")
                return reply_pattern.encode('utf-8')
        elif rule_type == 'contains':
            if match_pattern in text:
                logger.debug(f"Rule matched: contains '{match_pattern}'")
                return reply_pattern.encode('utf-8')
        elif rule_type == 'wildcard':
            if match_pattern.endswith(' *'):
                prefix = match_pattern[:-2]
                if text.startswith(prefix):
                    logger.debug(f"Rule matched: wildcard '{match_pattern}'")
                    return reply_pattern.encode('utf-8')
    
    return data


class TelnetStateMachine:
    NORMAL = 'NORMAL'
    IAC = 'IAC'
    SB = 'SB'
    SB_COM_PORT = 'SB_COM_PORT'
    
    def __init__(self):
        self.state = self.NORMAL
        self.sb_option = None
        self.sb_buffer = bytearray()
        self.iac_command = None
        self.option_byte = None
    
    def reset(self):
        self.state = self.NORMAL
        self.sb_option = None
        self.sb_buffer = bytearray()
        self.iac_command = None
        self.option_byte = None


def _unescape_rules(rules: List[Dict[str, str]]) -> List[Dict[str, str]]:
    escaped_rules = []
    for rule in rules:
        escaped_rule = {
            'type': rule.get('type', 'exact'),
            'match': unescape(rule.get('match', '')),
            'reply': unescape(rule.get('reply', ''))
        }
        escaped_rules.append(escaped_rule)
    return escaped_rules


def list_serial_ports() -> List[Dict[str, str]]:
    """List available serial ports."""
    ports = []
    if not PYSERIAL_AVAILABLE:
        return ports
    try:
        comports = serial.tools.list_ports.comports()
        for port in comports:
            ports.append({
                'device': port.device,
                'description': port.description,
                'hwid': port.hwid
            })
    except Exception as e:
        logger.error(f"Failed to list serial ports: {e}")
    return ports


class PhysicalSerialPort:
    """Manages physical serial port connection and data transfer."""
    
    def __init__(self, port_config: Dict[str, Any]):
        self.port_config = port_config
        self.serial_port: Optional[serial.Serial] = None
        self.read_thread: Optional[threading.Thread] = None
        self.running = False
        self.on_data_received: Optional[Callable[[bytes], None]] = None
        self.executor = ThreadPoolExecutor(max_workers=2)
        self._lock = threading.Lock()
    
    def connect(self) -> bool:
        """Connect to the physical serial port."""
        if not PYSERIAL_AVAILABLE:
            logger.error("❌ [物理串口] pyserial 库未安装，无法连接物理串口")
            return False
        
        with self._lock:
            try:
                params = self.port_config.get('serial_params', {})
                device = self.port_config.get('serial_device', '')
                
                if not device:
                    logger.error("❌ [物理串口] 未指定串口设备")
                    return False
                
                # Map parameters to pyserial values
                baudrate = params.get('baud_rate', 9600)
                bytesize_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
                bytesize = bytesize_map.get(params.get('data_bits', 8), serial.EIGHTBITS)
                
                parity_map = {
                    'None': serial.PARITY_NONE,
                    'Odd': serial.PARITY_ODD,
                    'Even': serial.PARITY_EVEN,
                    'Mark': serial.PARITY_MARK,
                    'Space': serial.PARITY_SPACE
                }
                parity = parity_map.get(params.get('parity', 'None'), serial.PARITY_NONE)
                
                stopbits_map = {
                    '1': serial.STOPBITS_ONE,
                    '1.5': serial.STOPBITS_ONE_POINT_FIVE,
                    '2': serial.STOPBITS_TWO
                }
                stopbits = stopbits_map.get(params.get('stop_bits', '1'), serial.STOPBITS_ONE)
                
                logger.info(f"🔄 [物理串口] 正在连接 {device}: {baudrate}/{params.get('data_bits', 8)}/{params.get('stop_bits', '1')}/{params.get('parity', 'None')}")
                
                self.serial_port = serial.Serial(
                    port=device,
                    baudrate=baudrate,
                    bytesize=bytesize,
                    parity=parity,
                    stopbits=stopbits,
                    timeout=0.1
                )
                
                self.running = True
                self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
                self.read_thread.start()
                logger.info(f"Successfully connected to {device}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to connect to serial port: {e}")
                self.serial_port = None
                return False
    
    def disconnect(self):
        """Disconnect from the physical serial port."""
        with self._lock:
            logger.info(f"🔌 [物理串口] 正在断开连接...")
            self.running = False
            
            if self.read_thread and self.read_thread.is_alive():
                self.read_thread.join(timeout=1.0)
            
            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.close()
                    logger.info(f"✅ [物理串口] 串口已关闭")
                except Exception as e:
                    logger.error(f"❌ [物理串口] 关闭串口时出错: {e}")
                self.serial_port = None
            
            logger.info(f"✅ [物理串口] 断开连接完成")
    
    def _read_loop(self):
        """Read data from serial port in background thread."""
        logger.info(f"📖 [物理串口] 串口读取线程已启动")
        while self.running and self.serial_port and self.serial_port.is_open:
            try:
                if self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    if data and self.on_data_received:
                        logger.info(f"📥 [物理串口] 线程读取到 {len(data)} 字节: {data.hex()}")
                        self.on_data_received(data)
                else:
                    threading.Event().wait(0.01)
            except Exception as e:
                if self.running:
                    logger.error(f"❌ [物理串口] 读取串口时出错: {e}")
                    break
        logger.info(f"📴 [物理串口] 串口读取线程已退出")
    
    def write(self, data: bytes) -> bool:
        """Write data to serial port."""
        with self._lock:
            if not self.serial_port or not self.serial_port.is_open:
                logger.warning(f"⚠️ [物理串口] 尝试写入但串口未连接")
                return False
            
            try:
                bytes_written = self.serial_port.write(data)
                logger.info(f"📤 [物理串口] 写入 {bytes_written} 字节: {data.hex()}")
                return True
            except Exception as e:
                logger.error(f"❌ [物理串口] 写入数据时出错: {e}")
                return False
    
    def update_parameters(self, new_params: Dict[str, Any]) -> bool:
        """Update serial port parameters."""
        with self._lock:
            if not self.serial_port or not self.serial_port.is_open:
                logger.warning("Serial port not connected, cannot update parameters")
                return False
            
            try:
                if 'baud_rate' in new_params:
                    self.serial_port.baudrate = new_params['baud_rate']
                if 'data_bits' in new_params:
                    bytesize_map = {5: serial.FIVEBITS, 6: serial.SIXBITS, 7: serial.SEVENBITS, 8: serial.EIGHTBITS}
                    self.serial_port.bytesize = bytesize_map.get(new_params['data_bits'], serial.EIGHTBITS)
                if 'parity' in new_params:
                    parity_map = {
                        'None': serial.PARITY_NONE,
                        'Odd': serial.PARITY_ODD,
                        'Even': serial.PARITY_EVEN,
                        'Mark': serial.PARITY_MARK,
                        'Space': serial.PARITY_SPACE
                    }
                    self.serial_port.parity = parity_map.get(new_params['parity'], serial.PARITY_NONE)
                if 'stop_bits' in new_params:
                    stopbits_map = {
                        '1': serial.STOPBITS_ONE,
                        '1.5': serial.STOPBITS_ONE_POINT_FIVE,
                        '2': serial.STOPBITS_TWO
                    }
                    self.serial_port.stopbits = stopbits_map.get(new_params['stop_bits'], serial.STOPBITS_ONE)
                
                self.port_config['serial_params'].update(new_params)
                logger.info(f"Serial port parameters updated: {new_params}")
                return True
            except Exception as e:
                logger.error(f"Error updating serial parameters: {e}")
                return False
    
    def is_connected(self) -> bool:
        """Check if serial port is connected."""
        with self._lock:
            return self.serial_port is not None and self.serial_port.is_open


class VirtualSerialPort:
    def __init__(self, port: int, serial_params: Dict[str, Any], response_rules: List[Dict[str, str]], 
                 serial_device: str = '', mode: str = 'simulator'):
        self.port = port
        self.serial_params = serial_params.copy()
        self.response_rules = _unescape_rules(response_rules)
        self.serial_device = serial_device
        self.mode = mode  # 'simulator' or 'physical'
        self._lock = asyncio.Lock()
        self.physical_port: Optional[PhysicalSerialPort] = None
    
    async def update_params(self, new_params: Dict[str, Any]):
        async with self._lock:
            self.serial_params.update(new_params)
            logger.info(f"Port {self.port} params updated: {self.serial_params}")
            
            if self.mode == 'physical' and self.physical_port:
                self.physical_port.update_parameters(new_params)
    
    async def update_rules(self, rules: List[Dict[str, str]]):
        async with self._lock:
            self.response_rules = _unescape_rules(rules)
            logger.info(f"Port {self.port} rules updated: {len(rules)} rules")
    
    async def get_params(self) -> Dict[str, Any]:
        async with self._lock:
            return self.serial_params.copy()
    
    async def get_rules(self) -> List[Dict[str, str]]:
        async with self._lock:
            return [r.copy() for r in self.response_rules]
    
    async def connect_physical(self) -> bool:
        """Connect to physical serial port if in physical mode."""
        if self.mode != 'physical':
            logger.warning(f"⚠️ [物理串口] 尝试连接但模式不是 physical")
            return False
        
        logger.info(f"🔄 [物理串口] 正在创建连接...")
        port_config = {
            'serial_device': self.serial_device,
            'serial_params': self.serial_params
        }
        self.physical_port = PhysicalSerialPort(port_config)
        result = self.physical_port.connect()
        if result:
            logger.info(f"✅ [物理串口] 物理串口连接已建立")
        return result
    
    async def disconnect_physical(self):
        """Disconnect from physical serial port."""
        if self.physical_port:
            self.physical_port.disconnect()
            self.physical_port = None


class SerialServerProtocol(asyncio.Protocol):
    def __init__(self, port_config: VirtualSerialPort, on_client_disconnect: Callable):
        self.port_config = port_config
        self.on_client_disconnect = on_client_disconnect
        self.transport = None
        self.state_machine = TelnetStateMachine()
        self.read_buffer = bytearray()
        self.data_buffer = bytearray()
        self.loop = asyncio.get_event_loop()
    
    def connection_made(self, transport: asyncio.Transport):
        self.transport = transport
        peername = transport.get_extra_info('peername')
        logger.info(f"🔗 [连接] 客户端连接到端口 {self.port_config.port}: {peername}")
        logger.info(f"📡 [连接] 模式: {self.port_config.mode}, 串口设备: {self.port_config.serial_device or 'N/A'}")
        
        # Handle COM_PORT_OPTION negotiation
        logger.info(f"📨 [Telnet] 发送 WILL COM_PORT_OPTION ({COM_PORT_OPTION}) 等待客户端响应...")
        self._send_telnet_command(WILL, COM_PORT_OPTION)
    
    def connection_lost(self, exc: Optional[Exception]):
        peername = self.transport.get_extra_info('peername') if self.transport else None
        logger.info(f"Client disconnected from port {self.port_config.port}: {peername}")
        
        # Disconnect physical port if connected
        if self.port_config.mode == 'physical' and self.port_config.physical_port:
            self.port_config.physical_port.on_data_received = None
        
        self.on_client_disconnect(self.port_config.port)
    
    def _send_telnet_command(self, cmd: int, option: int):
        """Send a Telnet command."""
        if self.transport:
            self.transport.write(bytes([IAC, cmd, option]))
            logger.debug(f"Sent Telnet command: IAC {cmd:02X} {option:02X}")
    
    def data_received(self, data: bytes):
        logger.debug(f"📥 [数据] 接收数据 on port {self.port_config.port}: {data.hex()}")
        self.read_buffer.extend(data)
        self.process_buffer()
    
    def process_buffer(self):
        while self.read_buffer:
            byte = self.read_buffer.pop(0)
            
            if self.state_machine.state == TelnetStateMachine.NORMAL:
                if byte == IAC:
                    self.state_machine.state = TelnetStateMachine.IAC
                else:
                    self.handle_data(byte)
            
            elif self.state_machine.state == TelnetStateMachine.IAC:
                if byte == IAC:
                    self.handle_data(byte)
                    self.state_machine.state = TelnetStateMachine.NORMAL
                elif byte in (WILL, WONT, DO, DONT):
                    self.state_machine.iac_command = byte
                    self.state_machine.state = TelnetStateMachine.IAC
                elif byte == SB:
                    self.state_machine.state = TelnetStateMachine.SB
                    self.state_machine.sb_buffer = bytearray()
                elif byte == SE:
                    self.state_machine.state = TelnetStateMachine.NORMAL
                else:
                    if self.state_machine.iac_command is not None:
                        self._handle_telnet_option(self.state_machine.iac_command, byte)
                        self.state_machine.iac_command = None
                    self.state_machine.state = TelnetStateMachine.NORMAL
            
            elif self.state_machine.state == TelnetStateMachine.SB:
                if self.state_machine.sb_option is None:
                    self.state_machine.sb_option = byte
                    if byte == COM_PORT_OPTION:
                        self.state_machine.state = TelnetStateMachine.SB_COM_PORT
                else:
                    self.state_machine.sb_buffer.append(byte)
            
            elif self.state_machine.state == TelnetStateMachine.SB_COM_PORT:
                if byte == IAC:
                    if self.read_buffer:
                        next_byte = self.read_buffer.pop(0)
                        if next_byte == IAC:
                            self.state_machine.sb_buffer.append(IAC)
                        elif next_byte == SE:
                            self.handle_rfc2217_subnegotiation()
                            self.state_machine.reset()
                        else:
                            logger.warning(f"Invalid IAC sequence in SB")
                            self.state_machine.reset()
                    else:
                        self.state_machine.sb_buffer.append(byte)
                else:
                    self.state_machine.sb_buffer.append(byte)
    
    def _handle_telnet_option(self, cmd: int, option: int):
        """Handle Telnet option negotiation."""
        cmd_names = {WILL: 'WILL', WONT: 'WONT', DO: 'DO', DONT: 'DONT'}
        cmd_name = cmd_names.get(cmd, f'0x{cmd:02X}')
        opt_names = {1: 'ECHO', 3: 'SUPPRESS_GO_AHEAD', 44: 'COM_PORT_OPTION'}
        opt_name = opt_names.get(option, f'0x{option:02X}')
        
        logger.info(f"📨 [Telnet] 收到选项协商: IAC {cmd_name} {opt_name} ({option})")
        
        if option == COM_PORT_OPTION:
            logger.info(f"✅ [RFC2217] 准备进入 COM_PORT_OPTION 协商模式")
            if cmd == WILL:
                logger.info(f"📤 [RFC2217] 发送 DO COM_PORT_OPTION 确认")
                self._send_telnet_command(DO, COM_PORT_OPTION)
            elif cmd == DO:
                logger.info(f"📤 [RFC2217] 发送 WILL COM_PORT_OPTION 确认")
                self._send_telnet_command(WILL, COM_PORT_OPTION)
            elif cmd == WONT:
                logger.info(f"📤 [Telnet] 发送 DONT COM_PORT_OPTION")
                self._send_telnet_command(DONT, COM_PORT_OPTION)
            elif cmd == DONT:
                logger.info(f"📤 [Telnet] 发送 WONT COM_PORT_OPTION")
                self._send_telnet_command(WONT, COM_PORT_OPTION)
        else:
            logger.debug(f"🔍 [Telnet] 其他选项 {opt_name} 暂不处理")
    
    def handle_data(self, byte: int):
        """Handle normal data byte."""
        self.data_buffer.append(byte)
        
        # In physical mode, send immediately or buffer
        if self.port_config.mode == 'physical':
            # For physical mode, buffer and send in chunks or on newline
            if byte in (0x0D, 0x0A, 0x00) or len(self.data_buffer) >= 1024:
                data = bytes(self.data_buffer)
                self.data_buffer = bytearray()
                self._send_to_physical(data)
        else:
            # Simulator mode: use rule engine
            if byte in (0x0D, 0x0A, 0x00):
                data = bytes(self.data_buffer)
                self.data_buffer = bytearray()
                asyncio.create_task(self.process_serial_data(data))
    
    def _send_to_physical(self, data: bytes):
        """Send data to physical serial port."""
        if self.port_config.mode == 'physical' and self.port_config.physical_port:
            self.port_config.physical_port.write(data)
    
    async def process_serial_data(self, data: bytes):
        """Process data in simulator mode using rule engine."""
        logger.info(f"📥 [模拟器] 收到数据: {data!r} (hex: {data.hex()})")
        rules = await self.port_config.get_rules()
        response = match_rule(data, rules)
        
        if response:
            logger.info(f"📤 [模拟器] 规则匹配响应: {response!r}")
            self.transport.write(response)
    
    def _on_physical_data_received(self, data: bytes):
        """Callback when data is received from physical serial port."""
        logger.info(f"📥 [物理串口] 从串口接收: {data!r} (hex: {data.hex()})")
        if self.transport:
            # Need to escape IAC bytes in data
            escaped_data = bytearray()
            for byte in data:
                escaped_data.append(byte)
                if byte == IAC:
                    escaped_data.append(IAC)
            logger.info(f"📤 [网络] 发送到客户端: {bytes(escaped_data)!r}")
            self.transport.write(bytes(escaped_data))
    
    def handle_rfc2217_subnegotiation(self):
        """Handle RFC2217 subnegotiation."""
        buffer = bytes(self.state_machine.sb_buffer)
        logger.info(f"🔐 [RFC2217] 收到子协商: {buffer.hex()}")
        
        if len(buffer) < 2:
            logger.warning("⚠️ [RFC2217] 子协商数据太短，无效")
            return
        
        cmd = buffer[1]
        params = buffer[2:]
        
        cmd_names = {
            SETBAUD: 'SETBAUD (设置波特率)',
            SETDATASIZE: 'SETDATASIZE (设置数据位)',
            SETPARITY: 'SETPARITY (设置校验位)',
            SETSTOPSIZE: 'SETSTOPSIZE (设置停止位)',
            SETCONTROL: 'SETCONTROL (设置控制)',
            SETFLOW: 'SETFLOW (设置流控)',
            SUSPEND: 'SUSPEND (暂停)'
        }
        cmd_name = cmd_names.get(cmd, f'未知命令 ({cmd})')
        
        logger.info(f"📋 [RFC2217] 命令: {cmd_name}")
        
        response_data = bytearray([COM_PORT_CMD, cmd])
        new_params = {}
        
        if cmd == SETBAUD:
            if len(params) == 4:
                baud_rate = struct.unpack('>I', params)[0]
                new_params['baud_rate'] = baud_rate
                logger.info(f"   └─ 波特率: {baud_rate} bps")
                response_data.extend(params)
            else:
                logger.warning(f"   └─ ⚠️ 波特率参数长度错误: {len(params)}")
        
        elif cmd == SETDATASIZE:
            if len(params) == 1 and params[0] in (5, 6, 7, 8):
                data_bits = params[0]
                new_params['data_bits'] = data_bits
                logger.info(f"   └─ 数据位: {data_bits}")
                response_data.extend(params)
            else:
                logger.warning(f"   └─ ⚠️ 数据位参数错误: {params[0] if params else 'N/A'}")
        
        elif cmd == SETPARITY:
            if len(params) == 1 and params[0] in PARITY_MAP:
                parity = PARITY_MAP[params[0]]
                new_params['parity'] = parity
                logger.info(f"   └─ 校验位: {parity}")
                response_data.extend(params)
            else:
                logger.warning(f"   └─ ⚠️ 校验位参数错误: {params[0] if params else 'N/A'}")
        
        elif cmd == SETSTOPSIZE:
            if len(params) == 1 and params[0] in (1, 2, 3):
                stop_bits_map = {1: '1', 2: '1.5', 3: '2'}
                stop_bits = stop_bits_map[params[0]]
                new_params['stop_bits'] = stop_bits
                logger.info(f"   └─ 停止位: {stop_bits}")
                response_data.extend(params)
            else:
                logger.warning(f"   └─ ⚠️ 停止位参数错误: {params[0] if params else 'N/A'}")
        
        elif cmd == SETCONTROL:
            logger.info(f"   └─ 控制参数: {params.hex()}")
            response_data.extend(params)
        
        elif cmd == SETFLOW:
            logger.info(f"   └─ 流控参数: {params.hex()}")
            response_data.extend(params)
        
        elif cmd == SUSPEND:
            logger.info(f"   └─ 暂停命令")
        
        else:
            logger.warning(f"⚠️ [RFC2217] 未知命令: {cmd}")
            return
        
        # Update parameters
        if new_params:
            if self.port_config.mode == 'physical':
                logger.info(f"✅ [RFC2217] 正在应用到物理串口: {new_params}")
            else:
                logger.info(f"✅ [RFC2217] 更新模拟器参数: {new_params}")
            asyncio.create_task(self.port_config.update_params(new_params))
        
        # Send response
        response = bytes([IAC, SB, COM_PORT_OPTION]) + bytes(response_data) + bytes([IAC, SE])
        logger.info(f"📤 [RFC2217] 发送响应: {response.hex()}")
        self.transport.write(response)


class SerialServerManager:
    def __init__(self, config):
        self.config = config
        self.servers: Dict[int, asyncio.AbstractServer] = {}
        self.virtual_ports: Dict[int, VirtualSerialPort] = {}
        self.running_ports: Dict[int, bool] = {}
        self.clients: Dict[int, SerialServerProtocol] = {}
    
    async def start_all(self) -> None:
        from config_manager import load_config
        config = load_config()
        for port_config in config.get('ports', []):
            if port_config.get('enabled', False):
                port = port_config['port']
                await self.start_port(port)
    
    async def stop_all(self) -> None:
        for port in list(self.servers.keys()):
            await self.stop_port(port)
    
    async def start_port(self, port: int) -> bool:
        if port in self.servers:
            logger.warning(f"⚠️ 端口 {port} 已经运行")
            return False
        
        from config_manager import load_config
        config = load_config()
        port_config = None
        
        for p in config.get('ports', []):
            if p['port'] == port:
                port_config = p
                break
        
        if not port_config or not port_config.get('enabled', False):
            logger.warning(f"⚠️ 端口 {port} 未找到或未启用")
            return False
        
        try:
            mode = port_config.get('mode', 'simulator')
            serial_device = port_config.get('serial_device', '')
            
            logger.info(f"🚀 [启动] 准备启动端口 {port}")
            logger.info(f"   ├─ 模式: {mode}")
            logger.info(f"   ├─ 串口设备: {serial_device or 'N/A'}")
            logger.info(f"   ├─ 波特率: {port_config.get('serial_params', {}).get('baud_rate', 9600)}")
            logger.info(f"   ├─ 数据位: {port_config.get('serial_params', {}).get('data_bits', 8)}")
            logger.info(f"   ├─ 停止位: {port_config.get('serial_params', {}).get('stop_bits', '1')}")
            logger.info(f"   └─ 校验位: {port_config.get('serial_params', {}).get('parity', 'None')}")
            
            virtual_port = VirtualSerialPort(
                port=port,
                serial_params=port_config.get('serial_params', {}),
                response_rules=port_config.get('response_rules', []),
                serial_device=serial_device,
                mode=mode
            )
            self.virtual_ports[port] = virtual_port
            
            # Connect physical port if in physical mode
            if mode == 'physical':
                logger.info(f"🔗 [物理串口] 准备连接到 {serial_device}")
                connected = await virtual_port.connect_physical()
                if not connected:
                    logger.error(f"❌ [物理串口] 连接到 {serial_device} 失败！")
                else:
                    logger.info(f"✅ [物理串口] 成功连接到 {serial_device}")
            
            async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
                peername = writer.get_extra_info('peername')
                logger.info(f"🚀 [客户端处理] 开始处理来自 {peername} 的连接")
                protocol = SerialServerProtocol(virtual_port, self.on_client_disconnect)
                protocol.connection_made(writer.transport)
                self.clients[port] = protocol
                
                # Set up physical port callback
                if virtual_port.mode == 'physical' and virtual_port.physical_port:
                    virtual_port.physical_port.on_data_received = protocol._on_physical_data_received
                    logger.info(f"🔗 [物理串口] 已绑定数据回调")
                
                try:
                    while True:
                        data = await reader.read(1024)
                        if not data:
                            logger.info(f"🔌 [客户端] 客户端 {peername} 关闭连接")
                            break
                        logger.info(f"📥 [客户端] 收到 {len(data)} 字节 from {peername}: {data.hex()}")
                        protocol.data_received(data)
                except asyncio.CancelledError:
                    logger.info(f"⚠️ [客户端] 处理被取消")
                except Exception as e:
                    logger.error(f"❌ [客户端] 处理错误: {e}")
                finally:
                    protocol.connection_lost(None)
                    if port in self.clients:
                        del self.clients[port]
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except:
                        pass
            
            server = await asyncio.start_server(handle_client, '0.0.0.0', port)
            self.servers[port] = server
            self.running_ports[port] = True
            logger.info(f"✅ [启动] 端口 {port} 监听成功 (模式: {mode})")
            logger.info(f"   └─ 等待客户端连接...")
            return True
        
        except Exception as e:
            logger.error(f"❌ [启动] 启动端口 {port} 失败: {e}")
            if port in self.virtual_ports:
                await self.virtual_ports[port].disconnect_physical()
                del self.virtual_ports[port]
            return False
    
    async def stop_port(self, port: int) -> bool:
        if port not in self.servers:
            return False
        
        try:
            # Disconnect physical port
            if port in self.virtual_ports:
                await self.virtual_ports[port].disconnect_physical()
            
            server = self.servers[port]
            server.close()
            await server.wait_closed()
            del self.servers[port]
            self.running_ports[port] = False
            if port in self.virtual_ports:
                del self.virtual_ports[port]
            logger.info(f"Stopped port {port}")
            return True
        except Exception as e:
            logger.error(f"Failed to stop port {port}: {e}")
            return False
    
    async def restart_port(self, port: int) -> bool:
        await self.stop_port(port)
        await asyncio.sleep(0.1)
        return await self.start_port(port)
    
    def is_port_running(self, port: int) -> bool:
        return self.running_ports.get(port, False)
    
    def get_running_ports(self) -> List[int]:
        return [port for port, running in self.running_ports.items() if running]
    
    def on_client_disconnect(self, port: int):
        logger.info(f"🔌 [回调] 端口 {port} 客户端断开处理完成")
