import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import main


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {"MEMORY_DB_PATH": os.path.join(self.temp_dir.name, "memory.sqlite3")},
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    def test_history_is_separate_per_user_and_limited(self):
        for index in range(10):
            main.save_exchange("user-a", f"question-{index}", f"answer-{index}")
        main.save_exchange("user-b", "private question", "private answer")

        history = main.load_history("user-a")
        self.assertEqual(len(history), main.MAX_HISTORY_MESSAGES)
        self.assertEqual(history[0], {"role": "user", "content": "question-2"})
        self.assertEqual(history[-1], {"role": "assistant", "content": "answer-9"})
        self.assertEqual(len(main.load_history("user-b")), 2)
        self.assertNotIn("private question", str(history))

    def test_clear_history_removes_only_selected_user(self):
        main.save_exchange("user-a", "hello", "hi")
        main.save_exchange("user-b", "hello", "hey")

        main.clear_history("user-a")

        self.assertEqual(main.load_history("user-a"), [])
        self.assertEqual(len(main.load_history("user-b")), 2)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env = patch.dict(
            os.environ,
            {"MEMORY_DB_PATH": os.path.join(self.temp_dir.name, "memory.sqlite3")},
        )
        self.env.start()
        self.message = SimpleNamespace(text="hello", replies=[])

        async def reply_text(text):
            self.message.replies.append(text)

        self.message.reply_text = reply_text
        self.update = SimpleNamespace(
            effective_message=self.message,
            effective_user=SimpleNamespace(id=123),
        )
        self.context = SimpleNamespace(user_data={})

    def tearDown(self):
        self.env.stop()
        self.temp_dir.cleanup()

    async def test_successful_message_is_saved_and_replied(self):
        with patch("main.ask_ollama", return_value="Hello there."):
            await main.handle_message(self.update, self.context)

        self.assertEqual(self.message.replies, ["Hello there."])
        self.assertEqual(
            main.load_history("123"),
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "Hello there."},
            ],
        )

    async def test_ai_error_does_not_save_failed_exchange(self):
        with patch("main.ask_ollama", side_effect=RuntimeError("offline")):
            await main.handle_message(self.update, self.context)

        self.assertEqual(main.load_history("123"), [])
        self.assertEqual(len(self.message.replies), 1)
        self.assertIn("AI server", self.message.replies[0])


if __name__ == "__main__":
    unittest.main()
