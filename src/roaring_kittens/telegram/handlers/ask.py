import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from roaring_kittens.ai.analyst import run_analyst
from roaring_kittens.broker.tech import compute_tech_summary
from roaring_kittens.db.calls import get_last_call, save_call
from roaring_kittens.db.owner import fetch_owner_id
from roaring_kittens.deps import Deps
from roaring_kittens.news.repository import get_news_for_tickers
from roaring_kittens.telegram.formatting import format_analyst_report, format_prev_call_note
from roaring_kittens.universe.universe import Instrument

log = structlog.get_logger()
router = Router()

USAGE = "Формат: <code>/ask SBER</code> или <code>/ask SBER стоит докупать?</code>"

LIMIT_REACHED = ("⏳ Лимит запросов на сегодня исчерпан ({limit}/день для гостей). "
                 "Приходи завтра!")

# Для гостей и пустого портфеля — самые ходовые бумаги IMOEX.
# (MGNT исключён: Магнит вылетел из индекса, universe его не знает.)
POPULAR_TICKERS = ["SBER", "GAZP", "LKOH", "YDEX", "T", "OZON", "ROSN", "NVTK"]

# Пул примеров для подсказки «свой вопрос» — показываем случайные при каждом открытии.
# Только вопросы, под которыми у бота РЕАЛЬНО есть данные (свечи + новости).
# «Дивиденды» и «дёшево ли» появятся с Fundamentals-аналитиком в Фазе 2.
EXAMPLE_QUESTIONS = [
    "почему падает?",
    "почему растёт?",
    "какие главные риски?",
    "стоит докупать?",
    "что говорят последние новости?",
    "как выглядит техническая картина?",
    "на каких уровнях поддержка?",
]


def pick_examples(tickers: list[str], n: int = 2) -> list[str]:
    """n случайных примеров вида '/ask TICKER вопрос' со случайными тикерами."""
    questions = random.sample(EXAMPLE_QUESTIONS, k=min(n, len(EXAMPLE_QUESTIONS)))
    pool = tickers or ["SBER"]
    return [f"/ask {random.choice(pool)} {q}" for q in questions]


def build_ticker_keyboard(tickers: list[str], cap: int = 12,
                          with_all_button: bool = False) -> InlineKeyboardMarkup:
    """Сетка тикеров 4 в ряд, callback ask:<TICKER>. Тап — сразу разбор."""
    rows, row = [], []
    for t in tickers[:cap]:
        row.append(InlineKeyboardButton(text=t, callback_data=f"ask:{t}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if with_all_button:
        rows.append([InlineKeyboardButton(text="📜 Все бумаги", callback_data="ask_all")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _guest_over_limit(deps: Deps, user_id: int) -> bool:
    owner_id = await fetch_owner_id(deps.session_factory)
    return user_id != owner_id and not deps.ask_limiter.allow(user_id)


async def build_position_note(deps: Deps, ticker: str) -> str | None:
    """Блок о реальной позиции владельца. None при сбое (не блокируем разбор)."""
    try:
        snap = await deps.broker.get_portfolio()
    except Exception as exc:
        log.warning("position_note_failed", error=str(exc))
        return None
    pos = next((p for p in snap.positions if p.ticker == ticker), None)
    if pos is None:
        return "Позиция: у пользователя НЕТ этой бумаги в портфеле."
    weight = (pos.quantity * pos.current_price / snap.total_value * 100).quantize(Decimal("0.1")) \
        if snap.total_value else Decimal("0")
    return (f"Позиция: {pos.quantity} шт по {pos.avg_price} ₽ "
            f"(P&L {pos.pnl_pct:+}%), вес {weight}% портфеля.")


async def _analyze_and_edit(progress: Message, deps: Deps, instrument: Instrument,
                            question: str | None, asked_by: int) -> None:
    """Общее ядро /ask: контекст → аналитик → запись вызова → рендер."""
    try:
        candles = await deps.broker.get_daily_candles(instrument.figi)
        tech = compute_tech_summary(candles)
        since = datetime.now(tz=timezone.utc) - timedelta(days=3)
        async with deps.session_factory() as session:
            news = await get_news_for_tickers(session, [instrument.ticker], since=since)
            prev = await get_last_call(session, instrument.ticker)
        owner_id = await fetch_owner_id(deps.session_factory)
        position_note = await build_position_note(deps, instrument.ticker) \
            if asked_by == owner_id else None
        report = await run_analyst(deps.llm, instrument.ticker, tech, news,
                                   question, position_note)
    except Exception as exc:
        log.error("ask_failed", ticker=instrument.ticker, error=str(exc))
        await progress.edit_text(
            f"⚠️ Не смог разобрать {instrument.ticker} — сбой данных или AI. "
            f"Попробуй ещё раз: <code>/ask {instrument.ticker}</code>"
        )
        return

    try:  # запись вызова не должна ронять ответ пользователю
        async with deps.session_factory() as session:
            await save_call(session, asked_by=asked_by, ticker=instrument.ticker,
                            figi=instrument.figi, source="ask", question=question,
                            stance=report.stance, confidence=report.confidence,
                            summary=report.summary,
                            price_at_call=tech.last_close if tech else None,
                            news_urls=[n.url for n in news])
            await session.commit()
    except Exception as exc:
        log.error("save_call_failed", ticker=instrument.ticker, error=str(exc))

    now = datetime.now(tz=timezone.utc)
    prev_note = format_prev_call_note(prev.stance, prev.confidence, prev.created_at,
                                      report.stance, now) if prev else None
    low_data = tech is None or not news
    await progress.edit_text(
        format_analyst_report(report, low_data=low_data, sources=news or None,
                              prev_note=prev_note)
    )


@router.message(Command("ask"))
async def cmd_ask(message: Message, command: CommandObject, deps: Deps) -> None:
    if not command.args:
        await show_ticker_picker(message, deps)
        return
    parts = command.args.split(maxsplit=1)
    instrument = deps.universe.resolve(parts[0])
    if instrument is None:
        await message.answer(f"Не знаю бумагу «{parts[0]}». {USAGE}")
        return
    if await _guest_over_limit(deps, message.from_user.id):
        await message.answer(LIMIT_REACHED.format(limit=deps.ask_limiter.limit))
        return
    question = parts[1] if len(parts) > 1 else None
    progress = await message.answer(f"🤖 Анализирую {instrument.ticker}…")
    await _analyze_and_edit(progress, deps, instrument, question,
                            asked_by=message.from_user.id)


@router.message(F.text == "💡 Спросить")
async def btn_ask(message: Message, deps: Deps) -> None:
    await show_ticker_picker(message, deps)


async def show_ticker_picker(message: Message, deps: Deps) -> None:
    """Владельцу — тикеры его портфеля, гостям — популярные из IMOEX."""
    tickers = [t for t in POPULAR_TICKERS if deps.universe.get(t)]
    owner_id = await fetch_owner_id(deps.session_factory)
    if message.from_user.id == owner_id:
        try:
            snap = await deps.broker.get_portfolio()
            portfolio_tickers = [p.ticker for p in snap.positions
                                 if deps.universe.get(p.ticker)]
            if portfolio_tickers:
                tickers = portfolio_tickers
        except Exception as exc:
            log.warning("ticker_picker_portfolio_failed", error=str(exc))
    examples = "\n".join(f"<code>{e}</code>" for e in pick_examples(tickers))
    await message.answer(
        f"💡 Тапни бумагу — сделаю разбор.\n\nИли задай свой вопрос, например:\n{examples}",
        reply_markup=build_ticker_keyboard(tickers, with_all_button=True),
    )


@router.callback_query(F.data == "ask_all")
async def cb_show_all(callback: CallbackQuery, deps: Deps) -> None:
    tickers = sorted(deps.universe.tickers())
    await callback.message.edit_text(
        f"💡 Все бумаги universe ({len(tickers)}) — тапни для разбора:",
        reply_markup=build_ticker_keyboard(tickers, cap=len(tickers)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("askq:"))  # старые сообщения с пресетами
@router.callback_query(F.data.startswith("ask:"))
async def cb_run_ask(callback: CallbackQuery, deps: Deps) -> None:
    ticker = callback.data.split(":")[1]
    await callback.answer()
    instrument = deps.universe.resolve(ticker)
    if instrument is None:
        await callback.message.edit_text(f"Не знаю бумагу «{ticker}». {USAGE}")
        return
    if await _guest_over_limit(deps, callback.from_user.id):
        await callback.message.edit_text(LIMIT_REACHED.format(limit=deps.ask_limiter.limit))
        return
    await callback.message.edit_text(f"🤖 Анализирую {instrument.ticker}…")
    await _analyze_and_edit(callback.message, deps, instrument, None,
                            asked_by=callback.from_user.id)
