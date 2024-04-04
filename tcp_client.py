import asyncio
import json
import logging
from blinker import signal

logger = logging.getLogger(__name__)


class Device:
    def __init__(self, device_id):
        self.device_id = device_id
        self.online = False
        self.properties = {}
        self.inputs = {}

    def set_online(self, online):
        self.online = online

    def update_properties(self, properties):
        self.properties.update(properties)

    def update_input(self, input_id, input_properties):
        self.inputs[input_id] = input_properties

    def get_input(self, input_id):
        return self.inputs.get(input_id, None)


class TCPClient:
    RECONNECT_TIME = 3
    KEEP_ALIVE_TIME = 3
    SLEEP_TIME = 3
    USLEEP_TIME = 0.01
    MSG_SEPARATOR = '\x00'

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.connected = False
        self.approved = None
        self.reader = None
        self.writer = None
        self.devices = {}  # Track devices by their IDs
        self.connection_signal = signal('connection_change')
        # Lock for thread-safe operations on `self.connected`
        self.connection_lock = asyncio.Lock()
        self.tasks = []  # List to keep track of tasks

    async def start(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            async with self.connection_lock:
                self.connected = True
            self.connection_signal.send(connected=True)
            logger.info("Connected to TCP")
            await self.send_get_devices()
            self.tasks.append(asyncio.create_task(self.poll_for_response()))
            self.tasks.append(asyncio.create_task(self.start_keep_alive()))
        except Exception as e:
            logger.error(f"Connection error: {e}")
            async with self.connection_lock:
                self.connected = False
            self.connection_signal.send(connected=False)
            await asyncio.sleep(self.RECONNECT_TIME)
            self.tasks.append(asyncio.create_task(self.start()))

    async def send_message(self, msg):
        async with self.connection_lock:
            if not self.connected:
                logger.error("Not connected to server.")
                return
        tcp_message = f"{msg}{self.MSG_SEPARATOR}"
        try:
            self.writer.write(tcp_message.encode('utf-8'))
            await self.writer.drain()
            logger.debug(f"Sent: {tcp_message}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            async with self.connection_lock:
                self.connected = False
            self.connection_signal.send(connected=False)
            asyncio.create_task(self.start())

    async def poll_for_response(self):
        while True:
            async with self.connection_lock:
                if not self.connected:
                    break
            try:
                response = await self.reader.readuntil(separator=self.MSG_SEPARATOR.encode('utf-8'))
                message = response.decode('utf-8').rstrip(self.MSG_SEPARATOR)
                asyncio.create_task(self.handle_message(message))
            except asyncio.IncompleteReadError:
                logger.info("Server closed the connection.")
                async with self.connection_lock:
                    self.connected = False
                self.connection_signal.send(connected=False)
                break
            except asyncio.CancelledError:
                logger.info("Polling for response cancelled.")
                break
            except Exception as e:
                logger.error(f"Error while reading from server: {e}")
                async with self.connection_lock:
                    self.connected = False
                self.connection_signal.send(connected=False)
                break
            await asyncio.sleep(self.SLEEP_TIME)

    async def close(self):
        if self.writer:
            self.writer.close()
            asyncio.create_task(self.writer.wait_closed())
        async with self.connection_lock:
            self.connected = False
        self.connection_signal.send(connected=False)
        async for task in self.tasks:
            try:
                await task.cancel()
            except Exception as e:
                logger.error(f"Error while cancelling task: {e}")
        self.tasks.clear()

    async def handle_message(self, msg):
        try:
            message_data = json.loads(msg)
            json_path = message_data['path'].split('/')

            if json_path[0] == 'devices':
                if len(json_path) == 1:  # -> /devices
                    # -> /devices
                    # Handle the list of devices
                    children_keys = message_data['data']['children'].keys()
                    for dev_id in children_keys:
                        await self.send_get_device(dev_id)
                elif len(json_path) == 2:
                    # -> /devices/id
                    dev_id = json_path[1]
                    if dev_id not in self.devices:  # Create a new Device instance
                        self.devices[dev_id] = Device(dev_id)
                    self.devices[dev_id].update_properties(
                        message_data['data'])
                    await self.send_get_inputs(dev_id)
                elif json_path[2] == 'DeviceOnline':
                    # -> /devices/id/DeviceOnline
                    dev_id = json_path[1]
                    # Update device online status
                    online = message_data['data']
                    if dev_id in self.devices:
                        self.devices[dev_id].set_online(online)
                elif json_path[2] == 'inputs' and len(json_path) == 4:
                    # -> /devices/id/inputs/id
                    dev_id = json_path[1]
                    input_id = json_path[3]  # Update input properties
                    if dev_id in self.devices:
                        self.devices[dev_id].update_input(
                            input_id, message_data['data'])
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")

    # Helper method to extract children keys from message data
    def get_json_children(self, message_data):
        try:
            data = json.loads(message_data)
            children = data.get('data', {}).get('children', {})
            return list(children.keys())
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None

    async def start_keep_alive(self):
        while self.connected:
            await self.send_message("set /Sleep false")
            await asyncio.sleep(self.KEEP_ALIVE_TIME)

    async def send_get_devices(self):
        await self.send_message("get /devices")

    def get_tapered_level(self, value):
        tapered = value / 100
        tapered = 1 / 1.27 * tapered
        return tapered

    def get_float_value(self, value):
        floaty = value / 100
        floaty = 2 / 1.27 * floaty
        floaty = floaty - 1
        return floaty

    def get_bool(self, value):
        return value > 0

    async def send_update_message(self, mapping, value):
        mix = mapping['mix']
        dev_id = mapping['deviceId']
        input_id = mapping['inputId']
        if mix == 'Inputs':
            await self.send_volume_message(dev_id, input_id, value)
        elif mix == 'Gain':
            await self.send_gain_preamp_message(dev_id, input_id, value)
        elif mix in ['Pad', 'Phase', 'LowCut', '48V']:
            await self.send_bool_preamp_message(dev_id, input_id, mix, value)
        elif mix in ['Solo', 'Mute']:
            await self.send_bool_message(dev_id, input_id, mix, value)
        elif mix.startswith('Send'):
            send_id = mix[-1]
            await self.send_gain_send_message(dev_id, input_id, send_id, value)
        elif mix == 'Pan':
            await self.send_float_message(dev_id, input_id, mix, value)

    async def send_bool_message(self, dev_id, input_id, property, value):
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/{property}/value {str(self.get_bool(value))}")

    async def send_bool_preamp_message(self, dev_id, input_id, property, value):
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/preamps/0/{property}/value {str(self.get_bool(value))}")

    async def send_gain_send_message(self, dev_id, input_id, send_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/sends/{send_id}/GainTapered/value {tapered_level:.6f}")

    async def send_gain_preamp_message(self, dev_id, input_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/preamps/0/GainTapered/value {tapered_level:.6f}")

    async def send_volume_message(self, dev_id, input_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/FaderLevelTapered/value {tapered_level:.6f}")

    async def send_float_message(self, dev_id, input_id, property, value):
        float_value = self.get_float_value(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/{property}/value {float_value:.6f}")

    async def send_get_device(self, dev_id):
        await self.send_message(f"get /devices/{dev_id}")
        await self.send_message(f"subscribe /devices/{dev_id}/DeviceOnline")

    async def send_get_inputs(self, dev_id):
        await self.send_message(f"get /devices/{dev_id}/inputs")

    async def send_get_input(self, dev_id, input_id):
        await self.send_message(f"get /devices/{dev_id}/inputs/{input_id}")
        await self.send_message(f"get /devices/{dev_id}/inputs/{input_id}/sends")

    def get_data_as_bool(self, json_data):
        try:
            json_dict = json.loads(json_data)
            data = json_dict.get("data", {})
            if isinstance(data, bool):
                return data
            elif isinstance(data, dict) and 'value' in data:
                return bool(data['value'])
            else:
                return None
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None

    async def handle_message(self, msg):
        try:
            message_data = json.loads(msg)
            json_path = message_data['path'].split('/')

            if json_path[0] == 'devices':
                if len(json_path) == 1:  # -> /devices
                    # -> /devices
                    pass
                elif len(json_path) == 2:
                    # -> /devices/id
                    dev_id = json_path[1]
                    # Create a new Device instance
                    self.devices[dev_id] = Device(dev_id)
                    children_keys = self.get_json_children(msg) or []
                    for child_id in children_keys:
                        await self.send_get_device(child_id)
                    children_keys = self.get_json_children(msg) or []
                    for dev_id in children_keys:
                        await self.send_get_device(dev_id)
                elif json_path[2] == 'DeviceOnline':
                    # -> /devices/id/DeviceOnline
                    dev_id = json_path[1]
                    online = self.get_data_as_bool(msg)
                    if online is None:
                        logger.error(
                            f"Invalid data for device online status: {msg}")
                        return
                    if dev_id in self.devices:
                        # Update device online status
                        self.devices[dev_id].set_online(online)
                    # Signal device online status change
                    self.connection_signal.send(
                        device_id=dev_id, online=online)
                elif json_path[2] == 'inputs':
                    dev_id = json_path[1]
                    if len(json_path) == 3:
                        # -> /devices/id/inputs
                        children_keys = self.get_json_children(msg) or []
                        for input_id in children_keys:
                            await self.send_get_input(dev_id, input_id)
                    elif len(json_path) == 4:
                        # -> /devices/id/inputs/id
                        input_id = json_path[3]
                        if dev_id in self.devices:
                            input_data = message_data['data']
                            self.devices[dev_id].update_input(
                                input_id, input_data)  # Update input properties
                        # Signal input information received
                        self.connection_signal.send(
                            device_id=dev_id, input_id=input_id, input_data=message_data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")

    def get_tapered_level(self, value):
        tapered = value / 100
        tapered = 1 / 1.27 * tapered
        return tapered

    def get_float_value(self, value):
        floaty = value / 100
        floaty = 2 / 1.27 * floaty
        floaty = floaty - 1
        return floaty

    def get_bool(self, value):
        return value > 0

    async def send_update_message(self, mapping, value):
        mix = mapping['mix']
        dev_id = mapping['deviceId']
        input_id = mapping['inputId']
        if mix == 'Inputs':
            await self.send_volume_message(dev_id, input_id, value)
        elif mix == 'Gain':
            await self.send_gain_preamp_message(dev_id, input_id, value)
        elif mix in ['Pad', 'Phase', 'LowCut', '48V']:
            await self.send_bool_preamp_message(dev_id, input_id, mix, value)
        elif mix in ['Solo', 'Mute']:
            await self.send_bool_message(dev_id, input_id, mix, value)
        elif mix.startswith('Send'):
            send_id = mix[-1]
            await self.send_gain_send_message(dev_id, input_id, send_id, value)
        elif mix == 'Pan':
            await self.send_float_message(dev_id, input_id, mix, value)

    async def send_bool_message(self, dev_id, input_id, property, value):
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/{property}/value {str(self.get_bool(value))}")

    async def send_bool_preamp_message(self, dev_id, input_id, property, value):
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/preamps/0/{property}/value {str(self.get_bool(value))}")

    async def send_gain_send_message(self, dev_id, input_id, send_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/sends/{send_id}/GainTapered/value {tapered_level:.6f}")

    async def send_gain_preamp_message(self, dev_id, input_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/preamps/0/GainTapered/value {tapered_level:.6f}")

    async def send_volume_message(self, dev_id, input_id, value):
        tapered_level = self.get_tapered_level(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/FaderLevelTapered/value {tapered_level:.6f}")

    async def send_float_message(self, dev_id, input_id, property, value):
        float_value = self.get_float_value(value)
        await self.send_message(f"set /devices/{dev_id}/inputs/{input_id}/{property}/value {float_value:.6f}")

    async def send_get_device(self, dev_id):
        await self.send_message(f"get /devices/{dev_id}")
        await self.send_message(f"subscribe /devices/{dev_id}/DeviceOnline")

    async def send_get_inputs(self, dev_id):
        await self.send_message(f"get /devices/{dev_id}/inputs")

    async def send_get_input(self, dev_id, input_id):
        await self.send_message(f"get /devices/{dev_id}/inputs/{input_id}")
        await self.send_message(f"get /devices/{dev_id}/inputs/{input_id}/sends")


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    client = TCPClient('localhost', 12345)
    asyncio.run(client.start())
