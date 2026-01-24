import os
import logging
import discord
from discord import app_commands

import data
import server

logger = logging.getLogger(__name__)

def save_setting(guild_id, key, val):
    guild_id = str(guild_id)

    logger.debug("Saving guild id")

    data.client.write("guild", guild_id, key, val)

class Client(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.guilds = True
        intents.members = True
        intents.voice_states = True
        super().__init__(intents=intents)

        self.setup_commands()

    async def on_ready(self):
        await self.sync_commands()

        logger.info(f"Logged in as {self.user}")

        self.loop.create_task(server.start())

    async def on_voice_state_update(member, before, after):
        if before.channel is None:
            return
        
        guild = member.guild
        guild_id = str(guild.id)
        channel_id = before.channel.id

        guild_data = data.client.read("guild", guild_id) or {}
        idle_id = guild_data.get("IDLE_VC")

        if idle_id is None:
            return

        if channel_id == idle_id:
            idle = guild.get_channel(idle_id)
            await idle.set_permissions(member, overwrite=None)

    async def sync_commands(self):
        for guild in self.guilds:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)

        logger.info("All guilds synced")

    def setup_commands(self):
        set_group = app_commands.Group(
            name="set",
            description="Configure bot settings (admin only)"
        )

        refresh_group = app_commands.Group(
            name="refresh",
            description="Refresh bot data"
        )

        @refresh_group.command(name="cache", description="Refresh data cache (might take a minute)")
        @app_commands.checks.has_permissions(administrator=True)
        async def refresh_cache(interaction: discord.Interaction, data_pass: str):
            if data_pass == os.environ.get("DATA_PASS"):
                data.client.load_cache()
                await interaction.response.send_message("Cache refreshed!", ephemeral=True)
            else:
                await interaction.response.send_message("Database access password incorrect!", ephemeral=True)

        @set_group.command(name="main", description="Set main VC")
        @app_commands.checks.has_permissions(administrator=True)
        async def set_main_vc(interaction: discord.Interaction, vc_id: str):
            save_setting(interaction.guild_id, "MAIN_VC", int(vc_id))
            await interaction.response.send_message("Main VC changed!", ephemeral=True)

        @set_group.command(name="idle", description="Set idle VC")
        @app_commands.checks.has_permissions(administrator=True)
        async def set_idle_vc(interaction: discord.Interaction, vc_id: str):
            save_setting(interaction.guild_id, "IDLE_VC", int(vc_id))
            await interaction.response.send_message("Idle VC changed!", ephemeral=True)

        
        @set_group.command(name="bloxlink", description="Set Bloxlink token")
        @app_commands.checks.has_permissions(administrator=True)
        async def set_bloxlink(interaction: discord.Interaction, token: str):
            save_setting(interaction.guild_id, "BLOXLINK", token)
            await interaction.response.send_message("Bloxlink token changed!", ephemeral=True)

        
        @set_group.command(name="password", description="Set password")
        @app_commands.checks.has_permissions(administrator=True)
        async def set_password(interaction: discord.Interaction, password: str):
            save_setting(interaction.guild_id, "PASSWORD", password)
            await interaction.response.send_message("Password changed! Make sure to update your code.", ephemeral=True)

        @refresh_group.error
        @set_group.error
        async def set_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
            if isinstance(error, app_commands.errors.MissingPermissions):
                await interaction.response.send_message("Administrator permission required.", ephemeral=True)

        self.tree = app_commands.CommandTree(self)
        self.tree.add_command(set_group)
        self.tree.add_command(refresh_group)

client = Client()