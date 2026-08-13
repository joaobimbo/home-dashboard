import json
import unittest
from types import SimpleNamespace
from unittest import mock

from modules.agent.providers import AnthropicProvider, GeminiProvider, OpenAIProvider


PAYLOAD = {
    "kind": "unsupported",
    "reply": "No",
    "question": None,
    "assumptions": [],
    "actions": [],
    "automation": None,
}


class ProviderTests(unittest.TestCase):
    def test_openai_uses_responses_structured_output(self):
        provider = OpenAIProvider("test", "test-model")
        provider.client.responses.create = mock.Mock(
            return_value=SimpleNamespace(output_text=json.dumps(PAYLOAD))
        )
        result = provider.interpret("hello", [], "safe-user")
        self.assertEqual(result["kind"], "unsupported")
        kwargs = provider.client.responses.create.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["safety_identifier"], "safe-user")
        self.assertEqual(kwargs["text"]["format"]["type"], "json_schema")
        self.assertIn("Current local date/time:", kwargs["input"])
        self.assertIn("Europe/Lisbon", kwargs["input"])

    def test_anthropic_uses_structured_output(self):
        provider = AnthropicProvider("test", "test-model")
        provider.client.messages.create = mock.Mock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(type="text", text=json.dumps(PAYLOAD))],
                stop_reason="end_turn",
            )
        )
        result = provider.interpret("hello", [], "ignored")
        self.assertEqual(result["kind"], "unsupported")
        kwargs = provider.client.messages.create.call_args.kwargs
        self.assertEqual(kwargs["output_config"]["format"]["type"], "json_schema")

    def test_gemini_uses_concise_device_and_function_contract(self):
        provider = GeminiProvider("test", "test-model")
        create = mock.Mock(return_value=SimpleNamespace(output_text=json.dumps(PAYLOAD)))
        provider.client = SimpleNamespace(interactions=SimpleNamespace(create=create))
        catalog = [
            {
                "token": "S1",
                "display_name": "Luz Escritorio",
                "other_names": ["office light"],
                "room": "Escritorio",
                "kind": "shelly",
                "component": "light",
                "capabilities": ["status", "power", "brightness"],
            }
        ]
        result = provider.interpret("turn it off", catalog, "ignored")
        self.assertEqual(result["kind"], "unsupported")
        kwargs = create.call_args.kwargs
        self.assertFalse(kwargs["store"])
        self.assertEqual(kwargs["response_format"]["mime_type"], "application/json")
        self.assertNotIn("schema", kwargs["response_format"])
        self.assertIn("Luz Escritorio", kwargs["input"])
        self.assertIn("power(device,state=on|off)", kwargs["input"])
        self.assertIn("operator=after", kwargs["input"])
        self.assertIn("Current local date/time:", kwargs["input"])
        self.assertIn("every day at 7am", kwargs["input"])
        self.assertIn("green is\n[0,255,0]", kwargs["input"])


if __name__ == "__main__":
    unittest.main()
