import asyncio
import attr
import json
import logging
from blinker import signal

logger = logging.getLogger(__name__)

@attr.s(auto_attribs=True)
class Input:
    input_id: str = attr.ib()
    device: 'Device' = attr.ib()
    properties: dict = attr.Factory(dict)
    gain: float = 0.0
    phantom_power: bool = False
    pad: bool = False
    phase: bool = False
    low_cut: bool = False

    def update_properties(self, properties):
        self.properties.update(properties)

    def set_gain(self, gain):
        self.device.client.start_task(
            self.device.client.send_gain_preamp_message(self.device.device_id, self.input_id, gain))
        self.gain = gain

    def set_phantom_power(self, phantom_power):
        self.device.client.start_task(self.device.client.send_bool_preamp_message(
            self.device.device_id, self.input_id, "48V", phantom_power))
        self.phantom_power = phantom_power

    def set_pad(self, pad):
        self.device.client.start_task(
            self.device.client.send_bool_preamp_message(self.device.device_id, self.input_id, "Pad", pad))
        self.pad = pad

    def set_phase(self, phase):
        self.device.client.start_task(self.device.client.send_bool_preamp_message(
            self.device.device_id, self.input_id, "Phase", phase))
        self.phase = phase

    def set_low_cut(self, low_cut):
        self.device.client.start_task(self.device.client.send_bool_preamp_message(
            self.device.device_id, self.input_id, "LowCut", low_cut))
        self.low_cut = low_cut



@attr.s(auto_attribs=True)
class Device:
    device_id: str = attr.ib()
    client: 'TCPClient' = attr.ib()
    online: bool = False
    properties: dict = attr.Factory(dict)
    inputs: dict = attr.Factory(dict)
    volume: float = None
    mute: bool = False
    solo: bool = False
    pan: float = 0.0
    gain: float = 0.0
    phantom_power: bool = False
    pad: bool = False
    phase: bool = False
    low_cut: bool = False

    def set_online(self, online):
        self.online = online

    def update_properties(self, properties):
        self.properties.update(properties)

    def update_input(self, input_id, input_properties):
        self.inputs[input_id] = input_properties

    def get_input(self, input_id):
        return self.inputs.get(input_id, None)

    def set_volume(self, volume):
        self.client.start_task(
            self.client.send_volume_message(self.device_id, volume))
        self.volume = volume

    def set_mute(self, mute):
        self.client.start_task(self.client.send_bool_message(
            self.device_id, "Mute", mute))
        self.mute = mute

    def set_solo(self, solo):
        self.client.start_task(self.client.send_bool_message(
            self.device_id, "Solo", solo))
        self.solo = solo

    def set_pan(self, pan):
        self.client.start_task(
            self.client.send_float_message(self.device_id, "Pan", pan))
        self.pan = pan

    def set_gain(self, gain):
        self.client.start_task(
            self.client.send_gain_preamp_message(self.device_id, gain))
        self.gain = gain

    def set_phantom_power(self, phantom_power):
        self.client.start_task(self.client.send_bool_preamp_message(
            self.device_id, "48V", phantom_power))
        self.phantom_power = phantom_power

    def set_pad(self, pad):
        self.client.start_task(
            self.client.send_bool_preamp_message(self.device_id, "Pad", pad))
        self.pad = pad

    def set_phase(self, phase):
        self.client.start_task(self.client.send_bool_preamp_message(
            self.device_id, "Phase", phase))
        self.phase = phase

    def set_low_cut(self, low_cut):
        self.client.start_task(self.client.send_bool_preamp_message(
            self.device_id, "LowCut", low_cut))
        self.low_cut = low_cut


@attr.s(auto_attribs=True)
class TCPClient:
    RECONNECT_TIME: int = 3
    KEEP_ALIVE_TIME: int = 3
    SLEEP_TIME: int = 3
    USLEEP_TIME: float = 0.01
    MSG_SEPARATOR: str = '\x00'
    host: str = attr.ib()
    port: int = attr.ib()
    connected: bool = False
    approved: bool = None
    reader: asyncio.StreamReader = None
    writer: asyncio.StreamWriter = None
    devices: dict = attr.Factory(dict)
    connection_signal: signal = attr.Factory(lambda: signal('connection_change'))
    connection_lock: asyncio.Lock = attr.Factory(asyncio.Lock)
    tasks: list = attr.Factory(list)

    def _task_done_callback(self, task):
        """
        Callback for when a task is done, to remove it from the tasks list.
        """
        self.tasks.remove(task)

    def start_task(self, coro):
        """
        Start an asyncio task, add a done callback, and track it in self.tasks.
        """
        task = asyncio.create_task(coro)
        task.add_done_callback(self._task_done_callback)
        self.tasks.append(task)

    async def start(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            async with self.connection_lock:
                self.connected = True
            self.connection_signal.send(connected=True)
            logger.info("Connected to TCP")
            await self.send_get_devices()
            self.start_task(self.poll_for_response())
            self.start_task(self.start_keep_alive())
        except Exception as e:
            logger.error(f"Connection error: {e}")
            async with self.connection_lock:
                self.connected = False
            self.connection_signal.send(connected=False)
            await asyncio.sleep(self.RECONNECT_TIME)
            self.start_task(self.start())

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
            self.start_task(self.start())

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
            self.start_task(self.writer.wait_closed())
        async with self.connection_lock:
            self.connected = False
        self.connection_signal.send(connected=False)
        async for task in self.tasks:
            try:
                task.cancel()
                await task
            except Exception as e:
                logger.error(f"Error while cancelling task: {e}")
        self.tasks.clear()

    async def handle_message(self, msg):
        message_data = json.loads(msg)
        json_path = message_data['path'].split('/')
        if json_path[0] == 'devices':
            if len(json_path) == 1:
                await self.handle_devices_list(message_data)
            elif len(json_path) == 2:
                await self.handle_device(message_data, json_path[1])
            elif len(json_path) > 2 and json_path[2] == 'DeviceOnline':
                await self.handle_device_online(message_data, json_path[1])
            elif len(json_path) > 3 and json_path[2] == 'inputs':
                await self.handle_device_input(message_data, json_path[1], json_path[3])

    async def handle_devices_list(self, message_data):
        # Handle the list of devices
        children_keys = message_data['data']['children'].keys()
        for dev_id in children_keys:
            await self.send_get_device(dev_id)

    async def handle_device(self, message_data, dev_id):
        # Handle device properties
        if dev_id not in self.devices:  # Create a new Device instance
            self.devices[dev_id] = Device(dev_id, self)
        self.devices[dev_id].update_properties(message_data['data'])
        await self.send_get_inputs(dev_id)

    async def handle_device_online(self, message_data, dev_id):
        # Handle device online status
        online = message_data['data']
        if dev_id in self.devices:
            self.devices[dev_id].set_online(online)

    async def handle_device_input(self, message_data, dev_id, input_id):
        # Handle input properties
        if dev_id in self.devices:
            self.devices[dev_id].update_input(input_id, message_data['data'])
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
