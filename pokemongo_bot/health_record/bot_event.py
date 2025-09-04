# -*- coding: utf-8 -*-

import logging
import uuid
import requests
import time
from pokemongo_bot.base_dir import _base_dir

class BotEvent(object):
    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger(__name__)
        client_uuid = uuid.uuid4()
        self.client_id = str(client_uuid)
        # UniversalAnalytics can be reviewed here:
        # https://github.com/analytics-pros/universal-analytics-python
        if self.config.get('health_record'):
            self.logger.info('Health check is enabled. For more information:')
            self.logger.info('https://github.com/PokemonGoF/PokemonGo-Bot/tree/dev#analytics')

        #self.heartbeat_wait = 15 * 60  # seconds
        self.last_heartbeat = time.time()

    def capture_error(self):
        if self.config.get('health_record'):
            self.logger.error("Sentry error reporting is disabled")

    def login_success(self):
        if self.config.get('health_record'):
            self.last_heartbeat = time.time()
            self.track_url('/loggedin')

    def login_failed(self):
        if self.config.get('health_record'):
            self.track_url('/login')

    def login_retry(self):
        if self.config.get('health_record'):
            self.track_url('/relogin')

    def logout(self):
        if self.config.get('health_record'):
            self.track_url('/logout')

    def heartbeat(self):
        if self.config.get('health_record'):
            current_time = time.time()
            if current_time - self.heartbeat_wait > self.last_heartbeat:
                self.last_heartbeat = current_time
                self.track_url('/heartbeat')

    def track_url(self, path):
        data = {
            'v': '1',
            'tid': 'UA-81469507-1',
            'aip': '1',  # Anonymize IPs
            'cid': self.client_id,
            't': 'pageview',
            'dp': path
        }
        try:
            response = requests.post(
                'http://www.google-analytics.com/collect', data=data)
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            pass