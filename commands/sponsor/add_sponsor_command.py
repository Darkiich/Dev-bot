from bot_init import bot, ss14_db
from datetime import datetime
from disnake.ext.commands import has_any_role
from dataConfig import ROLE_ACCESS_TOP_HEADS

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
    
    match tier:
        case 1:
            res_add = await ss14_db.add_sponsor(guid, username, donate_name, 1, '#00FF00', False, [], 0, expire_date, False)
            if not res_add:
                await ctx.send(f"Удалите запись о спонсоре перед добавлением новой")
            else:
                await ctx.send(f"Пользователь {username} добавлен в спонсоры с тиром 1")
        case 2:
            res_add = await ss14_db.add_sponsor(guid, username, donate_name, 2, '#00FF00', True, markings50, 0, expire_date, False)
            if not res_add:
                await ctx.send(f"Удалите запись о спонсоре перед добавлением новой")
            else:
                await ctx.send(f"Пользователь {username} добавлен в спонсоры с тиром 2")
        case 3:
            res_add = await ss14_db.add_sponsor(guid, username, donate_name, 3, '#00FF00', True, markings75, 5, expire_date, False)
            if not res_add:
                await ctx.send(f"Удалите запись о спонсоре перед добавлением новой")
            else:
                await ctx.send(f"Пользователь {username} добавлен в спонсоры с тиром 3")
        case _:
            await ctx.send(f"Неверный тир {tier}. Допустимые значения: 1, 2, 3")