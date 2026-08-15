from __future__ import annotations

import hashlib
import json
import unittest

from config import Settings
from services.robokassa_service import RobokassaService


class RobokassaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            robokassa_password_2='password2',
            robokassa_result_hash_alg='SHA256',
        )
        self.service = RobokassaService(self.settings)

    def test_create_invoice_application_error_is_rejected(self) -> None:
        raw = json.dumps({'isSuccess': False, 'message': 'bad request'})
        with self.assertRaisesRegex(RuntimeError, 'bad request'):
            self.service._parse_create_invoice_response(raw, 1)

    def test_invoice_information_response_is_parsed(self) -> None:
        raw = json.dumps({
            'isSuccess': True,
            'invoiceInformation': {'invId': 42, 'invoiceStatus': 'Paid'},
        })
        result = self.service._parse_invoice_info_response(raw, 42)
        self.assertEqual(result['status'], 'paid')

    def test_result_signature_uses_configured_algorithm(self) -> None:
        base = '390.00:7:password2:Shp_order_id=7'
        signature = hashlib.sha256(base.encode('utf-8')).hexdigest()
        self.assertTrue(
            self.service.verify_result_signature('390.00', '7', signature, {'Shp_order_id': '7'})
        )
