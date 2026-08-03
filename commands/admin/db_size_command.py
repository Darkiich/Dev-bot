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


def get_state(ratio: float) -> tuple[int, str]:
    """Цвет и текстовый статус по заполненности конкретной БД."""
    if ratio >= 1.0:
        return 0xFF0000, "🔴 Порог превышен"
    if ratio >= 0.9:
        return 0xFFA500, "🟠 Близко к порогу"
    return 0x2ECC71, "🟢 В норме"


@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="db_size")
async def db_size_command(ctx):
    databases = await ss14_db.get_databases_size()
    if databases is None:
        await ctx.send("❌ Не удалось получить размер БД. Проверь подключение.")
        return

    limit_bytes = DB_SIZE_LIMIT_GB * GB
    embed = Embed(title="Занято места в БД", color=0x2ECC71)

    if not databases:
        embed.add_field(name="По базам", value="нет данных", inline=False)
        await ctx.send(embed=embed)
        return

    worst_ratio = 0.0
    for d in databases:
        ratio = d['size'] / limit_bytes if limit_bytes else 0.0
        worst_ratio = max(worst_ratio, ratio)
        _, state = get_state(ratio)

        lines = [
            f"**{fmt_size(d['size'])}** / {DB_SIZE_LIMIT_GB} ГБ  ({ratio * 100:.1f}%)",
            f"`{make_bar(ratio)}`",
            state,
        ]
        for t in (d.get('tables') or []):
            tsize = fmt_size(t['size']) if t['size'] is not None else "—"
            lines.append(f"　└ {t['name']}: {tsize}")

        embed.add_field(name=f"`{d['datname']}`", value="\n".join(lines), inline=False)

    embed.color = get_state(worst_ratio)[0]

    await ctx.send(embed=embed)
