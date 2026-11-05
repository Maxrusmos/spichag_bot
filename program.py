"""Генерация тренировки на конкретную дату.

План детерминирован: зависит от настроек, даты и числа выполненных тренировок,
поэтому его не нужно хранить и он автоматически пересчитывается при смене настроек.
"""

import random
from dataclasses import dataclass
from datetime import date, timedelta

from exercises import BLOCK_TITLES, EXERCISES, Exercise

WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def days_of(user):
    return sorted(int(d) for d in user["days"].split(",") if d != "")


def start_of(user):
    return date.fromisoformat(user["start_date"])


def end_of(user):
    """Последний день программы (включительно)."""
    return start_of(user) + timedelta(weeks=user["base_weeks"] + user["extra_weeks"]) - timedelta(days=1)


def is_training_day(user, d):
    return start_of(user) <= d <= end_of(user) and d.weekday() in days_of(user)


def training_dates(user, until=None):
    d, end = start_of(user), until or end_of(user)
    out = []
    while d <= end:
        if d.weekday() in days_of(user):
            out.append(d)
        d += timedelta(days=1)
    return out


def next_training_day(user, after):
    d = after + timedelta(days=1)
    while d <= end_of(user):
        if d.weekday() in days_of(user):
            return d
        d += timedelta(days=1)
    return None


def week_no(user, d):
    return (d - start_of(user)).days // 7 + 1


def phase(user, d):
    w, base = week_no(user, d), user["base_weeks"]
    if w > base:
        return "Продление", 1.0
    frac = (d - start_of(user)).days / (base * 7)
    name = "База" if frac < .3 else "Сила" if frac < .7 else "Интеграция"
    return name, frac


def is_test_day(user, d):
    """Первая тренировка каждой чётной недели + последняя тренировка программы."""
    if not is_training_day(user, d):
        return False
    if d == training_dates(user)[-1]:
        return True
    w = week_no(user, d)
    week_start = start_of(user) + timedelta(weeks=w - 1)
    first = next((x for x in training_dates(user, week_start + timedelta(days=6)) if x >= week_start), None)
    last = training_dates(user)[-1]
    if week_start <= last <= week_start + timedelta(days=6):
        return False  # в последнюю неделю тест только в финальной тренировке
    return w % 2 == 0 and d == first


def is_deload(user, d):
    w = week_no(user, d)
    return w % 4 == 0 and w < user["base_weeks"]


@dataclass
class Item:
    block: str
    ex: Exercise
    sets: int
    note: str = ""
    bonus: bool = False


@dataclass
class Workout:
    date: date
    week: int
    total_weeks: int
    phase: str
    level: int
    deload: bool
    test: bool
    items: list


def target_level(user, d, done_count):
    _, frac = phase(user, d)
    by_calendar = min(5, 2 + int(frac * 4))  # человек уже близок к элементу
    planned = max(1, len([x for x in training_dates(user) if x < start_of(user) + timedelta(weeks=user["base_weeks"])]))
    by_done = min(5, 2 + int(done_count / planned * 5))  # пропуски тормозят рост сложности
    return max(1, min(by_calendar, by_done))


def _pick(rng, pool, n, exclude=()):
    pool = [e for e in pool if e.id not in exclude]
    rng.shuffle(pool)
    return pool[:n]


def _press_note(user, idx, ex):
    if not ex.press:
        return ""
    legs = {"straddle": "ноги врозь", "pike": "ноги вместе"}.get(user["legs"])
    if not legs:
        legs = "ноги врозь" if idx % 2 == 0 else "ноги вместе"
    note = legs
    if ex.id in ("press_pause", "press_blocks") and user["start_pos"] in ("sit", "both") and (user["start_pos"] == "sit" or idx % 3 == 2):
        note += ", старт из седа (ладони на кубиках, оторви таз и ноги)"
    return note


def build(user, d, done_count):
    rng = random.Random(f"{user['user_id']}-{d.isoformat()}")
    idx = len(training_dates(user, d))
    level = target_level(user, d, done_count)
    deload = is_deload(user, d)
    test = is_test_day(user, d)
    ph, _ = phase(user, d)

    def by(block, lo, hi):
        return [e for e in EXERCISES if e.block == block and lo <= e.level <= hi]

    items = [Item("warmup", e, e.sets) for e in [next(e for e in EXERCISES if e.id == "wrists")]
             + _pick(rng, by("warmup", 1, 1), 1, exclude={"wrists"})]

    s_hi = min(level, 3)
    for e in _pick(rng, by("strength", max(1, s_hi - 1), s_hi), 1 if test else 2):
        items.append(Item("strength", e, e.sets))

    if test:
        items.append(Item("test", None, 0))
    else:
        skills = _pick(rng, by("skill", max(1, level - 1), level), 2)
        if level < 5 and rng.random() < .25:  # «пробное» упражнение уровнем выше
            harder = _pick(rng, by("skill", level + 1, level + 1), 1)
            if harder:
                skills = skills[:1] + harder
        for e in skills:
            items.append(Item("skill", e, e.sets, _press_note(user, idx, e), bonus=e.level > level))

    items.append(Item("stretch", _pick(rng, by("stretch", 1, 5), 1)[0], 1))

    if deload:
        for it in items:
            if it.block in ("strength", "skill"):
                it.sets = max(1, it.sets - 1)
    return Workout(d, week_no(user, d), user["base_weeks"] + user["extra_weeks"], ph, level, deload, test, items)


def format_workout(w):
    from exercises import TEST_EXERCISE_NOTE
    head = f"<b>Тренировка {w.date.strftime('%d.%m')}</b> · неделя {w.week}/{w.total_weeks} · {w.phase}"
    lines = [head]
    if w.deload:
        lines.append("<i>Разгрузочная неделя: подходов меньше, работай чисто.</i>")
    if w.test:
        lines.append("<i>Сегодня день теста 📏 — после тренировки отметишь результаты.</i>")
    n, cur = 0, None
    for it in w.items:
        if it.block != cur:
            cur = it.block
            lines.append(f"\n<b>{BLOCK_TITLES[cur]}</b>")
        if it.block == "test":
            lines.append(TEST_EXERCISE_NOTE)
            continue
        n += 1
        dose = it.ex.reps if it.sets == 1 else f"{it.sets} × {it.ex.reps}"
        star = " ⭐️" if it.bonus else ""
        lines.append(f"{n}. {it.ex.name}{star} — {dose}")
        if it.note:
            lines.append(f"    <i>{it.note}</i>")
    if any(it.bonus for it in w.items):
        lines.append("\n⭐️ — пробное упражнение посложнее. Пробуй аккуратно, сколько получится.")
    lines.append("\n📖 Кнопки с номерами — техника и анимация.")
    return "\n".join(lines)


def numbered(w):
    return [it.ex for it in w.items if it.ex is not None]
