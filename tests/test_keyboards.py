from __future__ import annotations

import unittest

from keyboards.reply import channel_connect_keyboard


class ChannelConnectKeyboardTests(unittest.TestCase):
    def test_requested_bot_rights_are_covered_by_user_rights(self) -> None:
        keyboard = channel_connect_keyboard()
        request = keyboard.keyboard[0][0].request_chat

        self.assertIsNotNone(request)
        self.assertIsNotNone(request.user_administrator_rights)
        self.assertIsNotNone(request.bot_administrator_rights)
        self.assertTrue(request.user_administrator_rights.can_promote_members)
        self.assertTrue(request.user_administrator_rights.can_post_messages)
        self.assertTrue(request.user_administrator_rights.can_edit_messages)
        self.assertTrue(request.bot_administrator_rights.can_post_messages)
        self.assertTrue(request.bot_administrator_rights.can_edit_messages)
        self.assertFalse(request.bot_administrator_rights.can_promote_members)


if __name__ == '__main__':
    unittest.main()
