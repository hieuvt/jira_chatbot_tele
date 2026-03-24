"""Verify cancel clears ForceReply markup and uses standalone send_message.

Usage:
  python scripts/phase3_handler_cancel_test.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.bot.handlers import deliver_conversation_output
from src.conversation.templates import load_template_bundle


def _check(condition: bool, label: str) -> int:
    if condition:
        print(f"[OK] {label}")
        return 0
    print(f"[FAIL] {label}")
    return 1


async def _run() -> int:
    failures = 0
    bundle = load_template_bundle(ROOT_DIR / "config" / "templates.json")
    tpl = bundle.bot_replies.get("TPL_CANCELLED", "Đã hủy giao việc.")

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_reply_markup = AsyncMock()
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    tracker0: dict[tuple[int, int], int] = {}
    await deliver_conversation_output(
        bot=bot,
        chat_id=42,
        user_id=1,
        trigger_message=msg,
        output=tpl,
        chat_type="supergroup",
        tpl_cancelled=tpl,
        force_reply_tracker=tracker0,
    )
    failures += _check(bot.send_message.await_count == 1, "cancel uses send_message once")
    failures += _check(bot.edit_message_reply_markup.await_count == 0, "cancel skips edit when no tracked prompt")
    failures += _check(msg.reply_text.await_count == 0, "cancel does not use reply_text")
    sm = bot.send_message.await_args.kwargs
    failures += _check(sm.get("chat_id") == 42 and sm.get("text") == tpl, "send_message chat_id and text")
    failures += _check("reply_markup" not in sm or sm.get("reply_markup") is None, "cancel has no reply_markup")

    bot_clear = MagicMock()
    bot_clear.send_message = AsyncMock()
    bot_clear.edit_message_reply_markup = AsyncMock()
    msg_clear = MagicMock()
    tracker_clear: dict[tuple[int, int], int] = {(42, 1): 555}
    await deliver_conversation_output(
        bot=bot_clear,
        chat_id=42,
        user_id=1,
        trigger_message=msg_clear,
        output=tpl,
        chat_type="supergroup",
        tpl_cancelled=tpl,
        force_reply_tracker=tracker_clear,
    )
    failures += _check(bot_clear.edit_message_reply_markup.await_count == 1, "cancel edits last ForceReply message")
    em = bot_clear.edit_message_reply_markup.await_args.kwargs
    failures += _check(
        em.get("chat_id") == 42 and em.get("message_id") == 555 and em.get("reply_markup") is None,
        "edit_message_reply_markup clears markup",
    )
    failures += _check((42, 1) not in tracker_clear, "tracker drops entry after cancel")

    bot2 = MagicMock()
    bot2.send_message = AsyncMock()
    bot2.edit_message_reply_markup = AsyncMock()
    msg2 = MagicMock()
    sent_prompt = MagicMock(message_id=321)
    msg2.reply_text = AsyncMock(return_value=sent_prompt)
    prompt = "Nhập tiêu đề công việc (summary)."
    tracker2: dict[tuple[int, int], int] = {}
    await deliver_conversation_output(
        bot=bot2,
        chat_id=99,
        user_id=2,
        trigger_message=msg2,
        output=prompt,
        chat_type="supergroup",
        tpl_cancelled=tpl,
        force_reply_tracker=tracker2,
    )
    failures += _check(bot2.send_message.await_count == 0, "prompt does not use send_message")
    failures += _check(msg2.reply_text.await_count == 1, "prompt uses reply_text")
    rm = msg2.reply_text.await_args.kwargs.get("reply_markup")
    failures += _check(rm is not None, "group prompt attaches ForceReply markup")
    failures += _check(tracker2.get((99, 2)) == 321, "tracker stores ForceReply message_id")

    return failures


def main() -> int:
    failures = asyncio.run(_run())
    if failures:
        print(f"HANDLER CANCEL TEST FAILED with {failures} issue(s)")
        return 1
    print("HANDLER CANCEL TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
