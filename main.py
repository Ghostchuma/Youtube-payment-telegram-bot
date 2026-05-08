import telebot
from telebot import types
import time
import psutil
from datetime import datetime
from threading import Thread
import re
from zoneinfo import ZoneInfo
#without .env
TOKEN = 'YOUR_ID'
bot = telebot.TeleBot(TOKEN)

START_TIME = time.time()
KYIV_TZ = ZoneInfo("Europe/Kyiv")
LAST_RESTART = datetime.now(KYIV_TZ).strftime("%B %d, %Y %I:%M %p")

chat_members = {}
user_data = {}
monthly_ping_state = {}

LANG = 'uk'

translations = {
    'menu': 'Головне меню',
    'start_welcome': (
        "Привіт! Я бот-нагадувач про оплату підписки.\n\n"
        "Що я вмію:\n"
        "• /schedule - запланувати нагадування\n"
        "• /settext - змінити текст пінгу\n"
        "• /status - показати статус\n"
        "• /help - коротка довідка\n\n"
        "Розробник: <a href=\"tg://user?id=432925925\">перейти</a>"
    ),
    'status_header': 'Статус Бота',
    'schedule': 'Запланувати тег',
    'help': 'Допомога',
    'edit_text': 'Змінити текст пінгу',
    'refresh': 'Скинути текст',
    'accept': 'Усі оплатили',
    'exit': 'Вийти /exit',
    'owner': 'Власник',
    'help_text': (
        "Доступні команди:\n"
        "/start - відкрити меню\n"
        "/status - статус бота\n"
        "/schedule - запланувати повідомлення (у групі лише для адмінів)\n"
        "/settext - змінити текст пінгу\n"
        "/refresh - скинути текст пінгу до стандартного\n"
        "/accept - повідомити, що всі оплатили\n"
        "/exit - вийти з режиму вводу\n"
        "/help - показати цю довідку"
    ),
    'group_welcome': 'Дякую, що додали мене до групи! Для роботи напишіть або натисніть /help.',
    'no_permission': 'Лише адміни чату можуть використовувати цю команду.',
    'no_access': 'У вас немає доступу до використання команд бота.',
    'enter_date': 'Введіть дату (РРРР-ММ-ДД).\nПриклад: 2026-05-06',
    'bad_date': 'Невірний формат дати.\nВикористовуйте РРРР-ММ-ДД\nПриклад: 2026-05-06',
    'enter_time': 'Введіть час (ГГ:ХХ).\nПриклад: 14:30',
    'bad_time': 'Невірний формат часу.\nВикористовуйте ГГ:ХХ (24г)\nПриклад: 14:30',
    'past_time': 'Цей час уже минув. Введіть майбутню дату/час.',
    'enter_custom_text': 'Надішліть новий текст пінгу.',
    'text_updated': 'Текст пінгу оновлено.',
    'text_reset': 'Текст пінгу скинуто до стандартного.',
    'accept_done': 'Усі оплатили підписку. Дякую! До нових зустрічей.',
    'flow_exited': 'Вихід із режиму вводу. Повертаю меню.',
    'done': 'Заплановано на: ',
    'error': 'Помилка. Формат: РРРР-ММ-ДД ГГ:ХХ',
    'monthly_sent': 'Щомісячне нагадування надіслано.',
}

DEFAULT_NOTIFY_TEXT = "<b>Час оплати підписки прийшов, нагадую 25 грн на карту 4441114459638795</b>"
NO_USERNAME_FALLBACK = "<b>Час оплати підписки</b>"

def escape_html(text):
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

def get_uptime():
    delta = time.time() - START_TIME
    d, h, m, s = int(delta//86400), int((delta%86400)//3600), int((delta%3600)//60), int(delta%60)
    return f"{d}d {h}h {m}m {s}s"

def get_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row(translations['status_header'], translations['schedule'])
    markup.row(translations['edit_text'], translations['help'])
    markup.row(translations['refresh'], translations['accept'])
    markup.row(translations['owner'], translations['exit'])
    return markup

def ensure_chat_data(chat_id):
    if chat_id not in user_data:
        user_data[chat_id] = {'ping_text': DEFAULT_NOTIFY_TEXT}
    if 'ping_text' not in user_data[chat_id]:
        user_data[chat_id]['ping_text'] = DEFAULT_NOTIFY_TEXT
    return user_data[chat_id]

def upsert_member(chat_id, user):
    if chat_id not in chat_members:
        chat_members[chat_id] = {}
    if user and not user.is_bot:
        chat_members[chat_id][user.id] = {
            'user_id': user.id,
            'username': user.username,
            'first_name': user.first_name or "Користувач"
        }

def build_mentions(chat_id):
    members = chat_members.get(chat_id, {})
    mentions = []
    for profile in members.values():
        username = profile.get('username')
        if username:
            mentions.append(f"@{username}")
        else:
            user_id = profile.get('user_id')
            first_name = escape_html(profile.get('first_name') or "Користувач")
            if user_id:
                mentions.append(f'<a href="tg://user?id={user_id}">{first_name}</a>')
    return mentions

def is_user_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception:
        return False

def has_access(message):
    if message.chat.type not in ['group', 'supergroup']:
        return True
    return is_user_admin(message.chat.id, message.from_user.id)

def deny_access(message):
    bot.send_message(
        message.chat.id,
        translations['no_access'],
        reply_markup=types.ReplyKeyboardRemove()
    )

def is_exit_text(text):
    if not text:
        return False
    txt = text.strip().lower()
    return txt == "/exit" or txt.startswith("/exit@")

def setup_bot_commands():
    commands = [
        types.BotCommand("start", "Відкрити меню"),
        types.BotCommand("status", "Показати статус бота"),
        types.BotCommand("schedule", "Запланувати повідомлення"),
        types.BotCommand("settext", "Змінити текст пінгу"),
        types.BotCommand("refresh", "Скинути текст пінгу"),
        types.BotCommand("accept", "Позначити що всі оплатили"),
        types.BotCommand("exit", "Вийти з режиму вводу"),
        types.BotCommand("help", "Показати довідку"),
    ]
    bot.set_my_commands(commands)
    bot.set_my_commands(commands, scope=types.BotCommandScopeAllPrivateChats())
    bot.set_my_commands(commands, scope=types.BotCommandScopeAllGroupChats())

@bot.message_handler(commands=['start'])
def cmd_start(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        bot.send_message(
            message.chat.id,
            f"{translations['start_welcome']}\n\n{translations['no_access']}",
            reply_markup=types.ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return
    bot.send_message(message.chat.id, translations['start_welcome'], reply_markup=get_menu(), parse_mode="HTML")

@bot.message_handler(commands=['status'])
def cmd_status(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    show_status(message)

@bot.message_handler(commands=['help'])
def cmd_help(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    bot.send_message(message.chat.id, translations['help_text'], reply_markup=get_menu())

@bot.message_handler(commands=['settext'])
def cmd_settext(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    msg = bot.send_message(message.chat.id, translations['enter_custom_text'], reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_custom_text)

@bot.message_handler(commands=['refresh'])
def cmd_refresh(message):
    data = ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    data['ping_text'] = DEFAULT_NOTIFY_TEXT
    bot.send_message(message.chat.id, translations['text_reset'], reply_markup=get_menu())

@bot.message_handler(commands=['accept'])
def cmd_accept(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    bot.send_message(message.chat.id, translations['accept_done'], reply_markup=get_menu())

@bot.message_handler(commands=['exit'])
def cmd_exit(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    bot.clear_step_handler_by_chat_id(message.chat.id)
    if not has_access(message):
        deny_access(message)
        return
    bot.send_message(message.chat.id, translations['flow_exited'], reply_markup=get_menu())

@bot.message_handler(commands=['schedule'])
def cmd_schedule(message):
    ensure_chat_data(message.chat.id)
    upsert_member(message.chat.id, message.from_user)
    if not has_access(message):
        deny_access(message)
        return
    start_schedule_flow(message)

def process_menu_button(message):
    if not message.text:
        return False
    ensure_chat_data(message.chat.id)
    if message.chat.type in ['group', 'supergroup']:
        upsert_member(message.chat.id, message.from_user)
    text = message.text.strip()
    if text == translations['status_header']:
        if not has_access(message):
            deny_access(message)
            return True
        show_status(message)
        return True
    if text == translations['schedule']:
        if not has_access(message):
            deny_access(message)
            return True
        start_schedule_flow(message)
        return True
    if text == translations['edit_text']:
        if not has_access(message):
            deny_access(message)
            return True
        msg = bot.send_message(message.chat.id, translations['enter_custom_text'], reply_markup=types.ReplyKeyboardRemove())
        bot.register_next_step_handler(msg, process_custom_text)
        return True
    if text == translations['help']:
        if not has_access(message):
            deny_access(message)
            return True
        cmd_help(message)
        return True
    if text == translations['refresh']:
        if not has_access(message):
            deny_access(message)
            return True
        cmd_refresh(message)
        return True
    if text == translations['accept']:
        if not has_access(message):
            deny_access(message)
            return True
        cmd_accept(message)
        return True
    if text == translations['owner']:
        bot.send_message(message.chat.id, 'Власник: <a href="tg://user?id=432925925">перейти</a>', parse_mode="HTML")
        return True
    if text == translations['exit']:
        cmd_exit(message)
        return True
    return False


@bot.message_handler(func=lambda m: bool(m.text) and m.chat.type in ['group', 'supergroup'] and re.match(r'^/(start|status|schedule|settext|refresh|accept|exit|help)(@\w+)?$', m.text.strip()))
def group_text_commands(message):
    cmd = message.text.split('@')[0].strip().lower()
    if cmd == '/start':
        cmd_start(message)
    elif cmd == '/status':
        cmd_status(message)
    elif cmd == '/schedule':
        cmd_schedule(message)
    elif cmd == '/settext':
        cmd_settext(message)
    elif cmd == '/refresh':
        cmd_refresh(message)
    elif cmd == '/accept':
        cmd_accept(message)
    elif cmd == '/exit':
        cmd_exit(message)
    elif cmd == '/help':
        cmd_help(message)

@bot.message_handler(content_types=['new_chat_members'])
def on_new_members(message):
    if message.chat.type not in ['group', 'supergroup']:
        return
    try:
        me = bot.get_me()
        if any(member.id == me.id for member in (message.new_chat_members or [])):
            bot.send_message(message.chat.id, translations['group_welcome'])
        for member in (message.new_chat_members or []):
            upsert_member(message.chat.id, member)
    except Exception:
        pass

def show_status(message):
    cid = message.chat.id
    users_count = len(chat_members.get(cid, []))
    process = psutil.Process()
    mem_mb = process.memory_info().rss / (1024 * 1024)
    cpu_percent = psutil.cpu_percent(interval=0.2)
    disk = psutil.disk_usage('/')
    disk_used_mb = disk.used / (1024 * 1024)
    disk_total_mb = disk.total / (1024 * 1024)

    status_msg = (
        f"{translations['status_header']}:\n\n"
        f"Uptime: {get_uptime()}\n"
        f"CPU Load: {cpu_percent:.2f}%\n"
        f"Memory: {mem_mb:.2f} MiB\n"
        f"Disk Usage: {disk_used_mb:.2f} MiB / {disk_total_mb:.2f} MiB\n"
        f"Учасників збережено: {users_count}\n"
        f"Останній перезапуск: {LAST_RESTART}"
    )
    bot.send_message(cid, status_msg)

def start_schedule_flow(message):
    msg = bot.send_message(message.chat.id, translations['enter_date'], reply_markup=types.ReplyKeyboardRemove())
    bot.register_next_step_handler(msg, process_date)

def process_date(message):
    if is_exit_text(message.text):
        cmd_exit(message)
        return
    data = ensure_chat_data(message.chat.id)
    date_text = (message.text or "").strip()
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', date_text):
        msg = bot.send_message(message.chat.id, translations['bad_date'])
        bot.register_next_step_handler(msg, process_date)
        return
    try:
        datetime.strptime(date_text, "%Y-%m-%d")
    except ValueError:
        msg = bot.send_message(message.chat.id, translations['bad_date'])
        bot.register_next_step_handler(msg, process_date)
        return
    data['date'] = date_text
    msg = bot.send_message(message.chat.id, translations['enter_time'])
    bot.register_next_step_handler(msg, process_time)

def process_time(message):
    if is_exit_text(message.text):
        cmd_exit(message)
        return
    data = ensure_chat_data(message.chat.id)
    time_text = (message.text or "").strip()
    if not re.match(r'^\d{2}:\d{2}$', time_text):
        msg = bot.send_message(message.chat.id, translations['bad_time'])
        bot.register_next_step_handler(msg, process_time)
        return
    try:
        datetime.strptime(time_text, "%H:%M")
    except ValueError:
        msg = bot.send_message(message.chat.id, translations['bad_time'])
        bot.register_next_step_handler(msg, process_time)
        return

    scheduled_at = f"{data.get('date', '')} {time_text}"
    try:
        check_target = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        if check_target <= datetime.now(KYIV_TZ):
            msg = bot.send_message(message.chat.id, translations['past_time'])
            bot.register_next_step_handler(msg, process_date)
            return
    except ValueError:
        msg = bot.send_message(message.chat.id, translations['bad_date'])
        bot.register_next_step_handler(msg, process_date)
        return

    data['time'] = time_text
    schedule_ping(message.chat.id)

def schedule_ping(chat_id):
    data = ensure_chat_data(chat_id)
    try:
        dt_str = f"{data['date']} {data['time']}"
        target_dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M").replace(tzinfo=KYIV_TZ)
        target_time = target_dt.timestamp()
        bot.send_message(chat_id, f"{translations['done']} {dt_str}", reply_markup=get_menu())

        def run_timer(target_cid, run_at):
            while time.time() < run_at:
                time.sleep(5)
            text = ensure_chat_data(target_cid).get('ping_text', DEFAULT_NOTIFY_TEXT)
            mentions = build_mentions(target_cid)
            if mentions:
                list_text = "\n".join([f"• {m}" for m in mentions])
                bot.send_message(target_cid, f"{text}\n\n<b>Кому потрібно оплатити:</b>\n{list_text}", parse_mode="HTML")
            else:
                bot.send_message(target_cid, NO_USERNAME_FALLBACK, parse_mode="HTML")

        Thread(target=run_timer, args=(chat_id, target_time), daemon=True).start()
    except Exception:
        bot.send_message(chat_id, translations['error'], reply_markup=get_menu())

def run_monthly_pings():
    while True:
        now = datetime.now(KYIV_TZ)
        if now.day == 28 and now.hour == 10 and now.minute == 30:
            for chat_id in list(chat_members.keys()):
                key = f"{now.year}-{now.month}"
                if monthly_ping_state.get(chat_id) == key:
                    continue
                mentions = build_mentions(chat_id)
                if mentions:
                    list_text = "\n".join([f"• {m}" for m in mentions])
                    bot.send_message(chat_id, f"{DEFAULT_NOTIFY_TEXT}\n\n<b>Кому потрібно оплатити:</b>\n{list_text}", parse_mode="HTML")
                else:
                    bot.send_message(chat_id, NO_USERNAME_FALLBACK, parse_mode="HTML")
                monthly_ping_state[chat_id] = key
            time.sleep(61)
            continue
        time.sleep(20)

def process_custom_text(message):
    if is_exit_text(message.text):
        cmd_exit(message)
        return
    data = ensure_chat_data(message.chat.id)
    text = (message.text or "").strip()
    if not text:
        text = DEFAULT_NOTIFY_TEXT
    data['ping_text'] = f"<b>{escape_html(text)}</b>"
    bot.send_message(message.chat.id, translations['text_updated'], reply_markup=get_menu())

@bot.message_handler(func=lambda m: True)
def collect_members(message):
    if message.chat.type in ['group', 'supergroup'] and message.from_user and not message.from_user.is_bot:
        upsert_member(message.chat.id, message.from_user)
    if process_menu_button(message):
        return

setup_bot_commands()
Thread(target=run_monthly_pings, daemon=True).start()
bot.infinity_polling()