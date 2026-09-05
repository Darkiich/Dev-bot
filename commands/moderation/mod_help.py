"""Справка по модерации Discord: команды, правила и подсказки."""

import disnake

from bot_init import bot
from commands.moderation.mod_common import reply
from dataConfig import MOD_DEFAULT_MUTE, MOD_WARN_EXPIRE_DAYS
from mod_rules import COLOR_INFO, measures_text

PUNISH = (
    "`&warn <@участник> <причина>` - предупреждение\n"
    "`&mute <@участник> [срок] [причина]` - мут ролью\n"
    "`&unmute <@участник> [комментарий]`\n"
    "`&dkick <@участник> [причина]` - выгнать с сервера\n"
    "`&dban <@участник или ID> [срок] [причина]`\n"
    "`&dunban <ID> [комментарий]`\n"
    "`&softban <@участник> [причина]` - кик с чисткой сообщений за сутки"
)

HISTORY = (
    "`&mod <@участник>` - досье с кнопками действий\n"
    "`&history <@участник> [страница]` - вся история\n"
    "`&warns [@участник]` - активные варны\n"
    "`&case <номер>` - карточка кейса\n"
    "`&case <номер> причина <текст>` - поправить формулировку\n"
    "`&revoke <номер> [комментарий]` - снять наказание\n"
    "`&unwarn <номер>` - снять варн\n"
    "`&note <@участник> <текст>` - скрытая заметка\n"
    "`&muted` - кто сейчас в муте\n"
    "`&modstats [дней]` - кто сколько намодерировал"
)

CHANNELS = (
    "`&purge <сколько> [фильтр]` - чистка канала\n"
    "`&lock [#канал] [срок] [причина]` - закрыть канал\n"
    "`&unlock [#канал]`\n"
    "`&slowmode <срок или off> [#канал]`\n"
    "`&lockdown on/off [причина]` - закрыть весь сервер на время рейда\n"
    "`&modpanel` - выложить панель с кнопками\n"
    "`&mute_setup` - расставить права роли мута по каналам"
)


def _rules_text() -> str:
    expire = (
        f"Варн сгорает через {MOD_WARN_EXPIRE_DAYS} дней, из истории не исчезает"
        if MOD_WARN_EXPIRE_DAYS else
        "Варны бессрочные"
    )

    return (
        "Каждое действие получает номер кейса, по нему же и снимается.\n"
        "Если написать `&warn` ответом на сообщение, то приложит ссылку на него к кейсу\n"
        f"Сроки: `30` без метки времени воспринимается как в минутах, `10m`, `2h`, `3d`, `1w`, `перм`. Мут без срока - `{MOD_DEFAULT_MUTE}`\n"
        f"{expire}\n"
        "Нарушителю уходит личка с причиной, сроком и номером кейса\n"
        "Все эти команды можно использовать как `/mod ...`"
    )


@bot.command(name="mod_help", aliases=["modhelp", "модерация"])
async def mod_help_command(ctx):
    """Справка по модерации Discord."""
    main = disnake.Embed(
        title="🛡️ Модерация Discord",
        description="Префикс `&`.",
        color=COLOR_INFO,
    )
    main.add_field(name="Наказания", value=PUNISH, inline=False)
    main.add_field(name="История и кейсы", value=HISTORY, inline=False)
    main.add_field(name="Каналы и порядок", value=CHANNELS, inline=False)

    extra = disnake.Embed(title="Что нужно знать", description=_rules_text(), color=COLOR_INFO)
    extra.add_field(name="Мера наказаний для варнов", value=measures_text(), inline=False)

    await ctx.send(embeds=[main, extra])
