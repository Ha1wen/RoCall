import asyncio
import discord
from discord.ext import commands
from discord import app_commands
from aiohttp import web
import os
import json
import requests
import time
from dotenv import load_dotenv

load_dotenv(override=True)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

print(f"Bot token: {BOT_TOKEN}")

COOLDOWN_SECONDS = 30

class Client(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        super().__init__(intents=intents)

        self.tree = discord.app_commands.CommandTree(self)
        self.synced = False

    async def on_ready(self):
        print("Setting up bot")

        if self.synced:
            return

        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Synced commands to: {guild.name} ({guild.id})")

        self.synced = True
        print("All guilds synced")

        print(f"Logged in as {self.user}")
        self.loop.create_task(start_webserver())

client = Client()

set_group = app_commands.Group(
    name="set",
    description="Configure bot settings (admin only)"
)

if not os.path.exists("data.json"):
    with open("data.json", "w") as f:
        json.dump({"Guilds":{}, "Users":{}}, f)

with open("data.json", "r") as file:
    data = json.load(file)

def save_data():
    with open("data.json", "w") as file:
        json.dump(data, file, indent=4)

def save_setting(guildId, key, val):
    guildId = str(guildId)

    data["Guilds"].setdefault(guildId, {})

    data["Guilds"][guildId][key] = val
    save_data()

def verify_user(guild_id, rblx_id):
    rblx_id = str(rblx_id)

    user_entry = data["Users"].get(rblx_id)
    guildData = data["Guilds"].get(guild_id) or {}
    bloxlink_token = guildData.get("BLOXLINK")

    if bloxlink_token is None:
        return web.json_response(reason= "Bloxlink token not set", status=500)

    now = int(time.time())

    if user_entry:
        last_update = user_entry.get("TIME_UPDATED", 0)
        if now - last_update < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (now - last_update)
            return web.json_response(reason= f"Cooldown active. Try again in {remaining} seconds.", status=425)
        
    url = f"https://api.blox.link/v4/public/guilds/{guild_id}/roblox-to-discord/{rblx_id}"

    response = requests.get(url,headers={"Authorization": bloxlink_token},timeout=10)

    if response.status_code != 200:
        return web.json_response(reason= "Failed to fetch Discord ID", status=500)

    json_data = response.json()
    disc_id = json_data["discordIDs"][0]

    if disc_id is None:
        return web.json_response(reason="User is not linked on Bloxlink", status=500)
    
    data["Users"][rblx_id] = {
        "DISC_ID": int(disc_id),
        "TIME_UPDATED": now
    }

    save_data()

    return int(disc_id)

@client.event
async def on_voice_state_update(member, before, after):
    if before.channel is None:
        return
    
    guild = member.guild
    guild_id = str(guild.id)
    channel_id = before.channel.id

    guildData = data["Guilds"].get(guild_id) or {}
    idle_id = guildData.get("IDLE_VC")

    if idle_id is None:
        return

    if channel_id == idle_id:
        idle = guild.get_channel(idle_id)
        await idle.set_permissions(member, overwrite=None)

@set_group.command(name="main", description="Set main VC")
@app_commands.checks.has_permissions(administrator=True)
async def setMainVC(interaction: discord.Interaction, vc_id: str):
    save_setting(interaction.guild_id, "MAIN_VC", int(vc_id))
    await interaction.response.send_message("Main VC changed!", ephemeral=True)

@set_group.command(name="idle", description="Set idle VC")
@app_commands.checks.has_permissions(administrator=True)
async def setIdleVC(interaction: discord.Interaction, vc_id: str):
    save_setting(interaction.guild_id, "IDLE_VC", int(vc_id))
    await interaction.response.send_message("Idle VC changed!", ephemeral=True)

@set_group.command(name="bloxlink", description="Set bloxlink token for member authentication")
@app_commands.checks.has_permissions(administrator=True)
async def setBloxlink(interaction: discord.Interaction, token: str):
    save_setting(interaction.guild_id, "BLOXLINK", token)
    await interaction.response.send_message(f"Bloxlink token changed!", ephemeral=True)

@set_group.command(name="password", description="Set password for bot interactions")
@app_commands.checks.has_permissions(administrator=True)
async def setPassword(interaction: discord.Interaction, password: str):
    save_setting(interaction.guild_id, "PASSWORD", password)
    await interaction.response.send_message(f"Password changed! Make sure to update your code.", ephemeral=True)

@set_group.error
async def set_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await interaction.response.send_message("Administrator permission required.", ephemeral=True)

client.tree.add_command(set_group)

async def handle(request):
    guild_id = request.headers.get("guild-id")
    password = request.headers.get("password")

    if guild_id is None:
        return web.json_response(reason="Improper guild id", status=400)

    guild = client.get_guild(int(guild_id))
    guildData = data["Guilds"].get(guild_id) or {}

    if guild is None:
        return web.json_response(reason="Bot is not in specified guild", status=500)

    if guildData.get("PASSWORD") is None:
        return web.json_response(reason="Password is not set in the requested guild", status=500)

    if password != guildData["PASSWORD"]:
        return web.json_response(reason="Password is incorrect", status=401)

    if guildData.get("IDLE_VC") is None or guildData.get("MAIN_VC") is None:
        return web.json_response(reason="VC Channels are not set in the requested guild", status=500)

    idle = guild.get_channel(guildData["IDLE_VC"])
    main = guild.get_channel(guildData["MAIN_VC"])

    action = request.headers.get("action")
    mode = request.headers.get("mode")

    if action is None or mode is None:
        return web.json_response(reason="Action/Mode not specified", status=400)

    rblx_id = request.headers.get("rblx-id")
    userData = data["Users"].get(rblx_id)
    disc_id = 0

    if userData is not None:
        disc_id = userData["DISC_ID"]
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

    def getStatus():
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
        return web.json_response({"status": getStatus()})

    if request.method == "POST":
        if member.voice is None or member.voice.channel is None:
            return web.json_response(reason="Member not in voice channel", status=400)
        
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

        return web.json_response({"status": getStatus()})
    
    return web.json_response(reason="Idk what happened", status=418)
    
async def start_webserver():
    app = web.Application()
    app.router.add_route("*", "/api", handle)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    print(f"Web server running on port {port}")

client.run(BOT_TOKEN)