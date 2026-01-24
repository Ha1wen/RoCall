import os
import dotenv
import logging

import redis

dotenv.load_dotenv(override=True)

DATA_BANK = "rocall"
DATA_HOST = "redis-16247.c73.us-east-1-2.ec2.cloud.redislabs.com"
DATA_PASS = os.environ.get("DATA_PASS")
DATA_USER = "default"

logger = logging.getLogger(__name__)

class Client:
    def __init__(self):
        self.prefix = DATA_BANK
        self.cache = {}
        self.client = redis.Redis(
            host=DATA_HOST,
            port=16247,
            decode_responses=True,
            username=DATA_USER,
            password=DATA_PASS,
        )

        self.load_cache()

    def _key(self, namespace, key):
        return f"{self.prefix}:{namespace}:{key}"

    def write(self, namespace, key, obj_key=None, value=None):        
        full_key = self._key(namespace, key)

        if not self.client.exists(full_key):
            self.client.json().set(full_key, "$", {})

        path = "$"

        if obj_key is not None:
            path = f"$.{obj_key}"

        self.client.json().set(full_key, path, value)

        if path == "$":
            self.cache.setdefault(namespace, {})[key] = value
        else:
            self.cache.setdefault(namespace, {}).setdefault(key, {})[obj_key] = value

        return "OK"

    def read(self, namespace, key, force=False):
        if not force and key in self.cache.get(namespace, {}):
            return self.cache[namespace][key]
        
        full_key = self._key(namespace, key)
        value = self.client.json().get(full_key)

        self.cache.setdefault(namespace, {})[key] = value

        return value

    def load_cache(self):
        logger.info("Loading cache")

        pattern = f"{self.prefix}:*"

        for full_key in self.client.scan_iter(match=pattern):
            parts = full_key.split(":", 2)
            _, namespace, key = parts
            
            self.read(namespace, key, True)

        logger.info("Cache loaded")

    def close(self):
        self.client.close()

client = Client()