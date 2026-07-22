import time
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from roaring_kittens.ai.usage_context import use_budget_mode, use_user
from roaring_kittens.alerts import send_alert
from roaring_kittens.budget import budget_state
from roaring_kittens.committee.impact import ImpactCheck, decide_impact_action, run_impact_check
from roaring_kittens.committee.render import chunk_lines, format_council_verdict
from roaring_kittens.committee.runner import run_council_flow
from roaring_kittens.committee.thesis_check import decide_validation_action, run_thesis_check
from roaring_kittens.db.alerts_buffer import delete_alerts, fetch_alerts, list_buffered_chats
from roaring_kittens.db.calls import council_ran_recently
from roaring_kittens.db.theses import close_thesis, get_active_theses, mark_thesis_weakened
from roaring_kittens.db.users import list_active_users
from roaring_kittens.db.watchlist import list_watchlist
from roaring_kittens.deps import Deps
from roaring_kittens.digest.morning import run_morning_digest
from roaring_kittens.news.matching import match_tickers
from roaring_kittens.news.repository import save_news
from roaring_kittens.news.rss import fetch_feed
from roaring_kittens.news.sources import SOURCES
from roaring_kittens.positions_sync import sync_positions
from roaring_kittens.price_watch import price_watch_job
from roaring_kittens.reflection import weekly_reflection_job
from roaring_kittens.scoring import score_due_calls
from roaring_kittens.telegram.formatting import esc
from roaring_kittens.users_service import get_cached_portfolio, get_user_broker

log = structlog.get_logger()

# (user_id, 'YYYY-MM'): 80/100%-уведомление шлём раз в месяц; после рестарта
# может повториться единожды — приемлемо (in-memory)
_budget_notified: set[tuple[int, str]] = set()

BUDGET_SKIPPED_NOTE = " (бюджет исчерпан — комитет не собирал, /budget)"


async def _budget_mode_for(deps, bot, uid: int) -> tuple[str, bool]:
    """(budget_mode для LLM, heavy_ok). Считается раз на юзера на цикл джобы.
    На первом переходе из 'ok' за месяц шлёт юзеру одно уведомление."""
    state, _, _ = await budget_state(deps, uid)
    month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
    if state != "ok" and (uid, month) not in _budget_notified:
        _budget_notified.add((uid, month))
        text = ("🟡 80% месячного AI-бюджета — до 1-го числа перехожу на "
                "эконом-модели. /budget — детали."
                if state == "econom" else
                "🔴 Месячный AI-бюджет исчерпан — тяжёлые разборы (комитет) "
                "заблокированы до 1-го числа. /budget — детали.")
        try:
            await send_alert(deps, bot, uid, text)
        except Exception as exc:
            log.warning("budget_notify_failed", user=uid, error=str(exc))
    return ("econom" if state in ("econom", "blocked") else "ok",
            state != "blocked")


async def poll_news(deps: Deps, bot=None) -> None:
    alias_map = deps.universe.alias_map()
    fresh_items = []  # ТОЛЬКО реально вставленные новости — точность вместо окна
    for source_id, url in SOURCES:
        items = await fetch_feed(url, source=source_id)
        for item in items:
            item.tickers = match_tickers(f"{item.headline} {item.body or ''}", alias_map)
        relevant = [i for i in items if i.tickers]
        async with deps.session_factory() as session:
            inserted_urls = await save_news(session, relevant)
            await session.commit()
        fresh_items += [i for i in relevant if i.url in set(inserted_urls)]
        log.info("news_polled", source=source_id, fetched=len(items),
                 relevant=len(relevant), inserted=len(inserted_urls))
    log.info("news_poll_done", inserted=len(fresh_items))
    if bot is not None and fresh_items:
        handled: dict[int, set[str]] = {}
        try:
            handled = await validate_theses(deps, bot, fresh_items)
        except Exception as exc:
            log.error("validate_theses_failed", error=str(exc))
        try:
            await impact_scan(deps, bot, fresh_items, skip_by_user=handled)
        except Exception as exc:
            log.error("impact_scan_failed", error=str(exc))


GENERIC_NEWS_TICKER_CAP = 3   # пост с 4+ тикерами = обзор рынка, не событие компании
WEAKENED_COOLDOWN = timedelta(hours=24)


async def validate_theses(deps, bot, fresh_items: list) -> dict[int, set[str]]:
    """Проверка активных тезисов ВСЕХ юзеров ТОЛЬКО реально новыми новостями.

    Возвращает owner_id -> тикеры, которые валидатор взял на себя
    (impact_scan пропускает их ТОЛЬКО для этого юзера)."""
    if not fresh_items:
        return {}
    by_ticker: dict[str, list] = {}
    for item in fresh_items:
        # обзорные посты («Индекс МБ сегодня»), матчащиеся на пол-универсума,
        # не считаем событием конкретной компании — тезисы ими не проверяем
        if len(item.tickers) > GENERIC_NEWS_TICKER_CAP:
            continue
        for t in item.tickers:
            by_ticker.setdefault(t, []).append(item)
    async with deps.session_factory() as session:
        theses_to_check = [t for t in await get_active_theses(session)
                           if t.ticker in by_ticker]
    # handled = только (юзер, тикер), где валидатор реально ДЕЙСТВОВАЛ: сбой проверки
    # или still_valid не должны глушить impact_scan (там может быть HIGH-событие)
    handled: dict[int, set[str]] = {}
    budget_cache: dict[int, tuple[str, bool]] = {}
    for thesis in theses_to_check:
        owner_id = thesis.owner_id
        if owner_id is None:
            # до-миграционный тезис: содержимое НЕ роутим никому — только лог
            log.error("thesis_without_owner", thesis_id=str(thesis.id),
                      ticker=thesis.ticker)
            continue
        news = by_ticker[thesis.ticker]
        async with deps.session_factory() as session:
            recent = await council_ran_recently(session, thesis.ticker, hours=24)
        if owner_id not in budget_cache:
            budget_cache[owner_id] = await _budget_mode_for(deps, bot, owner_id)
        mode, heavy_ok = budget_cache[owner_id]
        try:
            with use_user(owner_id), use_budget_mode(mode):
                check = await run_thesis_check(deps.llm, thesis, news)
        except Exception as exc:
            log.error("thesis_check_failed", ticker=thesis.ticker, error=str(exc))
            continue
        action = decide_validation_action(check.status, recent)
        if action == "council" and not heavy_ok:
            action = "notify"  # blocked: слом сообщаем (critical), комитет не жжём
        if action == "nothing":
            continue
        if action == "notify":
            handled.setdefault(owner_id, set()).add(thesis.ticker)
            text = (f"⚠️ Тезис по <b>{thesis.ticker}</b> "
                    f"{'СЛОМАН' if check.status == 'invalidated' else 'ослаблен'}: "
                    f"{esc(check.reasoning_short)}\nТезис: {esc(thesis.thesis)}")
            if check.status == "weakened":
                last = thesis.last_weakened_at
                if last and datetime.now(tz=timezone.utc) - last < WEAKENED_COOLDOWN:
                    log.info("weakened_suppressed_cooldown", ticker=thesis.ticker)
                    continue
                async with deps.session_factory() as session:
                    await mark_thesis_weakened(session, thesis.id)
                    await session.commit()
                await send_alert(deps, bot, owner_id, text)
            else:  # СЛОМАН — critical: сквозь тихие часы и троттлинг
                if not heavy_ok:
                    text += BUDGET_SKIPPED_NOTE
                await send_alert(deps, bot, owner_id, text, critical=True)
            continue
        # action == "council": автозапуск комитета (слом тезиса = critical)
        handled.setdefault(owner_id, set()).add(thesis.ticker)
        await send_alert(
            deps, bot, owner_id,
            f"🚨 Новости ломают тезис по <b>{thesis.ticker}</b>: "
            f"{esc(check.reasoning_short)}\nСобираю комитет…", critical=True)
        instrument = deps.universe.resolve(thesis.ticker)
        if instrument is None:
            continue
        try:
            broker = await get_user_broker(deps, owner_id)
            with use_user(owner_id), use_budget_mode(mode):
                outcome = await run_council_flow(deps, instrument, owner_id,
                                                 broker=broker)
        except Exception as exc:
            log.error("auto_council_failed", ticker=thesis.ticker, error=str(exc))
            continue
        async with deps.session_factory() as session:
            await close_thesis(session, thesis.id, status="invalidated",
                               realized_return_pct=None,
                               close_reason=f"новости: {check.reasoning_short}")
            await session.commit()
        # Комитет предложил замену старому тезису — даём принять кнопкой
        keyboard = None
        if outcome.run_id is not None:
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                             callback_data=f"proto:{outcome.run_id}")]]
            if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
                buttons.append([InlineKeyboardButton(
                    text="📌 Принять новый тезис",
                    callback_data=f"thesis_save:{outcome.run_id}")])
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        await send_alert(
            deps, bot, owner_id,
            format_council_verdict(instrument.ticker, outcome.state["views"],
                                   outcome.state["debate"], outcome.proposal,
                                   outcome.risk),
            critical=True, keyboard=keyboard)
    return handled


async def _collect_impact_interests(deps,
                                    skip_by_user: dict[int, set[str]]
                                    ) -> dict[int, set[str]]:
    """user -> тикеры интереса: (кэш-портфель ∪ его watchlist) − его тезисы − handled."""
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    interests: dict[int, set[str]] = {}
    for u in users:
        uid = u.telegram_id
        portfolio: set[str] = set()
        broker = await get_user_broker(deps, uid)
        if broker is not None:
            snap = await get_cached_portfolio(deps, uid, broker)
            if snap is not None:
                portfolio = {p.ticker for p in snap.positions}
        async with deps.session_factory() as session:
            watched = set(await list_watchlist(session, uid))
            thesis_tickers = {t.ticker
                              for t in await get_active_theses(session, owner_id=uid)}
        interest = (portfolio | watched) - thesis_tickers - skip_by_user.get(uid, set())
        if interest:
            interests[uid] = interest
    return interests


async def impact_scan(deps, bot, fresh_items: list,
                      skip_by_user: dict[int, set[str]]) -> None:
    """HIGH-impact реакция для тикеров портфеля/watchlist БЕЗ тезиса (те — у валидатора).

    Двухпроходный: классификация — ОДИН раз на тикер, системный кост (вне use_user);
    реакция — каждому заинтересованному юзеру под его бюджетом."""
    if not fresh_items:
        return
    by_ticker: dict[str, list] = {}
    for item in fresh_items:
        if len(item.tickers) > GENERIC_NEWS_TICKER_CAP:
            continue
        for t in item.tickers:
            by_ticker.setdefault(t, []).append(item)
    if not by_ticker:
        return
    interests = await _collect_impact_interests(deps, skip_by_user)
    if not interests:
        return
    union: set[str] = set().union(*interests.values())
    checked: dict[str, ImpactCheck] = {}
    for ticker in sorted(set(by_ticker) & union):   # ПРОХОД 1: система платит
        try:
            checked[ticker] = await run_impact_check(deps.llm, ticker,
                                                     by_ticker[ticker])
        except Exception as exc:
            log.error("impact_check_failed", ticker=ticker, error=str(exc))
    for uid, tickers in interests.items():          # ПРОХОД 2: per-user реакция
        mode, heavy_ok = await _budget_mode_for(deps, bot, uid)
        for ticker in sorted(tickers & set(checked)):
            try:
                with use_user(uid), use_budget_mode(mode):
                    await _react_for_user(deps, bot, uid, ticker, checked[ticker],
                                          by_ticker[ticker], heavy_ok=heavy_ok)
            except Exception as exc:
                log.error("impact_react_failed", user=uid, ticker=ticker,
                          error=str(exc))


async def _react_for_user(deps, bot, uid: int, ticker: str, check,
                          news: list, heavy_ok: bool) -> None:
    async with deps.session_factory() as session:
        recent = await council_ran_recently(session, ticker, hours=24)
    action = decide_impact_action(check.impact, recent)
    if action == "nothing":
        return
    headline = news[0].headline
    text = (f"⚡️ <b>{check.impact.upper()} — {ticker}</b>\n"
            f"{esc(headline)}\n{esc(check.reasoning_short)}")
    if action in ("council", "council_critical") and not heavy_ok:
        # бюджет исчерпан: честно говорим, почему без комитета
        action = "notify_critical" if action == "council_critical" else "notify"
        text += BUDGET_SKIPPED_NOTE
    elif action in ("notify", "notify_critical") and recent:
        # глобальный guard срезал комитет — подскажем, как получить свой разбор
        text += (f"\nКомитет по этой новости уже собирался — "
                 f"/council {ticker} для своего разбора.")
    if action == "notify":
        await send_alert(deps, bot, uid, text)
        return
    if action == "notify_critical":
        await send_alert(deps, bot, uid, text, critical=True)
        return
    critical = action == "council_critical"
    # В буфер уходит текст БЕЗ обещания комитета: ночью комитет не гоняем,
    # и утренний дамп не должен обещать то, чего не было. «Комитет совещается…»
    # шлём отдельным сообщением ТОЛЬКО когда алерт реально доставлен.
    status = await send_alert(deps, bot, uid, text, critical=critical)
    if status != "sent":
        return  # ночью HIGH буферится — утром юзер сам решит про комитет
    await bot.send_message(uid, f"🏛 {ticker}: комитет совещается…")
    instrument = deps.universe.resolve(ticker)
    if instrument is None:
        return
    try:
        broker = await get_user_broker(deps, uid)
        outcome = await run_council_flow(deps, instrument, uid, broker=broker)
    except Exception as exc:
        log.error("impact_council_failed", ticker=ticker, error=str(exc))
        return
    keyboard = None
    if outcome.run_id is not None:
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        buttons = [[InlineKeyboardButton(text="📜 Протокол",
                                         callback_data=f"proto:{outcome.run_id}")]]
        if outcome.risk.approved and outcome.proposal.action in ("buy", "hold"):
            buttons.append([InlineKeyboardButton(
                text="📌 Принять тезис",
                callback_data=f"thesis_save:{outcome.run_id}")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    # Вердикт — всегда critical: анонс уже ушёл, прогон уже оплачен; кнопки —
    # ТОЛЬКО инициатору (run.asked_by=uid, колбэки гейтятся по нему же).
    await send_alert(deps, bot, uid,
                     format_council_verdict(instrument.ticker, outcome.state["views"],
                                            outcome.state["debate"], outcome.proposal,
                                            outcome.risk),
                     critical=True, keyboard=keyboard)


async def _flush_buffer(deps, bot, chat_id: int, header: str) -> int:
    """At-least-once: fetch -> send -> delete. Сбой отправки НЕ теряет алерты."""
    async with deps.session_factory() as session:
        rows = await fetch_alerts(session, chat_id)
    if not rows:
        return 0
    lines = [header, ""]
    for _, payload in rows:  # тексты экранированы при создании — повторно не экранируем
        lines.append(payload)
        lines.append("")
    for chunk in chunk_lines(lines):
        await bot.send_message(chat_id, chunk)  # упадёт — алерты останутся в буфере
    async with deps.session_factory() as session:
        await delete_alerts(session, [rid for rid, _ in rows])
        await session.commit()
    return len(rows)


async def drain_pending_job(deps: Deps, bot) -> None:
    """Дневной дренаж затроттленных алертов — раз в час, чтобы они не ждали до 9:00.

    Дренируем ВСЕ чаты с непустым буфером (не только владельца): покрывает друзей
    и stranded-строки только что revoked-юзеров."""
    from roaring_kittens.alerts import _now_local, is_quiet_hours
    if is_quiet_hours(_now_local(deps)):
        return  # ночное — дождётся утреннего дайджеста
    async with deps.session_factory() as session:
        chats = await list_buffered_chats(session)
    for chat_id in chats:
        try:
            sent = await _flush_buffer(deps, bot, chat_id, "⏳ <b>Отложенные алерты:</b>")
            if sent:
                log.info("pending_alerts_flushed", chat=chat_id, count=sent)
        except Exception as exc:
            log.error("pending_flush_failed", chat=chat_id, error=str(exc))


async def morning_digest_job(deps: Deps, bot) -> None:
    """Утренний дайджест каждому активному юзеру с брокером; ночной буфер — всем."""
    async with deps.session_factory() as session:
        buffered = await list_buffered_chats(session)
    for chat_id in buffered:  # буфер дренируем даже юзерам без токена
        try:
            await _flush_buffer(deps, bot, chat_id, "🌙 <b>Ночью накопилось:</b>")
        except Exception as exc:  # буфер не должен ронять сам дайджест
            log.error("night_buffer_flush_failed", chat=chat_id, error=str(exc))
    async with deps.session_factory() as session:
        users = await list_active_users(session)
    if not users:
        log.warning("digest_skipped_no_users")
        return
    for u in users:
        broker = await get_user_broker(deps, u.telegram_id)
        if broker is None:
            continue
        started = time.monotonic()
        try:
            mode, heavy_ok = await _budget_mode_for(deps, bot, u.telegram_id)
            with use_user(u.telegram_id), use_budget_mode(mode):
                await run_morning_digest(deps, bot, u.telegram_id, broker=broker,
                                         allow_spotlight=heavy_ok)
        except Exception as exc:  # один юзер не роняет остальных
            log.error("digest_user_failed", user=u.telegram_id, error=str(exc))
        log.info("digest_user_done", user=u.telegram_id,
                 sec=round(time.monotonic() - started, 1))


def build_scheduler(deps: Deps, bot) -> AsyncIOScheduler:
    # misfire_grace_time: занятый процесс не должен молча пропускать cron-тики
    scheduler = AsyncIOScheduler(timezone=deps.settings.tz,
                                 job_defaults={"misfire_grace_time": 300})
    scheduler.add_job(poll_news, "interval", minutes=5, args=[deps, bot],
                      id="poll_news", max_instances=1, coalesce=True)
    scheduler.add_job(drain_pending_job, "cron", hour="9-21", minute=15,
                      args=[deps, bot],
                      id="drain_pending", max_instances=1, coalesce=True)
    scheduler.add_job(price_watch_job, "cron", day_of_week="mon-fri",
                      hour="10-18", minute="*/30", args=[deps, bot],
                      id="price_watch", max_instances=1, coalesce=True)
    scheduler.add_job(morning_digest_job, "cron", hour=9, minute=0,
                      args=[deps, bot],
                      id="morning_digest", max_instances=1, coalesce=True)
    scheduler.add_job(score_due_calls, "cron", hour=23, minute=45, args=[deps],
                      id="score_calls", max_instances=1, coalesce=True)
    scheduler.add_job(sync_positions, "cron", hour=8, minute=50, args=[deps, bot],
                      id="positions_sync", max_instances=1, coalesce=True)
    scheduler.add_job(weekly_reflection_job, "cron", day_of_week="sun",
                      hour=23, minute=0, args=[deps, bot],
                      id="weekly_reflection", max_instances=1, coalesce=True)
    return scheduler
