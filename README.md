# KonturSMM Telegram Bot

KonturSMM is an AI manager for a Telegram channel. It keeps a channel profile,
creates versioned drafts, publishes only after approval, schedules posts and
shows results based on actions that actually happened inside the bot.

## Main flow

1. A user can send up to five posts and receive the first analysis for free.
2. The result is delivered immediately; subscribing to KonturSMM is not required.
3. An optional trial is unlocked after membership verification, connecting an
   own channel and completing its short profile.
4. The user explicitly starts a 24-hour trial with five successful AI actions.
5. Generated content is saved as a draft and can be edited, regenerated,
   published immediately or scheduled.
6. Paid packages add their configured limits. Failed AI calls return a reserved
   action automatically.

The permanent reply menu has five sections: My channel, Create, Plan, Analysis
and Results. Admins also see the Admin button.

## AI providers

Text requests use `GEMINI_TEXT_MODEL` through the Google OpenAI-compatible
endpoint first. If Gemini is unavailable or its quota is exhausted, the same
request is retried through `OPENAI_TEXT_MODEL` at Polza.ai. The system prompt in
`services/prompt_templates.py` is unchanged.

Successful requests write a server log with `provider=gemini` or
`provider=polza`. Generation history also stores the selected provider in
`metadata_json`. Images and transcription remain on Polza.ai.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

On Windows use `.venv\Scripts\activate` instead of the `source` command.

Required settings:

- `KONTUR_BOT_TOKEN`
- `OPENAI_API_KEY` (Polza fallback, images and transcription)
- `KONTUR_GEMINI_API_KEY` or `GEMINI_API_KEY`
- `KONTUR_CHANNEL_ID` and `KONTUR_CHANNEL_LINK`
- `ADMIN_IDS`

`DATABASE_PATH` defaults to `data/bot.sqlite3`. Schema changes are additive and
run during startup. Existing users, balances, payments, analyses and generation
history are preserved.

## Telegram channel connection

The user selects a channel using Telegram's native channel picker. The bot then
checks that:

- the selected chat is a channel;
- the user is its owner or administrator;
- the bot is an administrator with permission to post messages.

Telegram Bot API cannot download arbitrary history from a channel. KonturSMM
therefore learns from 3-5 posts supplied during setup and from posts received or
published after connection. Automatic competitor monitoring stays disabled by
default; manual topic interception is available.

## Trial and limits

The defaults are:

```text
TRIAL_DURATION_HOURS=24
TRIAL_GENERATION_LIMIT=5
```

AI usage is reserved atomically before a request and committed only after a
successful result. A provider error refunds it. Admin and manually granted
unlimited access are handled separately from tariff counters.

## Robokassa

Set `PAYMENT_ENABLED=true`, `APP_BASE_URL`, merchant credentials and matching
hash algorithms. In the Robokassa merchant settings configure:

```text
ResultURL:  https://your-domain.example/payments/robokassa/result
SuccessURL: https://your-domain.example/payments/robokassa/success
FailURL:    https://your-domain.example/payments/robokassa/fail
ResultURL method: POST
```

The ResultURL handler verifies the signature and amount before activating a
tariff. Invoice creation checks `isSuccess`, status refresh understands the
current `invoiceInformation` format, and payment callbacks are restricted to the
owner of the payment.

Health check: `GET /healthz`.

## Background jobs

When publishing is enabled, the scheduler starts with the bot, atomically claims
due jobs and retries failures. Schedule rows and drafts are persistent, so a bot
restart does not erase queued posts. Stale usage reservations and interrupted
publication claims are recovered at startup.

## Tests

```bash
python -m unittest discover -v
```

The test suite covers schema initialization, absence of an automatic fake trial,
trial reservation/refund, expired paid limits, draft versions, atomic schedule
claiming and Robokassa response/signature parsing.

## Admin commands

- `/admin`, `/users`, `/user @username`, `/events @username`, `/activity`
- `/funnel`, `/orders`
- `/grant_tariff @username start`
- `/grant_access @username 30`, `/revoke_access @username`
- `/set_limits @username posts_left 10`
- `/premium_requests`, `/reply_premium 1 text`
- `/reset_free_analysis @username`
- `/broadcast Text`
