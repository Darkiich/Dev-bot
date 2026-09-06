"""Справка по гост-отчётам."""

import disnake

from bot_init import bot
from commands.moderation.mod_common import reply
from dataConfig import GHOST_MAX_SHIFT_HOURS
from ghost_rules import COLOR_INFO

SHIFTS = (
    "`&aghost` - открыть агост\n"
    "`&eghost` - открыть игост\n"
    "Раунд, онлайн и режим бот берёт с сервера. Спрашивает время начала, "
    "у игоста ещё ивент: ссылка или описание, пусто - ивента нет."
)

BUTTONS = (
    "⏹️ **Завершить** - спросит время окончания\n"
    "📢 **Оповестить о действии** - у игоста, пишет в ветку и в базу\n"
    "🗒️ **Хронология** - действия смены списком\n"
    "✅ / ❌ - проверка отчёта наблюдателем, при отказе нужна причина"
)

STATS = (
    "`&ghost [@участник] [дней]` - сводка по человеку\n"
    "`&ghost_stats [агост/игост]` - метрики отдела\n"
    "`&ghost_report` - перерисовать закреплённый отчёт"
)

RULES = (
    "Вторую смену, не закрыв первую, открыть нельзя.\n"
    f"Смена длиннее {GHOST_MAX_SHIFT_HOURS} ч в часы и среднюю длительность не идёт."
)


@bot.command(name="ghost_help", aliases=["гост_помощь", "ghosthelp"])
async def ghost_help_command(ctx):
    """Справка по агосту и игосту."""
    embed = disnake.Embed(
        title="👻 Гост-отчёты",
        description="Префикс: `&`. Время по Москве.",
        color=COLOR_INFO,
    )

    embed.add_field(name="Смены", value=SHIFTS, inline=False)
    embed.add_field(name="Кнопки", value=BUTTONS, inline=False)
    embed.add_field(name="Аналитика", value=STATS, inline=False)
    embed.add_field(name="Учёт", value=RULES, inline=False)

    await reply(ctx, "", embed)
