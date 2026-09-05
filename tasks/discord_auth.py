import logging
import disnake
import uuid

from bot_init import ss14_db, bot
from disnake.ext import tasks

from dataConfig import CHANNEL_AUTH_DISCORD, CHANNEL_LOG_AUTH_DISCORD

logger = logging.getLogger(__name__)


class NicknameModal(disnake.ui.Modal):
    def __init__(self):
        components = [
            disnake.ui.TextInput(
                label="Введите UID SS14",
                placeholder="UID из лобби SS14",
                custom_id="guid",
                style=disnake.TextInputStyle.short,
                required=True
            )
        ]
        super().__init__(title="Привязка аккаунта", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        await inter.response.defer(ephemeral=True)
        guid = inter.text_values["guid"].strip()
        discord_id = str(inter.author.id)
        tech_channel = bot.get_channel(CHANNEL_LOG_AUTH_DISCORD)

        if not guid:
            await inter.send("❌ UID не может быть пустым.", ephemeral=True)
            await tech_channel.send(f"⚠️ Пользователь {inter.author.name} ({discord_id}) ввел пустой UID.")
            return

        if await ss14_db.is_linked(discord_id):
            await inter.send("❌ Аккаунт уже привязан.", ephemeral=True)
            await tech_channel.send(f"⚠️ Пользователь {inter.author.name} ({discord_id}) пытался повторно привязать аккаунт.")
            return

        try:
            uuid.UUID(guid)
        except ValueError as e:
            logger.info("Невалидный UID при привязке: %s (%s) ввёл %r", inter.author, discord_id, guid)
            await inter.send(f"⚠️ Вы ввели невалидный UID", ephemeral=True)
            await tech_channel.send(f"⚠️ Ошибка: Пользователь {inter.author.name} пытался привязать аккаунт вводя невалидный {inter.text_values["guid"].strip()}")
            return

        success, message = await ss14_db.link_user(guid, discord_id)
        await inter.send(message, ephemeral=True)
        if success:
            logger.info("Привязка аккаунта: %s (%s) к UID %s", inter.author, discord_id, guid)
            await tech_channel.send(f"✅ Привязка: {inter.author.name} ({discord_id}) к UID {guid}.")
        else:
            logger.warning("Ошибка привязки аккаунта %s (%s) к UID %s: %s", inter.author, discord_id, guid, message)
            await tech_channel.send(f"⚠️ Ошибка привязки для {inter.author.name} ({discord_id}) к UID {guid}: {message}.")

class RegisterButton(disnake.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @disnake.ui.button(label="Привязать аккаунт", style=disnake.ButtonStyle.primary, custom_id="link_button")
    async def register(self, button, inter):
        await inter.response.send_modal(NicknameModal())

@tasks.loop(hours=12)
async def discord_auth_update():
    channel = bot.get_channel(CHANNEL_AUTH_DISCORD)
    if not channel:
        return

    embed = disnake.Embed(
        title="Привязка аккаунта SS14",
        description="Нажмите кнопку и введите UID.",
        color=0x3498db
    )

    pinned = []
    async for msg in channel.pins():
        pinned.append(msg)

    old_message = next((m for m in pinned if m.author == channel.guild.me), None)

    if old_message:
        await old_message.edit(embed=embed, view=RegisterButton())
    else:
        new_message = await channel.send(embed=embed, view=RegisterButton())
        await new_message.pin()