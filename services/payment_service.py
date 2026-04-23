from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from database.queries import QueryService
from services.robokassa_service import RobokassaService
from services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class PaymentService:
    def __init__(
        self,
        queries: QueryService,
        robokassa_service: RobokassaService,
        subscription_service: SubscriptionService,
    ) -> None:
        self.queries = queries
        self.robokassa_service = robokassa_service
        self.subscription_service = subscription_service

    async def create_payment_for_plan(self, user_id: int, plan_code: str) -> dict[str, Any]:
        plan = await self.queries.get_plan_by_code(plan_code)
        if not plan or not bool(plan.get('is_active')):
            raise RuntimeError('Тариф недоступен.')

        description = f"Подписка SMM Bot — {plan['title']}"
        payment_id = await self.queries.create_payment(
            user_id=user_id,
            plan_id=int(plan['id']),
            amount=float(plan['price_rub']),
            description=description,
            shp_payload={'plan_code': plan['code']},
        )
        shp_fields = {
            'Shp_payment_id': str(payment_id),
            'Shp_user_id': str(user_id),
            'Shp_plan_code': str(plan['code']),
        }
        invoice = await self.robokassa_service.create_invoice(
            inv_id=payment_id,
            amount=float(plan['price_rub']),
            description=description,
            user_fields=shp_fields,
            item_name=description,
        )
        await self.queries.update_payment(
            payment_id,
            invoice_id=int(invoice['invoice_id']),
            provider_invoice_id=str(invoice.get('provider_invoice_id') or payment_id),
            invoice_url=invoice.get('invoice_url'),
            payment_url=invoice.get('invoice_url'),
            provider_payload_json=self._dump(invoice.get('provider_payload') or {}),
            status='pending',
        )
        await self.queries.log_payment_event(payment_id, 'invoice_created', invoice.get('provider_payload') or {})
        result = await self.queries.get_payment(payment_id)
        if not result:
            raise RuntimeError('Не удалось сохранить платёж.')
        return result

    async def process_result_callback(self, payload: dict[str, Any]) -> tuple[bool, str]:
        out_sum = str(payload.get('OutSum', ''))
        inv_id = str(payload.get('InvId', ''))
        signature = str(payload.get('SignatureValue', ''))
        shp_fields = {key: str(value) for key, value in payload.items() if key.lower().startswith('shp_')}

        if not inv_id or not out_sum or not signature:
            return False, 'Missing payment fields'
        if not self.robokassa_service.verify_result_signature(out_sum, inv_id, signature, shp_fields):
            return False, 'Invalid signature'

        payment = await self.queries.get_payment_by_invoice_id(int(inv_id))
        if not payment:
            return False, 'Payment not found'

        if payment.get('status') != 'paid':
            await self.queries.update_payment(
                int(payment['id']),
                status='paid',
                paid_at=datetime.now(timezone.utc).isoformat(),
                provider_payload_json=self._dump(payload),
            )
            await self.subscription_service.activate_plan_from_payment(
                user_id=int(payment['user_id']),
                plan_id=int(payment['plan_id']),
                payment_id=int(payment['id']),
            )
            await self.queries.log_payment_event(int(payment['id']), 'result_url_paid', payload)
        return True, f'OK{inv_id}'

    async def refresh_payment_status(self, payment_id: int) -> dict[str, Any]:
        payment = await self.queries.get_payment(payment_id)
        if not payment:
            raise RuntimeError('Платёж не найден.')
        if payment.get('status') == 'paid':
            return payment
        invoice_id = int(payment.get('invoice_id') or payment['id'])
        status_info = await self.robokassa_service.get_invoice_status(invoice_id)
        await self.queries.log_payment_event(payment_id, 'manual_status_check', status_info)
        normalized_status = status_info.get('status', 'unknown')
        if normalized_status == 'paid':
            await self.queries.update_payment(
                payment_id,
                status='paid',
                paid_at=datetime.now(timezone.utc).isoformat(),
                provider_payload_json=self._dump(status_info.get('payload') or status_info),
            )
            await self.subscription_service.activate_plan_from_payment(
                user_id=int(payment['user_id']),
                plan_id=int(payment['plan_id']),
                payment_id=payment_id,
            )
        elif normalized_status == 'expired':
            await self.queries.update_payment(payment_id, status='expired', provider_payload_json=self._dump(status_info.get('payload') or status_info))
        elif normalized_status == 'pending':
            await self.queries.update_payment(payment_id, status='pending', provider_payload_json=self._dump(status_info.get('payload') or status_info))
        return await self.queries.get_payment(payment_id) or payment

    @staticmethod
    def _dump(value: dict[str, Any]) -> str:
        return json_dumps(value)


def json_dumps(value: dict[str, Any]) -> str:
    import json
    return json.dumps(value, ensure_ascii=False)
