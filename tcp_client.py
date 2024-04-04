import asyncio
import json
import logging
from blinker import signal

logger = logging.getLogger(__name__)

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
        self.connection_signal = signal('connection_change')

    async def start(self):
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            self.connected = True
            self.connection_signal.send(connected=True)
            logger.info("Connected to TCP")
            await self.send_get_devices()
            asyncio.create_task(self.poll_for_response())
            asyncio.create_task(self.start_keep_alive())
        except Exception as e:
            logger.error(f"Connection error: {e}")
            self.connected = False
            self.connection_signal.send(connected=False)
            await asyncio.sleep(self.RECONNECT_TIME)
            asyncio.create_task(self.start())

    async def send_message(self, msg):
        if not self.connected:
            logger.error("Not connected to server.")
            return
        tcp_message = f"{msg}{self.MSG_SEPARATOR}"
        self.writer.write(tcp_message.encode('utf-8'))
        await self.writer.drain()
        logger.debug(f"Sent: {tcp_message}")
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            self.connected = False
            self.connection_signal.send(connected=False)
            asyncio.create_task(self.start())

    async def poll_for_response(self):
        # Correct implementation of poll_for_response should be here, matching the Swift client's logic.
        self.connected = False
        self.connection_signal.send(connected=False)
        asyncio.create_task(self.start())

    # The handle_message method should be updated to match the Swift client's handleMessage method.
    # This includes parsing the message and handling different paths and data extraction.
    # Please refer to the Swift code for the exact implementation details.

    async def start_keep_alive(self):
        try:
            while self.connected:
                await self.send_message("set /Sleep false")
                await asyncio.sleep(self.KEEP_ALIVE_TIME)
        except asyncio.CancelledError:
            logger.info("Keep-alive cancelled.")
        except Exception as e:
            logger.error(f"Error in keep-alive: {e}")

    async def send_get_devices(self):
        await self.send_message("get /devices")

    def close(self):
        if self.writer:
            self.writer.close()
            asyncio.create_task(self.writer.wait_closed())
        self.connected = False
        self.connection_signal.send(connected=False)

    # Additional methods for sending specific messages will be added here

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    client = TCPClient('localhost', 12345)
    asyncio.run(client.start())
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

    # Removed unused convert_to_dictionary method.

    # Removed unused get_json_children method.

    def get_data_as_bool(self, json_data):
        try:
            json_dict = json.loads(json_data)
            data = json_dict.get("data", {})
            if isinstance(data, bool):
                return data
            elif isinstance(data, dict) and 'value' in data:
                return bool(data['value'])
            else:
                return False
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return False

    async def handle_message(self, msg):
        try:
            message_data = json.loads(msg)
            json_path = message_data['path'].split('/')

            if json_path[0] == 'devices':
                if len(json_path) == 1:
                    # -> /devices
                    pass
                elif len(json_path) == 2:
                    # -> /devices/id
                    children_keys = self.get_json_children(msg)
                    for dev_id in children_keys:
                        await self.send_get_device(dev_id)
                elif json_path[2] == 'DeviceOnline':
                    # -> /devices/id/DeviceOnline
                    dev_id = json_path[1]
                    online = self.get_data_as_bool(msg)
                    # Signal device online status change
                    self.connection_signal.send(device_id=dev_id, online=online)
                elif json_path[2] == 'inputs':
                    dev_id = json_path[1]
                    if len(json_path) == 3:
                        # -> /devices/id/inputs
                        children_keys = self.get_json_children(msg)
                        for input_id in children_keys:
                            await self.send_get_input(dev_id, input_id)
                    elif len(json_path) == 4:
                        # -> /devices/id/inputs/id
                        input_id = json_path[3]
                        # Signal input information received
                        self.connection_signal.send(device_id=dev_id, input_id=input_id, input_data=message_data)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")

    # The rest of the methods from the Swift code will be implemented here
