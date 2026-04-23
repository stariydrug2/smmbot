from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from config import Settings

logger = logging.getLogger(__name__)


class RobokassaService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_invoice(
        self,
        inv_id: int,
        amount: float,
        description: str,
        user_fields: dict[str, str],
        item_name: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            'MerchantLogin': self.settings.robokassa_merchant_login,
            'InvoiceType': 'OneTime',
            'Culture': self.settings.robokassa_culture,
            'InvId': inv_id,
            'OutSum': float(amount),
            'Description': description,
            'MerchantComments': description,
            'UserFields': user_fields,
            'InvoiceItems': [
                {
                    'Name': item_name,
                    'Quantity': 1,
                    'Cost': float(amount),
                    'Tax': self.settings.robokassa_tax,
                    'PaymentMethod': self.settings.robokassa_payment_method,
                    'PaymentObject': self.settings.robokassa_payment_object,
                }
            ],
        }
        if self.settings.robokassa_success_url:
            payload['SuccessUrl2Data'] = {
                'Url': self.settings.robokassa_success_url,
                'Method': self.settings.robokassa_success_method,
            }
        if self.settings.robokassa_fail_url:
            payload['FailUrl2Data'] = {
                'Url': self.settings.robokassa_fail_url,
                'Method': self.settings.robokassa_fail_method,
            }
        token = self._build_jwt_token(payload)
        raw = await self._post_token(self.settings.robokassa_create_invoice_url, token)
        return self._parse_create_invoice_response(raw, inv_id)

    async def get_invoice_status(self, inv_id: int) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        payload = {
            'MerchantLogin': self.settings.robokassa_merchant_login,
            'CurrentPage': 1,
            'PageSize': 50,
            'InvoiceStatuses': ['Paid', 'Expired', 'Notpaid'],
            'Keywords': str(inv_id),
            'DateFrom': (now - timedelta(days=30)).isoformat(),
            'DateTo': (now + timedelta(days=1)).isoformat(),
            'IsAscending': False,
            'InvoiceTypes': ['OneTime'],
        }
        token = self._build_jwt_token(payload)
        raw = await self._post_token(self.settings.robokassa_invoice_info_url, token)
        return self._parse_invoice_info_response(raw, inv_id)

    def verify_result_signature(self, out_sum: str, inv_id: str, signature_value: str, shp_fields: dict[str, str]) -> bool:
        base_parts = [out_sum, inv_id, self.settings.robokassa_password_2]
        base_parts.extend(self._format_shp_parts(shp_fields))
        base_string = ':'.join(base_parts)
        digest = hashlib.md5(base_string.encode('utf-8')).hexdigest().upper()
        return digest == signature_value.upper()

    def _build_jwt_token(self, payload: dict[str, Any]) -> str:
        header = {'typ': 'JWT', 'alg': self.settings.robokassa_jwt_alg}
        header_b64 = self._b64url(json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        payload_b64 = self._b64url(json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
        signing_input = f'{header_b64}.{payload_b64}'
        signature = self._sign(signing_input)
        return f'{signing_input}.{signature}'

    async def _post_token(self, url: str, token: str) -> str:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=40)) as session:
            async with session.post(url, data=f'"{token}"', headers={'Content-Type': 'application/json; charset=utf-8'}) as response:
                text = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f'Ошибка Robokassa HTTP {response.status}: {text}')
                return text.strip()

    def _sign(self, signing_input: str) -> str:
        algorithm = self.settings.robokassa_jwt_alg.upper()
        digestmod = {
            'MD5': hashlib.md5,
            'RIPEMD160': hashlib.new,
            'SHA1': hashlib.sha1,
            'HS1': hashlib.sha1,
            'SHA256': hashlib.sha256,
            'HS256': hashlib.sha256,
            'SHA384': hashlib.sha384,
            'HS384': hashlib.sha384,
            'SHA512': hashlib.sha512,
            'HS512': hashlib.sha512,
        }.get(algorithm)
        key = f'{self.settings.robokassa_merchant_login}:{self.settings.robokassa_password_1}'.encode('utf-8')
        if algorithm == 'RIPEMD160':
            digest = hmac.new(key, signing_input.encode('utf-8'), lambda: hashlib.new('ripemd160'))
        else:
            if digestmod is None:
                raise RuntimeError(f'Неподдерживаемый алгоритм подписи Robokassa: {algorithm}')
            digest = hmac.new(key, signing_input.encode('utf-8'), digestmod)
        return self._b64url(digest.digest())

    @staticmethod
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

    @staticmethod
    def _format_shp_parts(shp_fields: dict[str, str]) -> list[str]:
        parts: list[str] = []
        for key, value in sorted(shp_fields.items(), key=lambda item: item[0].lower()):
            parts.append(f'{key}={value}')
        return parts

    @staticmethod
    def _parse_create_invoice_response(raw: str, inv_id: int) -> dict[str, Any]:
        cleaned = raw.strip().strip('"')
        if cleaned.startswith('{') or cleaned.startswith('['):
            data = json.loads(cleaned)
            if isinstance(data, dict):
                payment_url = str(
                    data.get('invoiceUrl')
                    or data.get('url')
                    or data.get('paymentUrl')
                    or data.get('link')
                    or ''
                )
                return {
                    'invoice_id': inv_id,
                    'invoice_url': payment_url,
                    'provider_payload': data,
                    'provider_invoice_id': str(data.get('id') or data.get('encodedId') or inv_id),
                }
        return {
            'invoice_id': inv_id,
            'invoice_url': cleaned,
            'provider_payload': {'raw': raw},
            'provider_invoice_id': str(inv_id),
        }

    @staticmethod
    def _parse_invoice_info_response(raw: str, inv_id: int) -> dict[str, Any]:
        cleaned = raw.strip().strip('"')
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return {'status': 'unknown', 'raw': raw, 'invoice_id': inv_id}

        items: list[dict[str, Any]] = []
        if isinstance(data, list):
            items = [item for item in data if isinstance(item, dict)]
        elif isinstance(data, dict):
            if isinstance(data.get('items'), list):
                items = [item for item in data['items'] if isinstance(item, dict)]
            elif isinstance(data.get('data'), list):
                items = [item for item in data['data'] if isinstance(item, dict)]
            else:
                items = [data]

        target = None
        for item in items:
            item_inv = str(item.get('InvId') or item.get('invId') or item.get('invoiceId') or '')
            if item_inv == str(inv_id):
                target = item
                break
        if target is None and items:
            target = items[0]

        status_raw = str((target or {}).get('Status') or (target or {}).get('status') or '').lower()
        if 'paid' in status_raw:
            status = 'paid'
        elif 'expired' in status_raw:
            status = 'expired'
        elif 'notpaid' in status_raw or 'not_paid' in status_raw or 'created' in status_raw:
            status = 'pending'
        else:
            status = 'unknown'
        return {
            'status': status,
            'invoice_id': inv_id,
            'payload': target or data,
            'raw': data,
        }
