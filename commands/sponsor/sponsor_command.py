from bot_init import bot, ss14_db
import disnake
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_TOP_HEADS

@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="sponsor")
async def spons_command(ctx, username: str):
    guid = await ss14_db.get_player_guid(username)
    if not guid:
        await ctx.send(f"Пользователь {username} не найден в БД")
        return
    
    db_info_spons = await ss14_db.get_sponsor(guid)
    if db_info_spons:
        embed = disnake.Embed(title=f"Информация о {db_info_spons['player_name']}", color=0xFFD700)
        embed.add_field(name="UUID", value=db_info_spons['user_id'], inline=False)
        embed.add_field(name="Ник на сервере", value=db_info_spons['player_name'], inline=False)
        embed.add_field(name="Ник донатера", value=db_info_spons['donate_name'], inline=False)
        embed.add_field(name="Тир", value=db_info_spons['tier'], inline=False)
        # embed.add_field(name="Цвет в оос чате", value=db_info_spons['ooccolor'], inline=False)
        embed.add_field(name="Приоритет в очереди", value="Да" if db_info_spons['have_priority_join'] else "Нет", inline=False)
        embed.add_field(name="Дополнительные слоты", value=db_info_spons['extra_slots'], inline=False)
        embed.add_field(name="Дата окончания", value=db_info_spons['expire_date'].strftime("%Y-%m-%d") if db_info_spons['expire_date'] else "Нет данных", inline=False)
        embed.add_field(name="Разрешенные профессии", value=db_info_spons['allow_job'] if db_info_spons['allow_job'] else "Нет данных", inline=False)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"Пользователь {username} не является спонсором")