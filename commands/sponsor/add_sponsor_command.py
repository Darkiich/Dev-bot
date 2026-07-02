import disnake

from bot_init import bot, ss14_db
from datetime import datetime
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_TOP_HEADS, SPONSOR_ROLE_ID


async def grant_sponsor_role(ctx, guid: str) -> str:
    if not SPONSOR_ROLE_ID:
        return "⚠️ Роль не выдана: в конфиге не задан SPONSOR_ROLE_ID."

    role = ctx.guild.get_role(SPONSOR_ROLE_ID)
    if role is None:
        return f"⚠️ Роль не выдана: роль с ID {SPONSOR_ROLE_ID} не найдена на сервере."

    discord_id = await ss14_db.get_discord_info_by_guid(guid)
    if not discord_id:
        return "⚠️ Роль не выдана: у игрока не привязан дискорд."

    try:
        member = ctx.guild.get_member(int(discord_id)) or await ctx.guild.fetch_member(int(discord_id))
    except (ValueError, TypeError):
        return "⚠️ Роль не выдана: некорректный Discord ID в БД."
    except disnake.NotFound:
        return f"⚠️ Роль не выдана: пользователь <@{discord_id}> не найден на сервере."
    except disnake.HTTPException as e:
        return f"⚠️ Роль не выдана: ошибка Discord при поиске участника ({e})."

    try:
        await member.add_roles(role, reason="Выдача спонсорки через бота")
        return f"✅ Роль **{role.name}** выдана {member.mention}."
    except disnake.Forbidden:
        return "⚠️ Роль не выдана: у бота нет прав."
    except disnake.HTTPException as e:
        return f"⚠️ Роль не выдана: ошибка Discord ({e})."


@has_any_role(*ROLE_ACCESS_TOP_HEADS)
@bot.command(name="add_sponsor")
async def add_sponsor_command(ctx, username: str, tier: int, date: str, donate_name: str = "Спонсор. Выдано через ДС бота"):
    guid = await ss14_db.get_player_guid(username)
    if not guid:
        await ctx.send(f"Пользователь {username} не найден в БД")
        return

    markings50 = ['FoxEars','ASDVulpkaninskull_sponsor','ADTVulpkaninhair_sponsor','ADTVulpkaninjagged_sponsor_hair','ADTVulpkaninykiteru_sponsor_hair','MothWingsLook1','MothWingsLook2','MothWingsLook3','Head7','CatEarsStubby','CatEarsCurled','CatEarsTorn','CatTailStripes','HumanHairCotton','HumanHairFingerwave','HumanHairFortuneteller','HumanHairFortunetellerAlt','HumanHairLongdtails','HumanHairLooseSlicked','HumanHairQuadcurls','HumanHairShy','HumanHairSpicy','HumanHairWife','AugmentsRoboticRightArm','AugmentsRoboticRightHand','CatEars','CatTail','DTAllsuccubus','ADTAlldurak','ADTAllhorn1','ADTAllhorn2','ADTAllhorn3','ADTAllhorn4','ADTAllhorn5','ADTAllhorn6','ADTAlllord','ADTAlloldpain','ADTAlltavrhorn','ADTAlltelehorn','ADTAllvampirehorn','ADTAllsuccubus','SlimeFoxEars','SlimeCatEars','SlimeCatTail','SlimeCatTail-slime_tail_cat_wag','SlimeCatTailStripes','SlimeCatEarsStubby','SlimeCatEarsCurled','SlimeCatEarsTorn','ADTVulpkaninskull_sponsor','ADTFoxTail']
    markings75 = markings50 + ['AugmentsAugArmRight','AugmentsAugHandRigh','AugmentsAugArmLeft','AugmentsAugHandLeft','AugmentsAugTorso','AugmentsAugLegRight','AugmentsAugFootRight','AugmentsAugLegLeft','AugmentsAugFootLeft','Malstrem','Terminator','Head7','ADTVulpkaninskull_sponsor','ADTAlldurak','ADTAllhorn1','ADTAllhorn2','ADTAllhorn3','ADTAllhorn4','ADTAllhorn5','ADTAllhorn6','ADTAlllord','ADTAlloldpain','ADTAlltavrhorn','ADTAlltelehorn','ADTAllvampirehorn']

    try:
        expire_date = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        await ctx.send("Неверный формат даты: YYYY-MM-DD")
        return

    tier_params = {
        1: ('#00FF00', False, [],         0, False),
        2: ('#00FF00', True,  markings50, 0, False),
        3: ('#00FF00', True,  markings75, 5, False),
    }
    if tier not in tier_params:
        await ctx.send(f"Неверный тир {tier}. Допустимые значения: 1, 2, 3")
        return

    ooccolor, have_priority, markings, extra_slots, allow_job = tier_params[tier]

    ok, info = await ss14_db.add_sponsor(
        guid, username, donate_name, tier, ooccolor,
        have_priority, markings, extra_slots, expire_date, allow_job
    )

    if not ok:
        if info == "exists":
            await ctx.send("Удалите запись о спонсоре перед добавлением новой")
        else:
            await ctx.send(f"❌ Не удалось добавить {username} в спонсоры:\n```{info}```")
        return

    role_status = await grant_sponsor_role(ctx, guid)
    await ctx.send(f"Пользователь {username} добавлен в спонсоры с тиром {tier}.\n{role_status}")
