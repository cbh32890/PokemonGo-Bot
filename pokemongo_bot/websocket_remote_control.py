# pokemongo_bot/websocket_remote_control.py
import threading
import logging
import socketio
from pokemongo_bot import inventory

class WebsocketNamespace(socketio.ClientNamespace):
    def __init__(self, bot, namespace):
        super().__init__(namespace)
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    def on_connect(self):
        self.logger.info(f"Connected to websocket server for {self.bot.config.username}")

    def on_disconnect(self):
        self.logger.info(f"Disconnected from websocket server for {self.bot.config.username}")

    def on_bot_process_request(self, command):
        name = command['name']
        command_handler = getattr(self, name, None)
        if not command_handler or not callable(command_handler):
            self.emit(
                'bot:send_reply',
                {
                    'response': '',
                    'command': 'command_not_found',
                    'account': self.bot.config.username
                }
            )
            return
        if 'args' in command:
            command_handler(*command['args'])
        else:
            command_handler()

    def get_player_info(self):
        try:
            self.emit(
                'bot:send_reply',
                {
                    'result': {'inventory': inventory.jsonify_inventory(), 'player': self.bot._player},
                    'command': 'get_player_info',
                    'account': self.bot.config.username
                }
            )
        except Exception as e:
            self.logger.error(f"Error in get_player_info: {e}")

class WebsocketRemoteControl(object):
    def __init__(self, bot):
        self.bot = bot
        self.host, port_str = self.bot.config.websocket_server_url.split(':')
        self.port = int(port_str)
        self.sio = socketio.Client()
        self.namespace = WebsocketNamespace(self.bot, f"/{self.bot.config.username}")
        self.sio.register_namespace(self.namespace)
        self.thread = threading.Thread(target=self.process_messages)
        self.logger = logging.getLogger(__name__)

    def start(self):
        self.sio.connect(f"ws://{self.host}:{self.port}")
        self.thread.start()
        return self

    def process_messages(self):
        self.sio.wait()

    def on_remote_command(self, command):
        # This method is no longer needed as it's handled by WebsocketNamespace
        pass