from bot_init import bot
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_TOP_HEADS

from .sponsor_api import SponsorApiError
from .sponsor_discord_roles import sync_sponsor_roles


@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="sync_sponsors", aliases=["sync_roles"])
async def sync_sponsors_command(ctx):
    """Сразу синхронизирует роли спонсоров (старая и новая спонсорка), не дожидаясь часового цикла."""
    async with ctx.typing():
        try:
            granted, revoked = await sync_sponsor_roles(f"Ручная синхронизация спонсорки ({ctx.author})")
        except SponsorApiError as error:
            await ctx.send(f"Не удалось синхронизировать: игровое API недоступно.\n```{error}```")
            return
        except Exception as error:
            await ctx.send(f"Сбой синхронизации ролей:\n```{error!r}```")
            return

    await ctx.send(f"Роли спонсоров синхронизированы: выдано {granted}, снято {revoked}.")
