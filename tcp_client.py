import asyncio
import json
import logging
from blinker import signal

logger = logging.getLogger(__name__)

class TCPClient:
    RECONNECT_TIME = 3
    KEEP_ALIVE_TIME = 3
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
