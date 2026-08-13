import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from modules.agent.bot import TelegramAgent


class TelegramAccessTests(unittest.TestCase):
    def setUp(self):
        self.agent = TelegramAgent.__new__(TelegramAgent)
        self.agent.allowed_chat_ids = frozenset({-1001})
        self.agent.max_message_age_seconds = 3600

    def test_allows_only_configured_groups(self):
        group = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001, type="supergroup"))
        other = SimpleNamespace(effective_chat=SimpleNamespace(id=-2002, type="supergroup"))
        direct = SimpleNamespace(effective_chat=SimpleNamespace(id=-1001, type="private"))
        self.assertTrue(self.agent._allowed(group))
        self.assertFalse(self.agent._allowed(other))
        self.assertFalse(self.agent._allowed(direct))

    def test_drops_messages_older_than_one_hour(self):
        def update_at(sent_at):
            return SimpleNamespace(
                callback_query=None,
                effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
                effective_user=SimpleNamespace(id=42),
                effective_message=SimpleNamespace(date=sent_at),
            )

        now = datetime.now(timezone.utc)
        self.assertTrue(self.agent._allowed(update_at(now - timedelta(minutes=59))))
        self.assertFalse(self.agent._allowed(update_at(now - timedelta(minutes=61))))

    def test_current_callback_on_old_message_is_allowed(self):
        update = SimpleNamespace(
            callback_query=SimpleNamespace(data="agent:noop:0"),
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=42),
            effective_message=SimpleNamespace(
                date=datetime.now(timezone.utc) - timedelta(days=2)
            ),
        )
        self.assertTrue(self.agent._allowed(update))


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

    def test_clock_rule_preview_shows_time_conditions_and_timezone(self):
        preview = self.agent._format_automation(
            {
                "name": "Morning blinds",
                "description": "Open every morning",
                "trigger": {
                    "source": "schedule",
                    "operator": "daily",
                    "at": "07:00",
                },
                "conditions": [
                    {
                        "source": "time",
                        "field": "local_time",
                        "operator": "gte",
                        "value": "07:00",
                    }
                ],
                "cancel_conditions": [],
                "repeat": "reusable",
                "overlap": "ignore",
                "steps": [
                    {
                        "kind": "action",
                        "action": {
                            "display_name": "Estores Quarto",
                            "operation": "cover",
                            "parameters": {"command": "open"},
                        },
                    }
                ],
            },
            "Europe/Lisbon",
        )

        self.assertIn("Trigger: every day at 07:00", preview)
        self.assertIn("Condition: local time is at or after 07:00", preview)
        self.assertIn("Time zone: Europe/Lisbon", preview)


class TelegramPowerMenuTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.agent = TelegramAgent.__new__(TelegramAgent)
        self.agent.allowed_chat_ids = frozenset({-1001})
        self.agent.max_message_age_seconds = 3600
        self.agent._pending = {}
        self.agent.store = mock.Mock()
        self.agent.client = mock.Mock()
        self.catalog = [
            {
                "token": "S1",
                "id": "office-light",
                "kind": "shelly",
                "component": "switch",
                "display_name": "Office light",
                "room": "Office",
                "capabilities": ["status", "power", "toggle"],
            },
            {
                "token": "A1",
                "id": "office-ac",
                "kind": "daikin",
                "component": "ac",
                "display_name": "Office AC",
                "room": "Office",
                "capabilities": ["status", "power", "ac_mode"],
            },
            {
                "token": "S2",
                "id": "office-cover",
                "kind": "shelly",
                "component": "cover",
                "display_name": "Office cover",
                "room": "Office",
                "capabilities": ["status", "cover", "position"],
            },
        ]
        self.snapshot = {
            "devices": {
                "office-light": {"ok": True, "state": "off"},
                "office-ac": {"ok": True, "power": True},
                "office-cover": {"ok": True, "state": "closed"},
            },
            "weather": None,
        }
        self.agent.client.catalog.return_value = self.catalog
        self.agent.client.snapshot.return_value = self.snapshot
        self.agent.client.execute.return_value = {"ok": True, "state": "on"}

    @staticmethod
    def update(message=None, query=None):
        return SimpleNamespace(
            callback_query=query,
            effective_chat=SimpleNamespace(id=-1001, type="supergroup"),
            effective_user=SimpleNamespace(id=42),
            effective_message=message,
        )

    def test_power_candidates_filter_by_live_state_and_capability(self):
        turn_on = self.agent._power_candidates(self.catalog, self.snapshot, "on")
        turn_off = self.agent._power_candidates(self.catalog, self.snapshot, "off")
        self.assertEqual([item["id"] for item in turn_on], ["office-light"])
        self.assertEqual([item["id"] for item in turn_off], ["office-ac"])

    async def test_on_menu_uses_bound_token_and_executes_rechecked_action(self):
        message = SimpleNamespace(reply_text=mock.AsyncMock())
        update = self.update(message=message)
        run_inline = mock.AsyncMock(side_effect=lambda function, *args: function(*args))
        with mock.patch("modules.agent.bot.asyncio.to_thread", new=run_inline):
            await self.agent._send_power_menu(update, "on")

            keyboard = message.reply_text.await_args.kwargs["reply_markup"]
            button = keyboard.inline_keyboard[0][0]
            self.assertIn("Office light", button.text)
            self.assertNotIn("office-light", button.callback_data)

            query = SimpleNamespace(
                data=button.callback_data,
                answer=mock.AsyncMock(),
                edit_message_text=mock.AsyncMock(),
            )
            callback_update = self.update(message=message, query=query)
            await self.agent.callback(callback_update, None)

        action = self.agent.client.execute.call_args.args[0]
        self.assertEqual(action["device_id"], "office-light")
        self.assertEqual(action["parameters"], {"state": "on"})
        self.assertIn("turned on", query.edit_message_text.await_args.args[0])

    async def test_exact_on_message_bypasses_provider(self):
        self.agent._consume_rate_limit = mock.Mock(return_value=True)
        self.agent._send_power_menu = mock.AsyncMock()
        message = SimpleNamespace(
            text="ON",
            date=datetime.now(timezone.utc),
            reply_text=mock.AsyncMock(),
        )
        update = self.update(message=message)

        await self.agent.natural_language(update, None)

        self.agent._send_power_menu.assert_awaited_once_with(update, "on")


if __name__ == "__main__":
    unittest.main()
