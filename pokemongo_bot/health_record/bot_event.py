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
        self.client_id = str(uuid.uuid4())
        self.enabled = self.config.get('health_record', False)
        if self.enabled:
            self.logger.info('Health check is enabled. For more information:')
            self.logger.info('https://github.com/PokemonGoF/PokemonGo-Bot/tree/dev#analytics')
        else:
            self.logger.info('Health check is disabled, skipping analytics requests.')
        self.heartbeat_wait = 15 * 60  # seconds
        self.last_heartbeat = time.time()

    def capture_error(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping capture_error")
            return
        self.logger.error("Sentry error reporting is disabled")

    def login_success(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping login_success")
            return
        self.last_heartbeat = time.time()
        self.track_url('/loggedin')

    def login_failed(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping login_failed")
            return
        self.track_url('/login')

    def login_retry(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping login_retry")
            return
        self.track_url('/relogin')

    def logout(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping logout")
            return
        self.track_url('/logout')

    def heartbeat(self):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping heartbeat")
            return
        current_time = time.time()
        if current_time - self.last_heartbeat > self.heartbeat_wait:
            self.last_heartbeat = current_time
            self.track_url('/heartbeat')

    def track_url(self, path):
        if not self.enabled:
            self.logger.debug("Health check disabled, skipping track_url: %s", path)
            return
        data = {
            'v': '1',
            'tid': 'UA-81469507-1',
            'aip': '1',  # Anonymize IPs
            'cid': self.client_id,
            't': 'pageview',
            'dp': path
        }
        try:
            self.logger.debug("Sending POST to http://www.google-analytics.com/collect for %s", path)
            response = requests.post(
                'http://www.google-analytics.com/collect',
                data=data,
                timeout=5  # 5-second timeout
            )
            response.raise_for_status()
            self.logger.debug("track_url %s succeeded: %s", path, response.status_code)
        except requests.exceptions.Timeout:
            self.logger.warning("track_url %s timed out after 5 seconds", path)
        except requests.exceptions.RequestException as e:
            self.logger.warning("track_url %s failed: %s", path, e)