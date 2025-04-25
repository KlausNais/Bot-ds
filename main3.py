import discord
from discord.ext import commands
import asyncio
import os
import datetime  # Для создания меток времени в транскрипте
import r
from dotenv import load_dotenv
load_dotenv()

def sanitize_filename(filename):
    """Удаляет или заменяет недопустимые символы в имени файла."""
    # Заменяем пробелы на подчеркивания
    filename = filename.replace(" ", "_")
    # Удаляем все символы, кроме букв, цифр, подчеркиваний и точек
    filename = re.sub(r"[^a-zA-Z0-9_.]", "", filename)
    return filename

# 1. Настройка

TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
if not TOKEN:
    print("Ошибка: Не найден токен бота в переменной окружения DISCORD_BOT_TOKEN.")
    exit()

PREFIX = "t."
bot = commands.Bot(command_prefix=PREFIX, intents=discord.Intents.all(), case_insensitive=True)

TICKET_CATEGORY_ID = 1350430931126587433  # Замените!
SUPPORT_ROLE_ID = 1358793114524844073  # Замените!
TICKET_MESSAGE = "Добро пожаловать! Опишите вашу проблему, и команда поддержки скоро вам поможет."
TRANSCRIPT_CHANNEL_ID = 1352689405395206245  # Замените! (Канал для транскриптов)

# 2. События

@bot.event
async def on_ready():
    print(f"Бот {bot.user.name} готов к работе!")
    await bot.change_presence(activity=discord.Game(name="Поддержка пользователей"))

# 3. Команды

@bot.command(name="new", help="Создает новый тикет.")
async def new_ticket(ctx):
    """Создает новый тикет."""

    existing_ticket = discord.utils.find(
        lambda c: c.name == f"ticket-{ctx.author.name.lower()}" and c.category_id == TICKET_CATEGORY_ID,
        ctx.guild.channels
    )
    if existing_ticket:
        await ctx.send(f"{ctx.author.mention}, у вас уже есть открытый тикет: {existing_ticket.mention}")
        return

    category = bot.get_channel(TICKET_CATEGORY_ID)
    if not category:
        await ctx.send(f"Ошибка: Не найдена категория с ID {TICKET_CATEGORY_ID}.")
        return

    overwrites = {
        ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        ctx.author: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True),
        ctx.guild.get_role(SUPPORT_ROLE_ID): discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, manage_channels=True),
        bot.user: discord.PermissionOverwrite(view_channel=True, send_messages=True)
    }

    try:
        channel = await category.create_text_channel(
            name=f"ticket-{ctx.author.name.lower()}",
            topic=f"Тикет создан пользователем {ctx.author.mention} ({ctx.author.id})",
            overwrites=overwrites,
            reason=f"Создание тикета пользователем {ctx.author.name}"
        )
    except discord.errors.Forbidden:
        await ctx.send("У бота недостаточно прав для создания канала в этой категории.  Необходимы права 'Manage Channels'.")
        return
    except Exception as e:
        await ctx.send(f"Произошла ошибка при создании канала: {e}")
        return

    # Создаем кнопки
    take_button = discord.ui.Button(style=discord.ButtonStyle.success, label="Взять", emoji="✋")
    close_button = discord.ui.Button(style=discord.ButtonStyle.danger, label="Закрыть", emoji="🔒")
    reason_button = discord.ui.Button(style=discord.ButtonStyle.secondary, label="Закрыть по причине", emoji="📝")

    async def take_callback(interaction):
        """Обработчик для кнопки "Взять"."""
        await interaction.response.send_message(f"Тикет взят пользователем {interaction.user.mention}", ephemeral=True)  # ephemeral=True делает сообщение видимым только для нажавшего кнопку
        # Добавьте здесь логику назначения тикета конкретному члену команды поддержки
    take_button.callback = take_callback

    async def close_callback(interaction):
        """Обработчик для кнопки "Закрыть"."""
        await interaction.response.send_message("Тикет закрывается...", ephemeral=True)
        await close_ticket(channel, interaction.user, reason=None) # Закрываем без причины
    close_button.callback = close_callback

    async def reason_callback(interaction):
        """Обработчик для кнопки "Закрыть по причине"."""
        await interaction.response.send_message("Укажите причину закрытия тикета:", ephemeral=True)

        def check(m):  # Локальная функция для проверки сообщения
            return m.author == interaction.user and m.channel == interaction.channel

        try:
            reason_message = await bot.wait_for('message', check=check, timeout=60)
            reason = reason_message.content
            await close_ticket(channel, interaction.user, reason=reason)
        except asyncio.TimeoutError:
            await interaction.channel.send(f"{interaction.user.mention}, время ожидания истекло. Тикет не был закрыт.")
    reason_button.callback = reason_callback

    view = discord.ui.View()
    view.add_item(take_button)
    view.add_item(close_button)
    view.add_item(reason_button)

    embed = discord.Embed(
        title=f"Тикет создан пользователем {ctx.author.name}",
        description=TICKET_MESSAGE,
        color=discord.Color.green()
    )
    embed.set_footer(text="Пожалуйста, дождитесь ответа команды поддержки.")

    try:
        await channel.send(ctx.author.mention, embed=embed, view=view)
    except discord.errors.Forbidden:
        await ctx.send("У бота недостаточно прав для отправки сообщений в этот канал.")
        await channel.delete(reason="Бот не может отправлять сообщения.")
        return

    await ctx.send(f"{ctx.author.mention}, ваш тикет создан: {channel.mention}")

async def close_ticket(channel, user, reason=None):
    """Функция для закрытия тикета и создания транскрипта."""

    # 1. Создаем транскрипт
    transcript_text = f"Транскрипт тикета {channel.name}\nЗакрыт пользователем: {user.name}#{user.discriminator}\n"
    if reason:
        transcript_text += f"Причина закрытия: {reason}\n"
    transcript_text += f"Дата закрытия: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    messages = []
    async for message in channel.history(limit=None, oldest_first=True): # Собираем все сообщения
        messages.append(message)

    for message in messages:
        timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
        transcript_text += f"[{timestamp}] {message.author.name}#{message.author.discriminator}: {message.content}\n"

    # 2. Отправляем транскрипт в канал транскриптов
    transcript_channel = bot.get_channel(TRANSCRIPT_CHANNEL_ID)
    if transcript_channel:
        try:
            transcript_file = discord.File(transcript_text.encode('utf-8'), filename=f"transcript-{channel.name}.txt")
            await transcript_channel.send(file=transcript_file)
        except discord.errors.Forbidden:
            print("У бота нет прав на отправку файлов в канал транскриптов.")
        except Exception as e:
            print(f"Ошибка при отправке транскрипта: {e}")
    else:
        print(f"Не найден канал транскриптов с ID {TRANSCRIPT_CHANNEL_ID}.")

    # 3. Удаляем канал тикета
    try:
        await channel.delete(reason=f"Тикет закрыт пользователем {user.name}")
    except discord.errors.Forbidden:
        print("У бота недостаточно прав для удаления канала. Необходимо право 'Manage Channels'.")
    except Exception as e:
        print(f"Произошла ошибка при закрытии канала: {e}")



# 4. Запуск бота

bot.run(TOKEN)
