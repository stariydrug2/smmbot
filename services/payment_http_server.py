from __future__ import annotations

from html import escape
from typing import Any

from aiohttp import web

from services.payment_service import PaymentService


def create_payment_app(payment_service: PaymentService) -> web.Application:
    app = web.Application()
    app['payment_service'] = payment_service
    app.router.add_route('*', '/payments/robokassa/result', robokassa_result_handler)
    app.router.add_get('/payments/robokassa/success', robokassa_success_handler)
    app.router.add_get('/payments/robokassa/fail', robokassa_fail_handler)
    app.router.add_get('/healthz', healthcheck_handler)
    return app


async def robokassa_result_handler(request: web.Request) -> web.Response:
    payment_service: PaymentService = request.app['payment_service']
    if request.method == 'POST':
        data = await request.post()
        payload = dict(data)
    else:
        payload = dict(request.query)
    ok, message = await payment_service.process_result_callback(payload)
    return web.Response(text=message if ok else message, status=200 if ok else 400, content_type='text/plain')


async def robokassa_success_handler(request: web.Request) -> web.Response:
    inv_id = request.query.get('InvId', '—')
    body = f'''<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <title>Оплата принята</title>
  </head>
  <body style="font-family:Arial,sans-serif;padding:32px;max-width:720px;margin:0 auto;">
    <h1>Оплата принята</h1>
    <p>Счёт <b>{escape(inv_id)}</b> успешно оплачен.</p>
    <p>Вернитесь в Telegram-бота. Подписка активируется автоматически после обработки ResultURL. Если в профиле статус ещё не обновился, нажмите кнопку проверки статуса оплаты.</p>
  </body>
</html>'''
    return web.Response(text=body, content_type='text/html')


async def robokassa_fail_handler(request: web.Request) -> web.Response:
    inv_id = request.query.get('InvId', '—')
    body = f'''<!doctype html>
<html lang="ru">
  <head>
    <meta charset="utf-8">
    <title>Оплата не завершена</title>
  </head>
  <body style="font-family:Arial,sans-serif;padding:32px;max-width:720px;margin:0 auto;">
    <h1>Оплата не завершена</h1>
    <p>Счёт <b>{escape(inv_id)}</b> не был оплачен или был прерван.</p>
    <p>Вернитесь в Telegram-бота и создайте новый счёт или попробуйте снова.</p>
  </body>
</html>'''
    return web.Response(text=body, content_type='text/html')


async def healthcheck_handler(_: web.Request) -> web.Response:
    return web.json_response({'ok': True})
