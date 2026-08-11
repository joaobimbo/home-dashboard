import unittest
from types import SimpleNamespace
from unittest import mock

from modules.agent.bot import TelegramAgent


class TelegramAccessTests(unittest.TestCase):
    def setUp(self):
        self.agent = TelegramAgent.__new__(TelegramAgent)
        self.agent.allowed_chat_ids = frozenset({-1001})

    def test_allows_only_configured_groups(self):
        group = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001, type="supergroup"))
        other = SimpleNamespace(effective_chat=SimpleNamespace(id=-2002, type="supergroup"))
        direct = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001, type="private"))
        self.assertTrue(self.agent._allowed(group))
        self.assertFalse(self.agent._allowed(other))
        self.assertFalse(self.agent._allowed(direct))


class TelegramDebugTests(unittest.IsolatedAsyncioTestCase):
    async def test_debug_reports_authorization_and_dashboard_catalog(self):
        agent = TelegramAgent.__new__(TelegramAgent)
        agent.allowed_chat_ids = frozenset({-1001})
        agent.provider_name = "openai"
        agent.provider_model = "test-model"
        agent._engine_thread = mock.Mock()
        agent._engine_thread.is_alive.return_value = True
        agent.store = mock.Mock()
        agent.store.list_rules.return_value = [{"enabled": True}]
        agent.client = mock.Mock()
        agent.client.catalog.return_value = [
            {"kind": "shelly", "room": "Escritorio"},
            {"kind": "daikin", "room": "Escritorio"},
        ]
        message = SimpleNamespace(reply_text=mock.AsyncMock())
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        )

        with mock.patch(
            "modules.agent.bot.asyncio.to_thread",
            new=mock.AsyncMock(return_value=agent.client.catalog.return_value),
        ):
            await agent.debug_command(update, None)

        reply = message.reply_text.await_args.args[0]
        self.assertIn("authorized supergroup -1001", reply)
        self.assertIn("1 Shelly, 1 AC", reply)
        self.assertIn("Escritorio", reply)

    def test_progress_text_describes_dispatch_stage(self):
        text = TelegramAgent._progress_text(
            {"kind": "direct_actions", "actions": [{}, {}]}
        )
        self.assertIn("Sending 2 action(s)", text)


class TelegramRuleMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = TelegramAgent.__new__(TelegramAgent)
        self.agent.allowed_chat_ids = frozenset({-1001})
        self.agent.store = mock.Mock()
        self.agent.store.list_rules.return_value = [
            {"id": "enabled01", "name": "Enabled rule", "enabled": True},
            {"id": "disabled1", "name": "Disabled rule", "enabled": False},
        ]

    def test_enable_menu_only_lists_disabled_rules(self):
        text, keyboard = self.agent._build_rule_menu("enable")
        self.assertIn("enable", text)
        buttons = [row[0] for row in keyboard.inline_keyboard]
        self.assertEqual([button.text for button in buttons], ["▶️ Disabled rule"])
        self.assertEqual(buttons[0].callback_data, "agent:select:enable:disabled1")

    def test_disable_menu_only_lists_enabled_rules(self):
        _text, keyboard = self.agent._build_rule_menu("disable")
        buttons = [row[0] for row in keyboard.inline_keyboard]
        self.assertEqual([button.text for button in buttons], ["⏸ Enabled rule"])

    async def test_enable_selection_updates_rule_without_copying_id(self):
        rule = {"id": "disabled1", "name": "Disabled rule", "enabled": False}
        self.agent.store.get_rule.return_value = rule
        self.agent.store.set_enabled.return_value = {**rule, "enabled": True}
        query = SimpleNamespace(
            data="agent:select:enable:disabled1",
            answer=mock.AsyncMock(),
            edit_message_text=mock.AsyncMock(),
        )
        update = SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=42),
        )

        with mock.patch(
            "modules.agent.bot.asyncio.to_thread",
            new=mock.AsyncMock(return_value={**rule, "enabled": True}),
        ):
            await self.agent.callback(update, None)

        query.answer.assert_awaited_once()
        self.assertIn("enabled", query.edit_message_text.await_args.args[0])

    def test_relative_rule_enable_message_explains_timer_restart(self):
        message = self.agent._format_enabled_result(
            {
                "name": "Light pulse",
                "trigger": {"source": "schedule", "operator": "after"},
            },
            True,
        )
        self.assertIn("countdown restarted", message)


if __name__ == "__main__":
    unittest.main()
