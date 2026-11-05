import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, available_timezones

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BotCommand, CallbackQuery, FSInputFile, InlineKeyboardButton, KeyboardButton, Message,
                           ReplyKeyboardMarkup)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
import figures
import program as pg
from exercises import BY_ID, TESTS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")

def _load_env():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8-sig"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


_load_env()
TOKEN = os.environ["BOT_TOKEN"]
ALLOWED = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
EVENING = "22:00"
MEDIA_VER = "v1"

router = Router()

BTN_TODAY, BTN_PLAN, BTN_PROGRESS, BTN_SETTINGS = "🏋️ Сегодня", "📅 План", "📈 Прогресс", "⚙️ Настройки"
MAIN_KB = ReplyKeyboardMarkup(resize_keyboard=True, keyboard=[
    [KeyboardButton(text=BTN_TODAY), KeyboardButton(text=BTN_PLAN)],
    [KeyboardButton(text=BTN_PROGRESS), KeyboardButton(text=BTN_SETTINGS)],
])

TZS = [("Калининград", "Europe/Kaliningrad"), ("Москва", "Europe/Moscow"), ("Самара", "Europe/Samara"),
       ("Екатеринбург", "Asia/Yekaterinburg"), ("Омск", "Asia/Omsk"), ("Новосибирск", "Asia/Novosibirsk"),
       ("Красноярск", "Asia/Krasnoyarsk"), ("Иркутск", "Asia/Irkutsk"), ("Владивосток", "Asia/Vladivostok")]
LEGS = {"straddle": "Врозь", "pike": "Вместе", "both": "Чередовать"}
STARTS = {"stand": "Только стоя", "both": "Стоя + иногда из седа", "sit": "Из седа"}
DEFAULT_DAYS = {2: [1, 4], 3: [0, 2, 4], 4: [0, 1, 3, 4], 5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5]}
STATUS = {"done": "✅ Сделано", "part": "🟡 Сделано частично", "skip": "❌ Пропущено", "sent": ""}
ONB_ORDER = ["weeks", "days", "time", "tz", "ev", "legs", "start", "sd"]


class Wait(StatesGroup):
    time = State()
    tz = State()


# ---------------------------------------------------------------- helpers

def allowed(uid):
    return not ALLOWED or uid in ALLOWED


def today_of(user):
    return datetime.now(ZoneInfo(user["tz"])).date()


def done_before(uid, d):
    return sum(1 for w in db.workouts(uid) if w["status"] in ("done", "part") and w["date"] < d.isoformat())


def kb(rows):
    b = InlineKeyboardBuilder()
    for row in rows:
        b.row(*[InlineKeyboardButton(text=t, callback_data=c) for t, c in row])
    return b.as_markup()


def chunk(items, n):
    return [items[i:i + n] for i in range(0, len(items), n)]


# ---------------------------------------------------------------- pickers

def picker(field, user):
    """Возвращает (текст, клавиатура) для выбора настройки."""
    if field == "weeks":
        rows = chunk([(f"{'• ' if user['base_weeks'] == w else ''}{w} нед.", f"set:weeks:{w}")
                      for w in (4, 6, 8, 10, 12)], 3)
        return "Сколько недель тренировать спичаг? (1–3 месяца)", kb(rows)
    if field == "days":
        days = pg.days_of(user)
        presets = [(f"{n}×/нед", f"days:n:{n}") for n in range(2, 7)]
        toggles = [(("✅ " if i in days else "") + d, f"days:t:{i}") for i, d in enumerate(pg.WEEKDAYS)]
        return (f"Сколько раз в неделю и в какие дни?\nСейчас: <b>{len(days)}× в неделю</b> "
                f"({', '.join(pg.WEEKDAYS[i] for i in days) or '—'}).\n"
                "Выбери вариант или переключай дни вручную.",
                kb([presets, toggles[:4], toggles[4:], [("Готово ➡️", "days:ok")]]))
    if field == "time":
        times = [f"{h:02d}:{m:02d}" for h in range(6, 11) for m in (0, 30)]
        rows = chunk([(("• " if user["morning"] == t else "") + t, f"set:time:{t}") for t in times], 5)
        rows.append([("✍️ Другое время", "set:time:custom")])
        return "Во сколько присылать тренировку утром?", kb(rows)
    if field == "tz":
        rows = chunk([(("• " if user["tz"] == z else "") + n, f"set:tz:{z}") for n, z in TZS], 3)
        rows.append([("✍️ Другой", "set:tz:custom")])
        return f"Часовой пояс? Сейчас: <b>{user['tz']}</b>", kb(rows)
    if field == "ev":
        return (f"Напоминать в {EVENING}, если тренировка не отмечена?",
                kb([[("🔔 Да", "set:ev:1"), ("🔕 Нет", "set:ev:0")]]))
    if field == "legs":
        return ("Спичаг ноги врозь или вместе?",
                kb([[(("• " if user["legs"] == k else "") + v, f"set:legs:{k}") for k, v in LEGS.items()]]))
    if field == "start":
        return ("Стартовая позиция спичага:",
                kb([[(("• " if user["start_pos"] == k else "") + v, f"set:start:{k}")] for k, v in STARTS.items()]))
    if field == "sd":
        return ("Когда начинаем? (при смене даты прогресс обнуляется)",
                kb([[("Сегодня", "set:sd:0"), ("Завтра", "set:sd:1"), ("С понедельника", "set:sd:mon")]]))
    raise ValueError(field)


def settings_view(user):
    days = ", ".join(pg.WEEKDAYS[i] for i in pg.days_of(user))
    end = pg.end_of(user).strftime("%d.%m.%Y") if user["start_date"] else "—"
    text = ("<b>⚙️ Настройки</b>\n"
            f"Программа: {user['base_weeks']} нед." + (f" + {user['extra_weeks']} продление" if user["extra_weeks"] else "")
            + f" (до {end})\n"
            f"Дни: {days}\nУтром: {user['morning']} ({user['tz']})\n"
            f"Вечернее напоминание: {'вкл' if user['evening'] else 'выкл'}\n"
            f"Ноги: {LEGS[user['legs']]}\nСтарт: {STARTS[user['start_pos']]}\n"
            f"Статус: {'активна' if user['active'] else '⏸ на паузе'}")
    return text, kb([
        [("📆 Срок", "menu:weeks"), ("🗓 Дни", "menu:days")],
        [("⏰ Время", "menu:time"), ("🌍 Пояс", "menu:tz"), ("🔔 Вечер", "menu:ev")],
        [("🦵 Ноги", "menu:legs"), ("🧍 Старт", "menu:start")],
        [("➕ Продлить", "menu:ext"), ("⏸ Пауза / ▶️", "menu:pause")],
        [("🔄 Начать заново", "menu:reset")],
    ])


async def after_set(field, msg: Message, user, state: FSMContext):
    data = await state.get_data()
    if data.get("onb"):
        i = ONB_ORDER.index(field)
        if i + 1 < len(ONB_ORDER):
            text, markup = picker(ONB_ORDER[i + 1], user)
            await msg.edit_text(text, reply_markup=markup) if msg.from_user.is_bot else await msg.answer(text, reply_markup=markup)
            return
        await state.clear()
        db.update_user(user["user_id"], active=1)
        user = db.get_user(user["user_id"])
        text = "Готово! 🎉 Программа составлена.\n\n" + settings_view(user)[0]
        await (msg.edit_text(text) if msg.from_user.is_bot else msg.answer(text))
        await msg.answer("Меню внизу 👇", reply_markup=MAIN_KB)
        await show_today(msg.bot, user)
        return
    text, markup = settings_view(user)
    await msg.edit_text(text, reply_markup=markup) if msg.from_user.is_bot else await msg.answer(text, reply_markup=markup)


# ---------------------------------------------------------------- workout

def workout_kb(w, iso, status):
    exs = pg.numbered(w)
    rows = chunk([(f"📖 {i + 1}", f"ex:{e.id}") for i, e in enumerate(exs)], 4)
    if status in (None, "sent"):
        rows.append([("✅ Сделал", f"w:{iso}:done"), ("🟡 Частично", f"w:{iso}:part"), ("❌ Пропуск", f"w:{iso}:skip")])
    else:
        rows.append([("↩️ Изменить отметку", f"w:{iso}:undo")])
    return kb(rows)


def workout_text(w, status):
    t = pg.format_workout(w)
    if status and STATUS.get(status):
        t += f"\n\n<b>{STATUS[status]}</b>"
    return t


async def send_workout(bot, user, d, prefix=""):
    w = pg.build(user, d, done_before(user["user_id"], d))
    db.set_workout(user["user_id"], d.isoformat())
    status = db.get_workout(user["user_id"], d.isoformat())["status"]
    await bot.send_message(user["chat_id"], prefix + workout_text(w, status),
                           reply_markup=workout_kb(w, d.isoformat(), status))


async def show_today(bot, user):
    d = today_of(user)
    if not user["active"]:
        await bot.send_message(user["chat_id"], "Программа на паузе. Включить: ⚙️ Настройки → Пауза / ▶️")
        return
    if d < pg.start_of(user):
        await bot.send_message(user["chat_id"], f"Старт программы {pg.start_of(user).strftime('%d.%m')}. "
                                                f"Первая тренировка придёт утром в {user['morning']}.")
        return
    if d > pg.end_of(user):
        await bot.send_message(user["chat_id"], "🏁 Программа завершена. Можно продлить:", reply_markup=ext_kb())
        return
    if not pg.is_training_day(user, d):
        nxt = pg.next_training_day(user, d)
        when = f"{pg.WEEKDAYS[nxt.weekday()]} {nxt.strftime('%d.%m')}" if nxt else "—"
        await bot.send_message(user["chat_id"], f"Сегодня день отдыха 😌\nСледующая тренировка: {when}")
        return
    await send_workout(bot, user, d)


def ext_kb():
    return kb([[("+1 неделя", "ext:1"), ("+2 недели", "ext:2"), ("+4 недели", "ext:4")]])


async def send_media(bot, chat_id, ex):
    caption = (f"<b>{ex.name}</b>\n{ex.sets if ex.sets > 1 else ''}{' × ' if ex.sets > 1 else ''}{ex.reps}\n\n"
               f"<b>Как:</b> {ex.how}\n\n<b>Ошибки:</b> {ex.mistakes}")
    key = f"{MEDIA_VER}:{ex.id}"
    file_id = db.media_get(key)
    try:
        if file_id:
            await bot.send_animation(chat_id, file_id, caption=caption[:1024])
            return
    except Exception:
        log.warning("cached file_id failed for %s", ex.id)
    path = figures.gif_path(ex.id)
    if not path.exists():
        figures.render(ex)
    msg = await bot.send_animation(chat_id, FSInputFile(path), caption=caption[:1024])
    if msg.animation:
        db.media_set(key, msg.animation.file_id)
    elif msg.document:
        db.media_set(key, msg.document.file_id)


# ---------------------------------------------------------------- handlers

@router.message.outer_middleware()
async def guard_msg(handler, event, data):
    if not allowed(event.from_user.id):
        return await event.answer("Это личный бот 🙂")
    return await handler(event, data)


@router.callback_query.outer_middleware()
async def guard_cb(handler, event, data):
    if not allowed(event.from_user.id):
        return await event.answer("Это личный бот", show_alert=True)
    return await handler(event, data)


@router.message(CommandStart())
async def cmd_start(m: Message, state: FSMContext):
    user = db.get_user(m.from_user.id)
    if user and user["active"] and user["start_date"]:
        await m.answer("С возвращением! 👋", reply_markup=MAIN_KB)
        return
    user = db.create_user(m.from_user.id, m.chat.id)
    await state.set_data({"onb": True})
    await m.answer("Привет! Я помогу выучить <b>спичаг с пола</b> 🤸\n"
                   "Тренировки по 10–20 минут: подкачка, техника, растяжка. Сложность растёт постепенно, "
                   "а каждые 2 недели — тест.\n\nИнвентарь: коврик, стена, кубики, ролл.\n\nНастроим программу:")
    text, markup = picker("weeks", user)
    await m.answer(text, reply_markup=markup)


@router.message(Command("today"))
@router.message(F.text == BTN_TODAY)
async def cmd_today(m: Message):
    user = db.get_user(m.from_user.id)
    if not user or not user["start_date"]:
        return await m.answer("Сначала настроим программу: /start")
    await show_today(m.bot, user)


@router.message(Command("plan"))
@router.message(F.text == BTN_PLAN)
async def cmd_plan(m: Message):
    user = db.get_user(m.from_user.id)
    if not user or not user["start_date"]:
        return await m.answer("Сначала /start")
    d0 = max(today_of(user), pg.start_of(user))
    lines = ["<b>📅 Ближайшие 7 дней</b>"]
    for i in range(7):
        d = d0 + timedelta(days=i)
        label = f"{pg.WEEKDAYS[d.weekday()]} {d.strftime('%d.%m')}"
        if not pg.is_training_day(user, d):
            lines.append(f"{label} — отдых")
            continue
        w = pg.build(user, d, done_before(user["user_id"], min(d, today_of(user))))
        skill = [it.ex.name for it in w.items if it.block == "skill"]
        tag = "📏 Тест" if w.test else ", ".join(skill)
        lines.append(f"<b>{label}</b> — {tag}" + (" (разгрузка)" if w.deload else ""))
    await m.answer("\n".join(lines))


@router.message(Command("progress"))
@router.message(F.text == BTN_PROGRESS)
async def cmd_progress(m: Message):
    user = db.get_user(m.from_user.id)
    if not user or not user["start_date"]:
        return await m.answer("Сначала /start")
    d = today_of(user)
    ws = {w["date"]: w["status"] for w in db.workouts(user["user_id"])}
    past = [x for x in pg.training_dates(user, min(d, pg.end_of(user)))]
    done = sum(ws.get(x.isoformat()) == "done" for x in past)
    part = sum(ws.get(x.isoformat()) == "part" for x in past)
    streak = 0
    for x in reversed(past):
        st = ws.get(x.isoformat())
        if st in ("done", "part"):
            streak += 1
        elif x == d and st in (None, "sent"):
            continue
        else:
            break
    total = len(pg.training_dates(user))
    cd = min(max(d, pg.start_of(user)), pg.end_of(user))
    ph, _ = pg.phase(user, cd)
    lvl = pg.target_level(user, cd, done_before(user["user_id"], cd))
    bar = "▓" * round(10 * len(past) / total) + "░" * (10 - round(10 * len(past) / total))
    lines = [f"<b>📈 Прогресс</b>",
             f"Неделя {pg.week_no(user, cd)} из {user['base_weeks'] + user['extra_weeks']} · фаза: {ph} · уровень {lvl}/5",
             f"{bar} {len(past)}/{total} тренировок",
             f"✅ {done}  🟡 {part}  ❌ {len(past) - done - part}",
             f"🔥 Серия: {streak}"]
    tests = db.tests(user["user_id"])
    if tests:
        lines.append("\n<b>📏 Тесты</b>")
        for key, q, opts in TESTS:
            hist = [f"{t['date'][8:10]}.{t['date'][5:7]}: {t['value']}" for t in tests if t["key"] == key][-4:]
            if hist:
                lines.append(f"<i>{q}</i>\n  " + "\n  ".join(hist))
    markup = ext_kb() if d >= pg.end_of(user) - timedelta(days=7) else None
    if markup:
        lines.append("\nПрограмма подходит к концу — можно продлить:")
    await m.answer("\n".join(lines), reply_markup=markup)


@router.message(Command("settings"))
@router.message(F.text == BTN_SETTINGS)
async def cmd_settings(m: Message):
    user = db.get_user(m.from_user.id)
    if not user or not user["start_date"]:
        return await m.answer("Сначала /start")
    text, markup = settings_view(user)
    await m.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("menu:"))
async def cb_menu(c: CallbackQuery, state: FSMContext):
    field = c.data.split(":")[1]
    user = db.get_user(c.from_user.id)
    await state.update_data(onb=False)
    if field == "pause":
        db.update_user(user["user_id"], active=0 if user["active"] else 1)
        text, markup = settings_view(db.get_user(user["user_id"]))
        await c.message.edit_text(text, reply_markup=markup)
    elif field == "ext":
        await c.message.edit_text("На сколько продлить программу? Продление — фаза полных спичагов.",
                                  reply_markup=ext_kb())
    elif field == "reset":
        await c.message.edit_text("Сбросить прогресс и тесты и пройти настройку заново?",
                                  reply_markup=kb([[("Да, сбросить", "reset:yes"), ("Отмена", "reset:no")]]))
    else:
        text, markup = picker(field, user)
        await c.message.edit_text(text, reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("reset:"))
async def cb_reset(c: CallbackQuery, state: FSMContext):
    user = db.get_user(c.from_user.id)
    if c.data == "reset:yes":
        db.reset_progress(user["user_id"])
        db.update_user(user["user_id"], active=0, extra_weeks=0)
        await state.set_data({"onb": True})
        text, markup = picker("weeks", db.get_user(user["user_id"]))
        await c.message.edit_text(text, reply_markup=markup)
    else:
        text, markup = settings_view(user)
        await c.message.edit_text(text, reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("ext:"))
async def cb_ext(c: CallbackQuery):
    n = int(c.data.split(":")[1])
    user = db.get_user(c.from_user.id)
    db.update_user(user["user_id"], extra_weeks=user["extra_weeks"] + n, active=1)
    user = db.get_user(user["user_id"])
    await c.message.edit_text(f"➕ Продлено на {n} нед. Новый финиш: {pg.end_of(user).strftime('%d.%m.%Y')}")
    await c.answer()


@router.callback_query(F.data.startswith("days:"))
async def cb_days(c: CallbackQuery, state: FSMContext):
    _, act, *rest = c.data.split(":")
    user = db.get_user(c.from_user.id)
    days = set(pg.days_of(user))
    if act == "n":
        days = set(DEFAULT_DAYS[int(rest[0])])
    elif act == "t":
        days ^= {int(rest[0])}
    elif act == "ok":
        if len(days) < 1:
            return await c.answer("Выбери хотя бы один день", show_alert=True)
        await c.answer()
        return await after_set("days", c.message, user, state)
    db.update_user(user["user_id"], days=",".join(map(str, sorted(days))))
    text, markup = picker("days", db.get_user(user["user_id"]))
    await c.message.edit_text(text, reply_markup=markup)
    await c.answer()


@router.callback_query(F.data.startswith("set:"))
async def cb_set(c: CallbackQuery, state: FSMContext):
    _, field, value = c.data.split(":", 2)
    uid = c.from_user.id
    if value == "custom":
        if field == "time":
            await state.set_state(Wait.time)
            await c.message.edit_text("Напиши время в формате ЧЧ:ММ, например 07:15")
        else:
            await state.set_state(Wait.tz)
            await c.message.edit_text("Напиши часовой пояс в формате IANA, например Europe/Minsk или Asia/Almaty")
        return await c.answer()
    if field == "weeks":
        db.update_user(uid, base_weeks=int(value))
    elif field == "time":
        db.update_user(uid, morning=value)
    elif field == "tz":
        db.update_user(uid, tz=value)
    elif field == "ev":
        db.update_user(uid, evening=int(value))
    elif field == "legs":
        db.update_user(uid, legs=value)
    elif field == "start":
        db.update_user(uid, start_pos=value)
    elif field == "sd":
        t = today_of(db.get_user(uid))
        d = t if value == "0" else t + timedelta(days=1) if value == "1" else t + timedelta(days=7 - t.weekday())
        db.reset_progress(uid)
        db.update_user(uid, start_date=d.isoformat(), extra_weeks=0)
    await c.answer("Сохранено")
    await after_set(field, c.message, db.get_user(uid), state)


@router.message(Wait.time)
async def wait_time(m: Message, state: FSMContext):
    try:
        t = datetime.strptime(m.text.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return await m.answer("Не понял 🙈 Формат ЧЧ:ММ, например 07:15")
    db.update_user(m.from_user.id, morning=t)
    await state.set_state(None)
    await after_set("time", m, db.get_user(m.from_user.id), state)


@router.message(Wait.tz)
async def wait_tz(m: Message, state: FSMContext):
    tz = m.text.strip()
    if tz not in available_timezones():
        return await m.answer("Такого пояса не знаю. Пример: Europe/Minsk")
    db.update_user(m.from_user.id, tz=tz)
    await state.set_state(None)
    await after_set("tz", m, db.get_user(m.from_user.id), state)


@router.callback_query(F.data.startswith("ex:"))
async def cb_ex(c: CallbackQuery):
    ex = BY_ID.get(c.data[3:])
    await c.answer()
    if ex:
        await send_media(c.bot, c.message.chat.id, ex)


@router.callback_query(F.data.startswith("w:"))
async def cb_workout(c: CallbackQuery):
    _, iso, act = c.data.split(":")
    user = db.get_user(c.from_user.id)
    d = date.fromisoformat(iso)
    status = "sent" if act == "undo" else act
    db.set_workout(user["user_id"], iso, status=status)
    w = pg.build(user, d, done_before(user["user_id"], d))
    await c.message.edit_text(workout_text(w, status), reply_markup=workout_kb(w, iso, status))
    await c.answer({"done": "Отлично! 💪", "part": "Тоже засчитано 👍", "skip": "Ок, в следующий раз",
                    "sent": "Отметка снята"}[status])
    if status in ("done", "part") and w.test:
        await ask_test(c.bot, user["chat_id"], iso, 0)
    elif status in ("done", "part") and d == pg.training_dates(user)[-1]:
        await c.message.answer("🏁 Это была последняя тренировка программы! Хочешь продлить?", reply_markup=ext_kb())


async def ask_test(bot, chat_id, iso, i):
    key, q, opts = TESTS[i]
    rows = [[(o, f"t:{iso}:{i}:{j}")] for j, o in enumerate(opts)]
    await bot.send_message(chat_id, f"📏 Тест {i + 1}/{len(TESTS)}\n{q}", reply_markup=kb(rows))


@router.callback_query(F.data.startswith("t:"))
async def cb_test(c: CallbackQuery):
    _, iso, i, j = c.data.split(":")
    i, j = int(i), int(j)
    key, q, opts = TESTS[i]
    db.save_test(c.from_user.id, iso, key, opts[j])
    await c.message.edit_text(f"📏 {q}\n<b>{opts[j]}</b>")
    await c.answer()
    if i + 1 < len(TESTS):
        await ask_test(c.bot, c.message.chat.id, iso, i + 1)
    else:
        await c.message.answer("Тест записан ✍️ Динамика — в 📈 Прогресс.")


# ---------------------------------------------------------------- scheduler

async def ticker(bot: Bot):
    while True:
        try:
            for user in db.all_users():
                if not user["start_date"]:
                    continue
                now = datetime.now(ZoneInfo(user["tz"]))
                d, hm = now.date(), now.strftime("%H:%M")
                if not pg.is_training_day(user, d):
                    continue
                w = db.get_workout(user["user_id"], d.isoformat())
                if hm == user["morning"] and w is None:
                    await send_workout(bot, user, d, prefix="Доброе утро! ☀️\n\n")
                elif hm == EVENING and user["evening"] and (w is None or w["status"] == "sent") \
                        and not (w and w["reminded"]):
                    db.set_workout(user["user_id"], d.isoformat(), reminded=1)
                    await send_workout(bot, user, d, prefix="🔔 Напоминание: тренировка ещё не отмечена.\n\n")
        except Exception:
            log.exception("ticker error")
        await asyncio.sleep(20)


async def main():
    db.init()
    figures.render_all()
    bot = Bot(TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
    dp = Dispatcher()
    dp.include_router(router)
    await bot.set_my_commands([
        BotCommand(command="today", description="Тренировка на сегодня"),
        BotCommand(command="plan", description="План на неделю"),
        BotCommand(command="progress", description="Прогресс и тесты"),
        BotCommand(command="settings", description="Настройки"),
        BotCommand(command="start", description="Начать / настройка"),
    ])
    asyncio.create_task(ticker(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
