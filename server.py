import os
import time
import dotenv
import logging

import discord
import requests
from aiohttp import web

import data
import bot

dotenv.load_dotenv(override=True)

VERIFY_COOLDOWN = 30

logger = logging.getLogger(__name__)

def verify_user(guild_id, rblx_id):
    rblx_id = str(rblx_id)

    user_entry = data.client.read("user", rblx_id)
    guild_data = data.client.read("guild", guild_id) or {}
    bloxlink_token = guild_data.get("BLOXLINK")

    if bloxlink_token is None:
        return web.json_response({"error":"Bloxlink token not set"}, status=500)

    now = int(time.time())

    if user_entry:
        last_update = user_entry.get("TIME_UPDATED", 0)
        if now - last_update < VERIFY_COOLDOWN:
            remaining = VERIFY_COOLDOWN - (now - last_update)
            return web.json_response({"error": f"Cooldown active. Try again in {remaining} seconds."}, status=425)
        
    url = f"https://api.blox.link/v4/public/guilds/{guild_id}/roblox-to-discord/{rblx_id}"

    response = requests.get(url,headers={"Authorization": bloxlink_token},timeout=10)

    if response.status_code != 200:
        return web.json_response({"error":"Failed to fetch Discord ID"}, status=500)

    json_data = response.json()
    disc_id = json_data["discordIDs"][0]

    if disc_id is None:
        return web.json_response({"error":"User is not linked on Bloxlink"}, status=500)
    
    data.client.write("user", rblx_id, value={
        "DISC_ID": int(disc_id),
        "TIME_UPDATED": now
    })

    return int(disc_id)

async def handle(request):
    try:
        guild_id = request.headers.get("guild-id")
        password = request.headers.get("password")

        if guild_id is None:
            return web.json_response({"error":"Improper guild id"}, status=400)

        guild = bot.client.get_guild(int(guild_id))
        guild_data = data.client.read("guild", guild_id) or {}

        if guild is None:
            return web.json_response({"error":"Bot is not in specified guild"}, status=400)

        if guild_data.get("PASSWORD") is None:
            return web.json_response({"error":"Password is not set in the requested guild"}, status=400)

        if password != guild_data["PASSWORD"]:
            return web.json_response({"error":"Password is incorrect"}, status=400)

        if guild_data.get("IDLE_VC") is None or guild_data.get("MAIN_VC") is None:
            return web.json_response({"error":"VC Channels are not set in the requested guild"}, status=400)

        idle = guild.get_channel(guild_data["IDLE_VC"])
        main = guild.get_channel(guild_data["MAIN_VC"])

        action = request.headers.get("action")
        mode = request.headers.get("mode")

        if action is None or mode is None:
            return web.json_response({"error":"Action/Mode not specified"}, status=400)

        rblx_id = request.headers.get("rblx-id")
        user_data = data.client.read("user", rblx_id)
        disc_id = 0

        if user_data is not None:
            disc_id = user_data["DISC_ID"]
        else:
            respone = verify_user(guild_id, rblx_id)

            if isinstance(respone, int):
                disc_id = respone
            else:
                return respone

        member = guild.get_member(disc_id)

        if member is None:
            try:
                member = await guild.fetch_member(disc_id)
            except discord.NotFound:
                return web.json_response({"status": "inactive"})

        def get_status():
            if member.voice is None or member.voice.channel is None:
                    return "inactive"
            
            if mode == "channel":
                if member.voice.channel.id == main.id:
                    return "active"
                else: #elif member.voice.channel.id == idle.id
                    return "idle"
            elif mode == "voice":
                if member.voice.channel.id == idle.id:
                    if idle.permissions_for(member).speak:
                        return "active"
                    else:
                        return "idle"
                else:
                    return "inactive"
            
            return "inactive"

        if request.method == "GET":
            return web.json_response({"status": get_status()})

        if request.method == "POST":
            if member.voice is None or member.voice.channel is None:
                return web.json_response({"error":"Member not in voice channel"}, status=400)
            
            if action == "connect":
                await member.move_to(main)
            elif action == "disconnect":
                await member.move_to(idle)
            elif action == "unmute":
                await idle.set_permissions(member, speak=True)
                await member.move_to(idle)
                #await idle.set_permissions(member, overwrite=None)
                #await member.edit(mute=False)
            elif action == "mute":
                await idle.set_permissions(member, overwrite=None)
                await member.move_to(idle)
                #await idle.set_permissions(member, speak=False)
                #await member.edit(mute=True)

            return web.json_response({"status": get_status()})

        return web.json_response({"error":"Idk what happened"}, status=418)
    
    except Exception as e:
        logger.error("Exception in /api handler:", e, flush=True)
        return web.json_response({"error": "Internal server error", "details": str(e)}, status=500)
    
async def start():
    app = web.Application()
    app.router.add_route("*", "/api", handle)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(f"Web server running on port {port}")