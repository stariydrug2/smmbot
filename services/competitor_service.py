from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp
from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError
from bs4 import BeautifulSoup

from config import Settings
from database.product_repository import ProductRepository
from database.queries import QueryService
from keyboards.product import (
    access_required_keyboard,
    competitor_alert_keyboard,
    competitor_digest_keyboard,
    draft_actions_keyboard,
)
from services.content_service import ContentService
from services.publishing_service import PublishingService
from services.usage_service import AccessRequiredError, UsageService
from utils.helpers import escape_html, render_model_text

logger = logging.getLogger(__name__)


class CompetitorFeedError(RuntimeError):
    pass


@dataclass(slots=True)
class PublicChannelPost:
    external_id: str
    url: str
    text: str
    views: int
    reactions: int
    published_at: str | None


@dataclass(slots=True)
class PublicChannelSnapshot:
    username: str
    title: str
    posts: list[PublicChannelPost]


@dataclass(slots=True)
class SyncSummary:
    sources_checked: int = 0
    new_posts: int = 0
    strong_posts: int = 0
    seeded_posts: int = 0
    errors: int = 0

    def add(self, other: SyncSummary) -> None:
        self.sources_checked += other.sources_checked
        self.new_posts += other.new_posts
        self.strong_posts += other.strong_posts
        self.seeded_posts += other.seeded_posts
        self.errors += other.errors


class TelegramPublicFeedClient:
    USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{4,64}$')

    def __init__(self, timeout_seconds: int) -> None:
        self.timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._session: aiohttp.ClientSession | None = None

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch(self, username: str) -> PublicChannelSnapshot:
        if not self.USERNAME_RE.fullmatch(username):
            raise CompetitorFeedError('Некорректное имя Telegram-канала.')
        session = await self._get_session()
        url = f'https://t.me/s/{username}'
        try:
            async with session.get(url, allow_redirects=True) as response:
                if response.status == 429:
                    raise CompetitorFeedError('Telegram временно ограничил проверки. Попробуем позже.')
                if response.status >= 400:
                    raise CompetitorFeedError(f'Публичная страница канала недоступна: HTTP {response.status}.')
                body = await response.content.read(2_000_001)
                if len(body) > 2_000_000:
                    raise CompetitorFeedError('Страница канала слишком большая для безопасной обработки.')
                html = body.decode(response.charset or 'utf-8', errors='replace')
        except asyncio.TimeoutError as exc:
            raise CompetitorFeedError('Telegram не ответил вовремя. Повторите проверку позже.') from exc
        except aiohttp.ClientError as exc:
            raise CompetitorFeedError('Не удалось открыть публичную страницу Telegram.') from exc
        return self.parse(username, html)

    async def _get_session(self) -> aiohttp.ClientSession:
        if not self._session or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    'User-Agent': 'KonturSMM/1.0 (+public Telegram channel monitoring)',
                    'Accept-Language': 'ru,en;q=0.8',
                },
            )
        return self._session

    @classmethod
    def parse(cls, username: str, html: str) -> PublicChannelSnapshot:
        soup = BeautifulSoup(html, 'html.parser')
        title_node = soup.select_one('.tgme_channel_info_header_title')
        title = title_node.get_text(' ', strip=True) if title_node else ''
        if not title:
            meta = soup.select_one('meta[property="og:title"]')
            title = str(meta.get('content') or '').strip() if meta else ''

        posts: list[PublicChannelPost] = []
        for node in soup.select('.tgme_widget_message[data-post]'):
            data_post = str(node.get('data-post') or '')
            source_name, separator, external_id = data_post.rpartition('/')
            if not separator or not external_id.isdigit():
                continue
            text_node = node.select_one('.tgme_widget_message_text')
            text = text_node.get_text('\n', strip=True) if text_node else ''
            views_node = node.select_one('.tgme_widget_message_views')
            views = cls.parse_metric(views_node.get_text(' ', strip=True) if views_node else '')
            reactions = sum(
                cls.parse_metric(item.get_text(' ', strip=True))
                for item in node.select(
                    '.tgme_reaction_value, .tgme_widget_message_reaction_count, '
                    '.tgme_widget_message_reactions .counter_value'
                )
            )
            date_link = node.select_one('a.tgme_widget_message_date')
            post_url = str(date_link.get('href') or '') if date_link else ''
            if not post_url:
                post_url = f'https://t.me/{source_name or username}/{external_id}'
            time_node = node.select_one('time[datetime]')
            published_at = str(time_node.get('datetime') or '') if time_node else ''
            if not text and not views and not published_at:
                continue
            posts.append(
                PublicChannelPost(
                    external_id=external_id,
                    url=post_url,
                    text=text,
                    views=views,
                    reactions=reactions,
                    published_at=published_at or None,
                )
            )

        if not soup.select_one('.tgme_channel_info') and not posts:
            raise CompetitorFeedError(
                'Канал не найден или у него нет доступной публичной страницы. Поддерживаются только открытые каналы.'
            )
        return PublicChannelSnapshot(username=username, title=title or f'@{username}', posts=posts)

    @staticmethod
    def parse_metric(value: str) -> int:
        clean = value.strip().upper().replace('\xa0', '').replace(' ', '').replace(',', '.')
        match = re.search(r'(\d+(?:\.\d+)?)\s*([KКMМ]?)', clean)
        if not match:
            return 0
        number = float(match.group(1))
        multiplier = {'K': 1_000, 'К': 1_000, 'M': 1_000_000, 'М': 1_000_000}.get(match.group(2), 1)
        return max(0, int(round(number * multiplier)))


class CompetitorMonitoringService:
    def __init__(
        self,
        repository: ProductRepository,
        queries: QueryService,
        content_service: ContentService,
        usage_service: UsageService,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.queries = queries
        self.content_service = content_service
        self.usage_service = usage_service
        self.settings = settings
        self.feed = TelegramPublicFeedClient(settings.competitor_http_timeout_seconds)
        self._pulse_locks: dict[int, asyncio.Lock] = {}

    async def close(self) -> None:
        await self.feed.close()

    @staticmethod
    def normalize_source(raw: str) -> str:
        value = raw.strip()
        if value.startswith('@'):
            username = value[1:]
        else:
            parsed = urlparse(value if '://' in value else f'https://t.me/{value}')
            if parsed.netloc.lower() not in {'t.me', 'telegram.me', 'www.t.me', 'www.telegram.me'}:
                raise CompetitorFeedError('Нужна ссылка t.me или имя канала вида @channel.')
            parts = [part for part in parsed.path.split('/') if part]
            if parts and parts[0].lower() == 's':
                parts = parts[1:]
            username = parts[0] if parts else ''
        if not TelegramPublicFeedClient.USERNAME_RE.fullmatch(username):
            raise CompetitorFeedError('Не похоже на публичный Telegram-канал. Пример: https://t.me/channel.')
        return username

    async def register_source(self, user_id: int, raw: str) -> tuple[dict, int]:
        username = self.normalize_source(raw)
        sources = await self.repository.list_competitor_sources(user_id)
        duplicate = next((item for item in sources if str(item.get('username') or '').lower() == username.lower()), None)
        if not duplicate and len(sources) >= self.settings.competitor_max_sources:
            raise CompetitorFeedError(f'Можно отслеживать не больше {self.settings.competitor_max_sources} каналов.')
        snapshot = await self.feed.fetch(username)
        source = await self.repository.add_competitor_source(
            user_id,
            username,
            f'https://t.me/{username}',
            snapshot.title,
        )
        summary = await self._ingest_source(source, snapshot, bot=None, allow_notifications=False)
        return source, summary.seeded_posts + summary.new_posts

    async def sync_all(self, bot: Bot) -> SyncSummary:
        sources = await self.repository.list_all_active_competitor_sources()
        grouped: dict[str, list[dict]] = {}
        for source in sources:
            grouped.setdefault(str(source['username']).lower(), []).append(source)
        total = SyncSummary()
        for username, related in grouped.items():
            try:
                snapshot = await self.feed.fetch(username)
            except CompetitorFeedError as exc:
                for source in related:
                    await self.repository.mark_competitor_source_checked(int(source['id']), error=str(exc))
                total.errors += len(related)
                continue
            for source in related:
                total.add(await self._ingest_source(source, snapshot, bot=bot, allow_notifications=True))
        return total

    async def sync_user(self, bot: Bot, user_id: int) -> SyncSummary:
        sources = await self.repository.list_competitor_sources(user_id)
        total = SyncSummary()
        for source in sources:
            username = str(source.get('username') or '')
            try:
                snapshot = await self.feed.fetch(username)
                total.add(await self._ingest_source(source, snapshot, bot=bot, allow_notifications=True))
            except CompetitorFeedError as exc:
                await self.repository.mark_competitor_source_checked(int(source['id']), error=str(exc))
                total.errors += 1
        return total

    async def _ingest_source(
        self,
        source: dict,
        snapshot: PublicChannelSnapshot,
        *,
        bot: Bot | None,
        allow_notifications: bool,
    ) -> SyncSummary:
        source_id = int(source['id'])
        initial_sync = not bool(source.get('initialized_at'))
        new_rows: list[dict] = []
        became_strong_rows: list[dict] = []
        strong_alert_rows: list[dict] = []
        all_rows: list[dict] = []

        for post in sorted(snapshot.posts, key=lambda item: int(item.external_id)):
            row, is_new = await self.repository.upsert_competitor_post(
                source_id,
                post.external_id,
                post.url,
                post.text,
                post.views,
                post.reactions,
                post.published_at,
            )
            prior_views = await self.repository.list_prior_competitor_views(source_id, post.external_id)
            score: float | None = None
            strong = False
            if len(prior_views) >= 5:
                baseline = float(median(prior_views))
                if baseline > 0:
                    score = post.views / baseline
                    strong = post.views >= max(
                        self.settings.competitor_strong_min_views,
                        math.ceil(baseline * self.settings.competitor_strong_multiplier),
                    )
            row, became_strong = await self.repository.update_competitor_post_strength(
                int(row['id']), score, strong
            )
            all_rows.append(row)
            if is_new:
                new_rows.append(row)
            if became_strong:
                became_strong_rows.append(row)
            if row.get('is_strong') and not row.get('notified_strong_at'):
                strong_alert_rows.append(row)

        last_seen = max((post.external_id for post in snapshot.posts), key=int, default=None)
        await self.repository.mark_competitor_source_checked(
            source_id,
            last_seen_post=last_seen,
            title=snapshot.title,
            initialized=True,
        )

        if initial_sync:
            for row in new_rows:
                await self.repository.mark_competitor_post_notified(int(row['id']), 'new')
            for row in all_rows:
                if row.get('is_strong'):
                    await self.repository.mark_competitor_post_notified(int(row['id']), 'strong')
            return SyncSummary(sources_checked=1, seeded_posts=len(new_rows))

        summary = SyncSummary(
            sources_checked=1,
            new_posts=len(new_rows),
            strong_posts=len(became_strong_rows),
        )
        if bot and allow_notifications:
            fresh_source = await self.repository.get_competitor_source(source_id) or source
            await self._notify_updates(bot, fresh_source, new_rows, strong_alert_rows)
        return summary

    async def _notify_updates(
        self,
        bot: Bot,
        source: dict,
        new_rows: list[dict],
        became_strong_rows: list[dict],
    ) -> None:
        settings = await self.repository.get_competitor_settings(int(source['user_id']))
        mode = str(settings.get('notify_mode') or 'strong')
        strong_ids = {int(row['id']) for row in became_strong_rows}

        if mode == 'off':
            for row in new_rows:
                await self.repository.mark_competitor_post_notified(int(row['id']), 'new')
            for row in became_strong_rows:
                await self.repository.mark_competitor_post_notified(int(row['id']), 'strong')
            return

        alerts: list[tuple[dict, bool]] = []
        if mode == 'all':
            alerts.extend((row, int(row['id']) in strong_ids) for row in new_rows)
        alerts.extend(
            (row, True)
            for row in became_strong_rows
            if not (mode == 'all' and any(int(item['id']) == int(row['id']) for item in new_rows))
        )

        sent_ids: set[int] = set()
        for row, strong in alerts[:5]:
            delivered = await self._send_post_alert(bot, source, row, strong)
            post_id = int(row['id'])
            if delivered:
                sent_ids.add(post_id)
                await self.repository.mark_competitor_post_notified(post_id, 'new')
                if strong:
                    await self.repository.mark_competitor_post_notified(post_id, 'strong')

        for row in new_rows:
            if int(row['id']) not in sent_ids:
                await self.repository.mark_competitor_post_notified(int(row['id']), 'new')
        for row in became_strong_rows:
            if int(row['id']) not in sent_ids and mode == 'off':
                await self.repository.mark_competitor_post_notified(int(row['id']), 'strong')

        if len(alerts) > 5:
            user = await self.queries.get_user_by_id(int(source['user_id']))
            if user:
                try:
                    await bot.send_message(
                        int(user['telegram_id']),
                        f'Ещё публикаций в радаре: <b>{len(alerts) - 5}</b>. Они войдут в недельный Пульс ниши.',
                    )
                except Exception:
                    logger.exception('Failed to send competitor alert summary to user_id=%s', source['user_id'])

    async def _send_post_alert(self, bot: Bot, source: dict, post: dict, strong: bool) -> bool:
        user = await self.queries.get_user_by_id(int(source['user_id']))
        if not user:
            return False
        source_name = source.get('title') or f"@{source.get('username')}"
        preview = str(post.get('content_text') or 'Публикация без текста')[:600]
        views = self.format_metric(int(post.get('views') or 0))
        score = float(post.get('strength_score') or 0)
        if strong:
            heading = '🔥 <b>Радар: сильный пост</b>'
            metric = f'Просмотры: <b>{views}</b> · примерно в <b>{score:.1f}×</b> выше обычного уровня'
        else:
            heading = '👀 <b>Новый пост у источника</b>'
            metric = f'Просмотры сейчас: <b>{views}</b>'
        try:
            await bot.send_message(
                int(user['telegram_id']),
                f'{heading}\n\n<b>{escape_html(str(source_name))}</b>\n{metric}\n\n{escape_html(preview)}',
                reply_markup=competitor_alert_keyboard(int(post['id']), str(post['post_url'])),
            )
            await self.repository.log_activity(
                'competitor_alert_sent',
                user_id=int(user['id']),
                telegram_id=int(user['telegram_id']),
                username=user.get('username'),
                full_name=user.get('full_name'),
                payload={'post_id': int(post['id']), 'strong': strong},
            )
            return True
        except TelegramForbiddenError:
            return False
        except Exception:
            logger.exception('Failed competitor alert user_id=%s post_id=%s', user['id'], post['id'])
            return False

    async def build_pulse(self, user_id: int) -> str:
        lock = self._pulse_locks.setdefault(user_id, asyncio.Lock())
        async with lock:
            posts = await self._recent_posts(user_id)
            if not posts:
                raise ValueError('За последние 7 дней у источников пока нет доступных публикаций.')
            post_ids = '|'.join(str(post['id']) for post in sorted(posts, key=lambda item: int(item['id'])))
            cache_key = hashlib.sha256(post_ids.encode('utf-8')).hexdigest()
            cached = await self.repository.get_competitor_report(user_id, 'pulse', cache_key)
            if cached:
                return cached
            result = await self.content_service.competitor_pulse(user_id, posts)
            await self.repository.save_competitor_report(user_id, 'pulse', cache_key, result)
            return result

    async def build_weekly_plan(self, user_id: int) -> dict:
        posts = await self._recent_posts(user_id)
        if not posts:
            raise ValueError('За последние 7 дней пока нет материалов для контент-плана.')
        reservation = await self.usage_service.reserve(user_id, 'content_plan')
        if not reservation:
            raise AccessRequiredError('Закончился лимит контент-планов.')
        try:
            result = await self.content_service.competitor_content_plan(user_id, posts)
            channel = await self.repository.get_active_channel(user_id)
            source_text = '\n'.join(str(post.get('post_url') or '') for post in posts[:20])
            draft = await self.repository.create_draft(
                user_id=user_id,
                channel_id=int(channel['id']) if channel else None,
                source_type='competitor_weekly',
                source_text=source_text,
                content_text=result,
                ai_mode='content_plan',
            )
        except Exception:
            await self.usage_service.refund(reservation)
            raise
        await self.usage_service.commit(reservation)
        user = await self.queries.get_user_by_id(user_id)
        if user:
            await self.repository.log_activity(
                'proactive_plan_created',
                user_id=user_id,
                telegram_id=int(user['telegram_id']),
                username=user.get('username'),
                full_name=user.get('full_name'),
                payload={'draft_id': int(draft['id']), 'access_source': reservation.source},
            )
        return draft

    async def run_loop(self, bot: Bot) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                if self.settings.feature_competitor_monitoring:
                    summary = await self.sync_all(bot)
                    logger.info(
                        'Competitor sync: sources=%s new=%s strong=%s errors=%s',
                        summary.sources_checked,
                        summary.new_posts,
                        summary.strong_posts,
                        summary.errors,
                    )
                await self._run_weekly_tasks(bot)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception('Competitor monitoring loop failed')
            await asyncio.sleep(self.settings.competitor_check_interval_seconds)

    async def _run_weekly_tasks(self, bot: Bot) -> None:
        now = datetime.now(timezone.utc)
        for user in await self.repository.list_competitor_users():
            user_id = int(user['user_id'])
            due, week_key = self._weekly_due(now, str(user.get('timezone') or self.settings.default_channel_timezone))
            if not due:
                continue
            monitor_settings = await self.repository.get_competitor_settings(user_id)
            telegram_id = int(user['telegram_id'])

            if bool(monitor_settings.get('pulse_enabled')) and monitor_settings.get('last_pulse_week') != week_key:
                try:
                    pulse = await self.build_pulse(user_id)
                except ValueError:
                    await self.repository.update_competitor_settings(user_id, last_pulse_week=week_key)
                except Exception:
                    logger.exception('Weekly competitor pulse failed user_id=%s', user_id)
                else:
                    await self.repository.update_competitor_settings(user_id, last_pulse_week=week_key)
                    await self._deliver_text(
                        bot,
                        telegram_id,
                        '<b>📡 Пульс ниши за 7 дней</b>',
                        pulse,
                        competitor_digest_keyboard(),
                    )

            if (
                self.settings.feature_proactive
                and bool(monitor_settings.get('weekly_plan_enabled'))
                and monitor_settings.get('last_plan_week') != week_key
            ):
                try:
                    draft = await self.build_weekly_plan(user_id)
                except AccessRequiredError:
                    await self.repository.update_competitor_settings(user_id, last_plan_week=week_key)
                    try:
                        await bot.send_message(
                            telegram_id,
                            '<b>Недельный план не создан.</b> Закончился лимит контент-планов.',
                            reply_markup=access_required_keyboard(),
                        )
                    except Exception:
                        logger.exception('Failed to send weekly plan limit notice user_id=%s', user_id)
                except ValueError:
                    await self.repository.update_competitor_settings(user_id, last_plan_week=week_key)
                except Exception:
                    logger.exception('Proactive competitor plan failed user_id=%s', user_id)
                else:
                    await self.repository.update_competitor_settings(user_id, last_plan_week=week_key)
                    await self._deliver_text(
                        bot,
                        telegram_id,
                        '<b>🗓 Контент-план по сигналам ниши</b>',
                        str(draft['content_text']),
                        draft_actions_keyboard(int(draft['id'])),
                    )

    def _weekly_due(self, now: datetime, timezone_name: str) -> tuple[bool, str]:
        try:
            local_now = now.astimezone(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            local_now = now.astimezone(ZoneInfo(self.settings.default_channel_timezone))
        week_start = (local_now - timedelta(days=local_now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        due_at = week_start + timedelta(
            days=self.settings.competitor_weekly_weekday,
            hours=self.settings.competitor_weekly_hour,
        )
        iso = local_now.isocalendar()
        return local_now >= due_at, f'{iso.year}-W{iso.week:02d}'

    async def _recent_posts(self, user_id: int) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        return await self.repository.list_competitor_posts(user_id, since=since, limit=60)

    async def _deliver_text(
        self,
        bot: Bot,
        telegram_id: int,
        heading: str,
        text: str,
        reply_markup: object | None,
    ) -> None:
        rendered = render_model_text(text)
        chunks = PublishingService._split_text(rendered, limit=3700)
        for index, chunk in enumerate(chunks):
            prefix = f'{heading}\n\n' if index == 0 else ''
            await bot.send_message(
                telegram_id,
                prefix + chunk,
                reply_markup=reply_markup if index == len(chunks) - 1 else None,
            )

    @staticmethod
    def format_metric(value: int) -> str:
        if value >= 1_000_000:
            return f'{value / 1_000_000:.1f} млн'
        if value >= 1_000:
            return f'{value / 1_000:.1f} тыс.'
        return str(value)
