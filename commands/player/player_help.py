"""
&about_help - справка по командам для игроков
"""

import disnake

from bot_init import bot
from player_service import COLOR_MAIN, MENTIONS

ABOUT_ME = (
    "`&me` - часы, любимые роли, раунды и дата первого захода\n"
    "`&roles` - все роли с наигранными часами\n"
    "`&hours` - часы за 7 и 30 дней, динамика по дням\n"
    "`&streak` - сколько дней подряд заходишь, лучшая серия\n"
    "`&myban` - свои баны и джоббаны, активные и прошлые\n"
    "`&linked` - к какому аккаунту привязан Discord, придёт в личку"
)

RATINGS = (
    "`&top` - топ по времени в игре\n"
    "`&top раунды` - топ по числу раундов\n"
    "`&top месяц` - топ по раундам за 30 дней\n"
    "`&top капитан` - топ по конкретной роли\n"
    "`&rank` - твои места во всех рейтингах сразу\n"
    "`&vs <@участник или ник>` - сравнение с другим игроком"
)

CHARACTERS = (
    "`&character` - твои персонажи\n"
    "`&character Джон Смит` - поиск персонажа по имени\n"
    "`&character @участник` - персонажи этого человека"
)


@bot.command(name="about_help", aliases=["about", "игроки", "player_help"])
async def about_help_command(ctx):
    """Справка по игроцким командам."""
    embed = disnake.Embed(
        title="🎮 Команды для игроков",
        description="Префикс `&`. Русские названия тоже работают: `&я`, `&роли`, `&часы`, `&топ`, `&перс`.",
        color=COLOR_MAIN,
    )
    embed.add_field(name="Про себя", value=ABOUT_ME, inline=False)
    embed.add_field(name="Рейтинги", value=RATINGS, inline=False)
    embed.add_field(name="Персонажи", value=CHARACTERS, inline=False)

    await ctx.send(embed=embed, allowed_mentions=MENTIONS)
