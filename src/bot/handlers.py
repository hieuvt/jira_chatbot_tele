"""Đăng ký handler Telegram: chuyển Update -> MessageInput, gọi state machine, gửi phản hồi (ForceReply khi cần)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from types import SimpleNamespace
from typing import Any, Coroutine, TypeVar

from telegram import ForceReply, Message, ReplyParameters, Update, User
from telegram.constants import ChatAction
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.conversation.state_machine import (
    FileMeta,
    MessageInput,
    ReminderCandidate,
    build_filename,
    MULTI_MESSAGE_PREFIX,
)

HTML_OUTPUT_PREFIX = "__HTML__:"

_T = TypeVar("_T")


async def _typing_keepalive(*, bot: Any, chat_id: int, work: Coroutine[Any, Any, _T]) -> _T:
    """
    Gửi ChatAction.TYPING lặp lại trong lúc chờ `work` (Telegram chỉ giữ typing ~5s mỗi lần).
    """
    try:
        await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
    except TelegramError:
        pass

    stop = asyncio.Event()

    async def _tick_loop() -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=4.5)
            except asyncio.TimeoutError:
                pass
            if stop.is_set():
                break
            try:
                await bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
            except TelegramError:
                pass

    tick = asyncio.create_task(_tick_loop())
    try:
        return await work
    finally:
        stop.set()
        tick.cancel()
        try:
            await tick
        except asyncio.CancelledError:
            pass


def _telegram_username_or_none(user: User | None) -> str | None:
    """@username chuẩn hoá (lowercase) để tra/ghi users.json; None nếu user không có username."""
    if user is None:
        return None
    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip().lstrip("@").strip().lower() or None
    return None


def _normalize_username_str(raw: str | None) -> str | None:
    if raw is None or not str(raw).strip():
        return None
    return str(raw).strip().lstrip("@").strip().lower() or None


def _telegram_user_name_for_store(user: User) -> str:
    """Nhãn lưu `user_name` trong users.json: ưu tiên @username, rồi họ tên, cuối cùng là id."""
    username = getattr(user, "username", None)
    if isinstance(username, str) and username.strip():
        return username.strip().lstrip("@")
    parts: list[str] = []
    fn = getattr(user, "first_name", None)
    ln = getattr(user, "last_name", None)
    if isinstance(fn, str) and fn.strip():
        parts.append(fn.strip())
    if isinstance(ln, str) and ln.strip():
        parts.append(ln.strip())
    joined = " ".join(parts).strip()
    if joined:
        return joined
    return str(user.id)


def _telegram_display_name_only(user: User) -> str:
    """Họ tên hiển thị Telegram (first + last); rỗng nếu không có (contract Phase 4)."""
    parts: list[str] = []
    fn = getattr(user, "first_name", None)
    ln = getattr(user, "last_name", None)
    if isinstance(fn, str) and fn.strip():
        parts.append(fn.strip())
    if isinstance(ln, str) and ln.strip():
        parts.append(ln.strip())
    return " ".join(parts).strip()


def _extract_mention_user(message: Message) -> User | None:
    """Lấy User từ entity text_mention / mention có kèm object user."""
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user:
            return entity.user
        if entity.type == "mention" and entity.user:
            return entity.user
    return None


def _needs_user_reply(output: str) -> bool:
    """
    Trong group/supergroup, Privacy Mode có thể chặn tin thường — chỉ bật ForceReply khi
    bot đang hỏi input tự do (jira id, assignee, summary, mô tả, …).
    """
    if not output:
        return False

    markers = (
        "Vui lòng nhập jira_account_id",
        "Bạn chưa liên kết Jira",
        "Người này chưa liên kết Jira",
        "Chọn người được giao việc",
        "Nhập tiêu đề công việc",
        "Nhập mô tả công việc",
        "Bạn có muốn thêm file đính kèm",
        "Bạn có muốn thêm checklist",
        "Nhập số ngày cần hoàn thành",
        "Xác nhận tạo công việc",
        "Nhập số thứ tự của task bạn muốn báo hoàn thành",
        "Xác nhận báo hoàn thành issue",
    )
    return any(m in output for m in markers)


def _reply_params_to_user_message(message: Message) -> ReplyParameters:
    """Bot gửi tin trả lời đúng message user — cần cho ForceReply(selective=True) trong nhóm/forum."""
    mid = int(message.message_id)
    tid = getattr(message, "message_thread_id", None)
    if tid is not None:
        return ReplyParameters(message_id=mid, message_thread_id=tid)
    return ReplyParameters(message_id=mid)


def _reply_params_for_reminder(c: ReminderCandidate) -> ReplyParameters | None:
    if c.reply_to_message_id is None:
        return None
    mid = int(c.reply_to_message_id)
    if c.reply_thread_id is not None:
        return ReplyParameters(message_id=mid, message_thread_id=int(c.reply_thread_id))
    return ReplyParameters(message_id=mid)


def _build_reminder_callback(state_machine: Any):
    """Coroutine gọi định kỳ: gửi nhắc cho các phiên đủ điều kiện."""

    async def reminder_callback(context: ContextTypes.DEFAULT_TYPE) -> None:
        iter_fn = getattr(state_machine, "iter_reminder_candidates", None)
        mark_fn = getattr(state_machine, "mark_reminder_sent", None)
        if not callable(iter_fn) or not callable(mark_fn):
            return
        candidates = iter_fn(now=None)
        bot = context.application.bot
        for c in candidates:
            try:
                chat = await bot.get_chat(c.chat_id)
                chat_type = getattr(chat, "type", None)
            except TelegramError:
                chat_type = None
            reply_markup = (
                ForceReply(selective=True, input_field_placeholder="…")
                if chat_type in ("group", "supergroup", "private") and _needs_user_reply(c.text)
                else None
            )
            rparams = _reply_params_for_reminder(c)
            send_kw: dict[str, Any] = {
                "chat_id": c.chat_id,
                "text": c.text,
                "reply_markup": reply_markup,
                "parse_mode": "HTML" if c.is_html else None,
            }
            if rparams is not None:
                send_kw["reply_parameters"] = rparams
            try:
                await bot.send_message(**send_kw)
                mark_fn(chat_id=c.chat_id, user_id=c.user_id)
            except TelegramError:
                pass

    return reminder_callback


async def conversation_reminder_post_init(application: Application) -> None:
    """
    Khi không cài `python-telegram-bot[job-queue]`, `job_queue` là None — chạy vòng nhắc bằng asyncio.
    Phải đăng ký qua Application.builder().post_init(...), không gọi application.post_init(...) sau build
    (thuộc tính đó là callback hoặc None, không phải hàm đăng ký).
    """
    if application.job_queue is not None:
        return
    reminder_callback = application.bot_data.get("_reminder_callback")
    if not callable(reminder_callback):
        return

    async def loop() -> None:
        await asyncio.sleep(30.0)
        while True:
            await reminder_callback(SimpleNamespace(application=application))  # type: ignore[arg-type]
            await asyncio.sleep(60.0)

    application.create_task(loop())


def register_conversation_reminder_job(application: Application, state_machine: Any) -> None:
    """Gửi lại prompt đang chờ (giaoviec / giaochotoi / baoxong) sau reminder_after_minutes im lặng."""
    reminder_callback = _build_reminder_callback(state_machine)
    jq = application.job_queue
    if jq is not None:
        jq.run_repeating(reminder_callback, interval=60.0, first=30.0)
        return
    application.bot_data["_reminder_callback"] = reminder_callback


async def deliver_conversation_output(
    *,
    bot: object,
    chat_id: int,
    user_id: int,
    trigger_message: Message,
    output: str,
    chat_type: str | None,
    tpl_cancelled: str,
    force_reply_tracker: dict[tuple[int, int], int],
    state_machine: Any | None = None,
) -> None:
    """
    Gửi nội dung state machine ra chat.
    - Hủy (TPL_CANCELLED): gỡ reply_markup tin nhắn prompt trước (nếu có), rồi send_message.
    - Prompt cần gõ chữ trong nhóm: reply_text + ForceReply, lưu message_id để /huy gỡ markup.
    """
    key = (chat_id, user_id)
    # Khi state machine trả về MULTI_MESSAGE_PREFIX + JSON, handler sẽ
    # parse JSON và gửi tuần tự nhiều tin nhắn (parse_mode HTML).
    if output.startswith(MULTI_MESSAGE_PREFIX):
        raw = output[len(MULTI_MESSAGE_PREFIX) :]
        last_mid = force_reply_tracker.pop(key, None)
        if last_mid is not None:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=last_mid,
                    reply_markup=None,
                )
            except TelegramError:
                pass
        try:
            parsed = json.loads(raw)
            message_texts = parsed if isinstance(parsed, list) else [parsed]
            message_texts = [str(x) for x in message_texts]
        except Exception:
            message_texts = [raw]
        for text in message_texts:
            await bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML")
        return
    is_html_output = output.startswith(HTML_OUTPUT_PREFIX)
    clean_output = output[len(HTML_OUTPUT_PREFIX) :] if is_html_output else output

    if tpl_cancelled and clean_output.strip() == tpl_cancelled.strip():
        last_mid = force_reply_tracker.pop(key, None)
        if last_mid is not None:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=last_mid,
                    reply_markup=None,
                )
            except TelegramError:
                pass
        await bot.send_message(
            chat_id=chat_id,
            text=clean_output,
            parse_mode="HTML" if is_html_output else None,
        )
        return

    reply_markup = (
        ForceReply(selective=True, input_field_placeholder="…")
        if chat_type in ("group", "supergroup", "private") and _needs_user_reply(clean_output)
        else None
    )
    sent = await bot.send_message(
        chat_id=chat_id,
        text=clean_output,
        reply_markup=reply_markup,
        parse_mode="HTML" if is_html_output else None,
        reply_parameters=_reply_params_to_user_message(trigger_message),
    )
    if reply_markup is not None and sent and getattr(sent, "message_id", None) is not None:
        force_reply_tracker[key] = int(sent.message_id)
    if state_machine is not None:
        note = getattr(state_machine, "note_outbound_prompt", None)
        if callable(note):
            note(chat_id=chat_id, user_id=user_id, output=output)


async def _download_to_file_meta(message: Message, kind: str, context: ContextTypes.DEFAULT_TYPE) -> FileMeta | None:
    """Tải một loại media (document, photo, …) về bytes và gói thành FileMeta cho state machine."""
    tg_file = None
    mime_type: str | None = None
    filename: str | None = None
    if kind == "document" and message.document:
        tg_file = await context.bot.get_file(message.document.file_id)
        mime_type = message.document.mime_type
        filename = message.document.file_name
    elif kind == "photo" and message.photo:
        largest = message.photo[-1]
        tg_file = await context.bot.get_file(largest.file_id)
        mime_type = "image/jpeg"
        filename = None
    elif kind == "video" and message.video:
        tg_file = await context.bot.get_file(message.video.file_id)
        mime_type = message.video.mime_type
        filename = message.video.file_name
    elif kind == "audio" and message.audio:
        tg_file = await context.bot.get_file(message.audio.file_id)
        mime_type = message.audio.mime_type
        filename = message.audio.file_name
    elif kind == "voice" and message.voice:
        tg_file = await context.bot.get_file(message.voice.file_id)
        mime_type = message.voice.mime_type
        filename = None
    elif kind == "animation" and message.animation:
        tg_file = await context.bot.get_file(message.animation.file_id)
        mime_type = message.animation.mime_type
        filename = message.animation.file_name
    elif kind == "video_note" and message.video_note:
        tg_file = await context.bot.get_file(message.video_note.file_id)
        mime_type = "video/mp4"
        filename = None
    elif kind == "sticker" and message.sticker:
        tg_file = await context.bot.get_file(message.sticker.file_id)
        mime_type = "image/webp"
        filename = None
    if not tg_file:
        return None
    content = await tg_file.download_as_bytearray()
    now_ts = int(datetime.now(tz=timezone.utc).timestamp())
    final_name = filename or build_filename(kind=kind, mime_type=mime_type, timestamp=now_ts)
    return FileMeta(
        filename=final_name,
        size=len(content),
        telegram_file_id=tg_file.file_id,
        telegram_file_unique_id=tg_file.file_unique_id,
        kind=kind,
        mime_type=mime_type,
        content_bytes=bytes(content),
    )


def _extract_mentioned_user_id(message: Message) -> int | None:
    """Lấy telegram user id từ mention / text_mention (nếu client gắn user)."""
    entities = message.entities or []
    for entity in entities:
        if entity.type == "text_mention" and entity.user:
            return entity.user.id
        if entity.type == "mention" and entity.user:
            # Một số client gắn `user` cho mention — xử lý best-effort
            return entity.user.id
    return None


def _extract_mentioned_user_username(message: Message) -> str | None:
    """
    Trích username từ entity mention / text_mention.
    - text_mention: có thể có user nhưng thiếu username.
    - mention: thường chỉ có chuỗi @username trong text.
    """
    entities = message.entities or []
    text = message.text or message.caption or ""
    for entity in entities:
        if entity.type == "text_mention" and entity.user:
            username = getattr(entity.user, "username", None)
            if isinstance(username, str) and username.strip():
                return username.strip()
        if entity.type == "mention":
            # Parse @username từ text theo offset/length của entity
            offset = int(getattr(entity, "offset", 0))
            length = int(getattr(entity, "length", 0))
            if length <= 0 or offset < 0 or offset + length > len(text):
                continue
            raw = text[offset : offset + length].strip()
            if raw:
                return raw.lstrip("@").strip()
    return None


def register_handlers(
    application: Application,
    state_machine: object,
    *,
    tpl_cancelled: str,
) -> None:
    """Đăng ký MessageHandler toàn bộ tin nhắn; build MessageInput và gọi state_machine.handle_message."""
    application.bot_data["state_machine"] = state_machine
    force_reply_tracker: dict[tuple[int, int], int] = {}

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_chat or not update.effective_user:
            return

        tg_message = update.message
        chat_id = update.effective_chat.id

        async def _work() -> str:
            attachments: list[FileMeta] = []
            for kind in ("document", "photo", "video", "audio", "voice", "animation", "video_note", "sticker"):
                meta = await _download_to_file_meta(tg_message, kind, context)
                if meta:
                    attachments.append(meta)

            eu = update.effective_user
            sender_user_name = _telegram_user_name_for_store(eu)
            sender_telegram_display_name = _telegram_display_name_only(eu)
            sender_username = _telegram_username_or_none(eu)

            reply_fu = tg_message.reply_to_message.from_user if tg_message.reply_to_message else None
            reply_target_user_name = _telegram_user_name_for_store(reply_fu) if reply_fu else None
            reply_target_telegram_display_name = _telegram_display_name_only(reply_fu) if reply_fu else None
            reply_to_username_norm = _normalize_username_str(
                tg_message.reply_to_message.from_user.username
                if tg_message.reply_to_message and tg_message.reply_to_message.from_user
                else None
            )

            mu = _extract_mention_user(tg_message)
            if mu:
                mentioned_user_name = _telegram_user_name_for_store(mu)
                mentioned_telegram_display_name = _telegram_display_name_only(mu)
                mentioned_username = _telegram_username_or_none(mu) or _normalize_username_str(
                    _extract_mentioned_user_username(tg_message)
                )
            else:
                un = _extract_mentioned_user_username(tg_message)
                mentioned_user_name = un if un else None
                mentioned_telegram_display_name = "" if un else None
                mentioned_username = _normalize_username_str(un)

            message_input = MessageInput(
                chat_id=update.effective_chat.id,
                user_id=update.effective_user.id,
                bot_user_id=getattr(context.bot, "id", None),
                telegram_message_id=int(tg_message.message_id),
                message_thread_id=getattr(tg_message, "message_thread_id", None),
                text=tg_message.text or tg_message.caption,
                reply_to_user_id=(
                    tg_message.reply_to_message.from_user.id if tg_message.reply_to_message else None
                ),
                reply_to_username=reply_to_username_norm,
                mentioned_user_id=_extract_mentioned_user_id(tg_message),
                mentioned_username=mentioned_username,
                sender_username=sender_username,
                sender_user_name=sender_user_name,
                sender_telegram_display_name=sender_telegram_display_name,
                reply_target_user_name=reply_target_user_name,
                reply_target_telegram_display_name=reply_target_telegram_display_name,
                mentioned_user_name=mentioned_user_name,
                mentioned_telegram_display_name=mentioned_telegram_display_name or "",
                attachments=attachments,
            )
            return await asyncio.to_thread(state_machine.handle_message, message_input)

        output = await _typing_keepalive(bot=context.bot, chat_id=chat_id, work=_work())
        chat_type = getattr(update.effective_chat, "type", None)
        await deliver_conversation_output(
            bot=context.bot,
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            trigger_message=tg_message,
            output=output,
            chat_type=chat_type,
            tpl_cancelled=tpl_cancelled,
            force_reply_tracker=force_reply_tracker,
            state_machine=state_machine,
        )

    application.add_handler(MessageHandler(filters.ALL, on_message))
    register_conversation_reminder_job(application, state_machine)

