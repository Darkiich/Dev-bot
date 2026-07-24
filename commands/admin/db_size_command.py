from bot_init import bot, ss14_db
from dataConfig import ROLE_ACCESS_TOP_HEADS, DB_SIZE_LIMIT_GB
from disnake.ext.commands import has_any_role
from disnake import Embed

GB = 1024 ** 3


def fmt_size(num_bytes: float) -> str:
    value = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if abs(value) < 1024.0:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{value:.2f} ПБ"


def make_bar(ratio: float, length: int = 20) -> str:
    ratio = max(0.0, min(ratio, 1.0))
    filled = int(round(ratio * length))
    return "█" * filled + "░" * (length - filled)


@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="db_size")
async def db_size_command(ctx):
    databases = await ss14_db.get_databases_size()
    if databases is None:
        await ctx.send("❌ Не удалось получить размер БД. Проверь подключение.")
        return

    total = sum(d['size'] for d in databases)
    limit_bytes = DB_SIZE_LIMIT_GB * GB
    ratio = total / limit_bytes if limit_bytes else 0.0

    if ratio >= 1.0:
        color = 0xFF0000
        state = "🔴 Порог превышен"
    elif ratio >= 0.9:
        color = 0xFFA500
        state = "🟠 Близко к порогу"
    else:
        color = 0x2ECC71
        state = "🟢 В норме"

    embed = Embed(title="Занято места в БД", color=color)
    embed.add_field(
        name="Суммарный размер",
        value=(
            f"**{fmt_size(total)}** / {DB_SIZE_LIMIT_GB} ГБ  ({ratio * 100:.1f}%)\n"
            f"`{make_bar(ratio)}`\n{state}"
        ),
        inline=False,
    )

    lines = []
    for d in databases:
        lines.append(f"• `{d['datname']}` — {fmt_size(d['size'])}")
        for t in (d.get('tables') or []):
            tsize = fmt_size(t['size']) if t['size'] is not None else "—"
            lines.append(f"　└ {t['name']}: {tsize}")
    embed.add_field(name="По базам", value="\n".join(lines) or "нет данных", inline=False)

    await ctx.send(embed=embed)
