from bot_init import bot
from disnake import Embed
import disnake  
from dataConfig import CHANNEL_VALENTINE, VALENTINE_IMAGE_PATH

'''Команда для отправки валентинки'''
@bot.command(name="valentine")
async def valentine_command(ctx, user: disnake.Member, *, message: str = "Ты моя валентинка!"):

    # Сразу же удаляем сообщение пользователя с вызовом команды
    try:
        await ctx.message.delete()
    except:
        pass

    # Сообщение об успешном вызове в ЛС отправителю
    try:
        await ctx.author.send(f"💌 **Валентинка успешно отправлена для {user.mention}!**")
    except:
        pass

    # Получаем каналеее дадада
    channel = bot.get_channel(CHANNEL_VALENTINE)
    if not channel:
        try:
            await ctx.author.send("❌ Не удалось найти канал для валентинок. Обратитесь к автору бота")
        except:
            pass
        return
    
    # Отправляем валентинку в указанный канал
    embed = Embed(
        description=f"**Послание: {message}**",
        color=0xff69b4
    )
    embed.set_footer(text="От тайного поклонника ✨")

    await channel.send(
        content=f"Пользователь {user.mention} получил валентинку!\n\n**Послание:** {message}",
        file=disnake.File(VALENTINE_IMAGE_PATH)
    )