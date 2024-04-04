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

    async def poll_for_response(self):
        while self.connected:
            try:
                response = await self.reader.readuntil(separator=self.MSG_SEPARATOR.encode('utf-8'))
                message = response.decode('utf-8').rstrip(self.MSG_SEPARATOR)
                asyncio.create_task(self.handle_message(message))
            except asyncio.IncompleteReadError:
                logger.error("Incomplete read from server.")
                self.connected = False
                self.connection_signal.send(connected=False)
                asyncio.create_task(self.start())

    async def handle_message(self, msg):
        try:
            message_data = json.loads(msg)
            # Handle the message data as needed
            logger.info(f"Received message: {message_data}")
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")

    async def start_keep_alive(self):
        while self.connected:
            await self.send_message("set /Sleep false")
            await asyncio.sleep(self.KEEP_ALIVE_TIME)

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
        # This method will be implemented based on the Swift code's sendUpdateMessage
        # It will use the mapping and value to construct and send the appropriate message
        pass

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

    def convert_to_dictionary(self, text):
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return None

    def get_json_children(self, json_data):
        try:
            json_dict = json.loads(json_data)
            data = json_dict.get("data", {})
            children = data.get("children", {})
            return list(children.keys())
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return []

    def get_data_as_bool(self, json_data):
        try:
            json_dict = json.loads(json_data)
            bool_data = json_dict.get("data", False)
            return bool_data
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse error: {e}")
            return False

    async def handle_message(self, msg):
        # This method will be implemented based on the Swift code's handleMessage
        # It will parse the message and handle it accordingly
        pass

    # The rest of the methods from the Swift code will be implemented here

