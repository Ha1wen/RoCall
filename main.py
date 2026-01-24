import os
import dotenv
import logging

import bot

dotenv.load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)

# @bot.client.event
# async def on_ready(self):
#     self.loop.create_task(server.start())

bot.client.run(os.environ.get("BOT_TOKEN"), log_handler=None)