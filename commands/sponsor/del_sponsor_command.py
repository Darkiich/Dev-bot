from bot_init import bot, ss14_db
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_TOP_HEADS

@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="del_sponsor")
async def del_sponsor_command(ctx, username: str):
    guid = await ss14_db.get_player_guid(username)
    if not guid:
        await ctx.send(f"Пользователь {username} не найден в БД")
        return
    
    ok, info = await ss14_db.delete_sponsor(guid)
    if ok:
        await ctx.send(f"Пользователь {username} удален из спонсоров")
    elif info == "not_found":
        await ctx.send(f"Пользователь {username} не найден в списке спонсоров")
    else:
        await ctx.send(f"Не удалось удалить {username} из спонсоров:\n```{info}```")