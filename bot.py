# -*- coding: utf-8 -*-
import json
import logging
import os
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from telegram import (InlineKeyboardButton as B, InlineKeyboardMarkup as M,
                      InputMediaPhoto, Update)
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler,
                          ContextTypes, MessageHandler, filters)

from data import DUAS, EVENING, MORNING, STORIES, TASBEEH

TOKEN = os.environ["BOT_TOKEN"]  # من @BotFather

# صور صفحات المصحف (604 صفحة: 001.png .. 604.png). غيّر الرابط لو عندك مصدر تاني.
QURAN_URL = os.environ.get(
    "QURAN_URL",
    "https://raw.githubusercontent.com/GovarJabbar/Quran-PNG/master/{n:03d}.png",
)

MORNING_AT = "06:00"   # أذكار الصباح (بتوقيت المستخدم)
EVENING_AT = "17:30"   # أذكار المساء

PRAYERS = {"Fajr": "الفجر", "Dhuhr": "الظهر", "Asr": "العصر",
           "Maghrib": "المغرب", "Isha": "العشاء"}

USERS_FILE = "users.json"
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("bot")


# ---------- التخزين ----------
def load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def save_users():
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(USERS, f, ensure_ascii=False)


USERS = load_users()


def user(chat_id):
    return USERS.setdefault(str(chat_id), {"on": True, "sent": [], "sdate": ""})


# ---------- أدوات ----------
def menu_kb():
    return M([
        [B("🌅 أذكار الصباح", callback_data="m:morning"), B("🌇 أذكار المساء", callback_data="m:evening")],
        [B("📿 التسبيح", callback_data="tm:0"), B("🤲 الاستغفار", callback_data="tm:4")],
        [B("🕌 مواعيد الصلاة", callback_data="times")],
        [B("📖 المصحف", callback_data="q:1")],
        [B("📚 قصص دينية", callback_data="stories"), B("🌙 أدعية", callback_data="duas")],
    ])


def back_kb():
    return M([[B("🏠 القائمة", callback_data="home")]])


def render_adhkar(title, items):
    parts = [f"*{title}*\n"]
    for i, it in enumerate(items, 1):
        head = f"{it['h']}\n" if it.get("h") else ""
        parts.append(f"{i}. {head}{it['t']}\n(× {it['n']})")
    return "\n\n".join(parts)


async def send_long(bot, chat_id, text, **kw):
    for i in range(0, len(text), 3900):
        await bot.send_message(chat_id, text[i:i + 3900], **kw)


async def fetch_timings(city, country):
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get("https://api.aladhan.com/v1/timingsByCity",
                        params={"city": city, "country": country, "method": 5})
        r.raise_for_status()
    d = r.json()["data"]
    t = {k: d["timings"][k][:5] for k in list(PRAYERS) + ["Sunrise"]}
    return t, d["meta"]["timezone"]


def times_text(u):
    t = u["timings"]
    lines = [f"🕌 مواعيد الصلاة — {u['city']}\n"]
    lines.append(f"الفجر: {t['Fajr']}\nالشروق: {t['Sunrise']}")
    for k in ["Dhuhr", "Asr", "Maghrib", "Isha"]:
        lines.append(f"{PRAYERS[k]}: {t[k]}")
    return "\n".join(lines)


# ---------- الأوامر ----------
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user(update.effective_chat.id)
    save_users()
    await update.message.reply_text(
        "السلام عليكم ورحمة الله 🌙\nاختار من القائمة:\n\n"
        "لتفعيل تنبيهات الأذان والأذكار التلقائية ابعت:\n/city Cairo Egypt\n"
        "(اسم المدينة ثم الدولة بالإنجليزي)\n\n"
        "للانتقال لصفحة في المصحف ابعت رقمها (1-604).",
        reply_markup=menu_kb())


async def city(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if len(ctx.args) < 2:
        await update.message.reply_text("الصيغة: /city Cairo Egypt")
        return
    c, country = ctx.args[0], " ".join(ctx.args[1:])
    try:
        timings, tz = await fetch_timings(c, country)
    except Exception:
        await update.message.reply_text("مقدرتش أجيب المواعيد، اتأكد من اسم المدينة والدولة بالإنجليزي.")
        return
    u = user(update.effective_chat.id)
    u.update(city=c, country=country, timings=timings, tz=tz, on=True,
             tdate=datetime.now(ZoneInfo(tz)).strftime("%Y-%m-%d"))
    save_users()
    await update.message.reply_text(times_text(u) + "\n\n✅ تم تفعيل التنبيهات. /stop لإيقافها.")


async def stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user(update.effective_chat.id)["on"] = False
    save_users()
    await update.message.reply_text("تم إيقاف التنبيهات. /resume لإعادتها.")


async def resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user(update.effective_chat.id)["on"] = True
    save_users()
    await update.message.reply_text("تم تشغيل التنبيهات ✅")


async def page_by_number(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text.strip().translate(str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789"))
    if txt.isdigit() and 1 <= int(txt) <= 604:
        n = int(txt)
        await update.message.reply_photo(QURAN_URL.format(n=n), caption=f"صفحة {n} / 604",
                                         reply_markup=quran_kb(n))


def quran_kb(n):
    row = []
    if n > 1:
        row.append(B("◀️ السابقة", callback_data=f"q:{n - 1}"))
    if n < 604:
        row.append(B("التالية ▶️", callback_data=f"q:{n + 1}"))
    return M([row, [B("🏠 القائمة", callback_data="home")]])


# ---------- الأزرار ----------
async def on_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    d = q.data
    chat_id = q.message.chat_id

    if d == "home":
        await q.message.reply_text("القائمة الرئيسية:", reply_markup=menu_kb())

    elif d in ("m:morning", "m:evening"):
        items, title = (MORNING, "أذكار الصباح 🌅") if d == "m:morning" else (EVENING, "أذكار المساء 🌇")
        await send_long(ctx.bot, chat_id, render_adhkar(title, items))
        await ctx.bot.send_message(chat_id, "تقبل الله منك 🤍", reply_markup=back_kb())

    elif d.startswith("tm:"):  # فتح العدّاد
        await show_tasbeeh(q, int(d.split(":")[1]), 0)

    elif d.startswith("t:"):  # تسبيحة: t:<index>:<العدد الحالي>
        _, i, n = d.split(":")
        await show_tasbeeh(q, int(i), int(n) + 1)

    elif d.startswith("tn:"):  # الذكر التالي
        await show_tasbeeh(q, (int(d.split(":")[1]) + 1) % len(TASBEEH), 0)

    elif d.startswith("tr:"):
        await show_tasbeeh(q, int(d.split(":")[1]), 0)

    elif d == "times":
        u = user(chat_id)
        if not u.get("timings"):
            await q.message.reply_text("ابعت مدينتك الأول، مثال:\n/city Cairo Egypt", reply_markup=back_kb())
        else:
            await q.message.reply_text(times_text(u), reply_markup=back_kb())

    elif d.startswith("q:"):
        n = int(d.split(":")[1])
        media = InputMediaPhoto(QURAN_URL.format(n=n), caption=f"صفحة {n} / 604")
        try:
            await q.edit_message_media(media, reply_markup=quran_kb(n))
        except Exception:  # أول مرة من الرسالة النصية
            await ctx.bot.send_photo(chat_id, QURAN_URL.format(n=n), caption=f"صفحة {n} / 604",
                                     reply_markup=quran_kb(n))

    elif d == "stories":
        kb = [[B(s["title"], callback_data=f"s:{i}")] for i, s in enumerate(STORIES)]
        kb.append([B("🏠 القائمة", callback_data="home")])
        await q.message.reply_text("اختار قصة:", reply_markup=M(kb))

    elif d.startswith("s:"):
        s = STORIES[int(d.split(":")[1])]
        await send_long(ctx.bot, chat_id, f"{s['title']}\n\n{s['body']}", reply_markup=None)
        await ctx.bot.send_message(chat_id, "—", reply_markup=M([[B("📚 باقي القصص", callback_data="stories")]]))

    elif d == "duas":
        await send_long(ctx.bot, chat_id, "🌙 أدعية\n\n" + "\n\n".join(f"• {x}" for x in DUAS))
        await ctx.bot.send_message(chat_id, "اللهم تقبل 🤍", reply_markup=back_kb())


async def show_tasbeeh(q, i, count):
    kb = M([
        [B("➕ سبّح", callback_data=f"t:{i}:{count}")],
        [B("🔄 تصفير", callback_data=f"tr:{i}"), B("⏭ الذكر التالي", callback_data=f"tn:{i}")],
        [B("🏠 القائمة", callback_data="home")],
    ])
    text = f"{TASBEEH[i]}\n\nالعدد: {count}"
    try:
        await q.edit_message_text(text, reply_markup=kb)
    except Exception:
        await q.message.reply_text(text, reply_markup=kb)


# ---------- المنبّه الدوري (كل دقيقة) ----------
async def tick(ctx: ContextTypes.DEFAULT_TYPE):
    for chat_id, u in list(USERS.items()):
        if not u.get("on") or not u.get("city"):
            continue
        try:
            tz = ZoneInfo(u["tz"])
            now = datetime.now(tz)
            today, hm = now.strftime("%Y-%m-%d"), now.strftime("%H:%M")
            if u.get("sdate") != today:
                u["sdate"], u["sent"] = today, []
            if u.get("tdate") != today:
                u["timings"], u["tz"] = await fetch_timings(u["city"], u["country"])
                u["tdate"] = today

            events = [(k, hm == u["timings"][k]) for k in PRAYERS]
            events += [("morning", hm == MORNING_AT), ("evening", hm == EVENING_AT)]
            for key, due in events:
                if not due or key in u["sent"]:
                    continue
                u["sent"].append(key)
                if key == "morning":
                    await send_long(ctx.bot, int(chat_id), render_adhkar("أذكار الصباح 🌅", MORNING))
                elif key == "evening":
                    await send_long(ctx.bot, int(chat_id), render_adhkar("أذكار المساء 🌇", EVENING))
                else:
                    await ctx.bot.send_message(int(chat_id), f"🕌 حان الآن موعد أذان {PRAYERS[key]} — {u['city']}\nحيّ على الصلاة")
            save_users()
        except Exception as e:
            log.warning("tick failed for %s: %s", chat_id, e)


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("city", city))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("resume", resume))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, page_by_number))
    app.job_queue.run_repeating(tick, interval=60, first=5)
    app.run_polling()


if __name__ == "__main__":
    main()
