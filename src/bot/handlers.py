"""Telegram handlers for Phase 3 state-machine integration."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import ForceReply, Message, Update, User
from telegram.error import TelegramError
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.conversation.state_machine import FileMeta, MessageInput, build_filename


def _telegram_user_name_for_store(user: User) -> str:
    """Identifier-first label for users.json `user_name` (username, else name, else id)."""
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
    """Profile display name: first + last; empty if unset (per Phase 4 contract)."""
    parts: list[str] = []
    fn = getattr(user, "first_name", None)
    ln = getattr(user, "last_name", None)
    if isinstance(fn, str) and fn.strip():
        parts.append(fn.strip())
    if isinstance(ln, str) and ln.strip():
        parts.append(ln.strip())
    return " ".join(parts).strip()


def _extract_mention_user(message: Message) -> User | None:
    for entity in message.entities or []:
        if entity.type == "text_mention" and entity.user:
            return entity.user
        if entity.type == "mention" and entity.user:
            return entity.user
    return None


def _needs_user_reply(output: str) -> bool:
    """
    In group/supergroup, Bot Privacy Mode prevents normal text messages from reaching the bot.
    We only need ForceReply when the bot is asking for the user to type the next input
    (e.g., jira_account_id, assignee, summary, description, etc.).
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
    )
    return any(m in output for m in markers)


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
) -> None:
    """
    Send state-machine text to the chat. For TPL_CANCELLED, clear ForceReply on the last bot
    prompt (edit_message_reply_markup) when possible, then send_message without threading.

    In groups, prompts that need free-form input use ForceReply; we store that message_id per
    (chat_id, user_id) so cancel can drop the markup and help clients exit the reply bar.
    """
    key = (chat_id, user_id)

    if tpl_cancelled and output.strip() == tpl_cancelled.strip():
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
        await bot.send_message(chat_id=chat_id, text=output)
        return

    reply_markup = (
        ForceReply(selective=True, input_field_placeholder="…")
        if chat_type in ("group", "supergroup") and _needs_user_reply(output)
        else None
    )
    sent = await trigger_message.reply_text(output, reply_markup=reply_markup)
    if reply_markup is not None and sent and getattr(sent, "message_id", None) is not None:
        force_reply_tracker[key] = int(sent.message_id)


async def _download_to_file_meta(message: Message, kind: str, context: ContextTypes.DEFAULT_TYPE) -> FileMeta | None:
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
    entities = message.entities or []
    for entity in entities:
        if entity.type == "text_mention" and entity.user:
            return entity.user.id
        if entity.type == "mention" and entity.user:
            # Some clients may populate `user` for `mention`; handle best-effort.
            return entity.user.id
    return None


def _extract_mentioned_user_username(message: Message) -> str | None:
    """
    Extract Telegram username from mention entities, if available.

    - `text_mention`: may include full user object (username may be missing).
    - `mention`: often only provides the textual @username (no user object).
    """
    entities = message.entities or []
    text = message.text or message.caption or ""
    for entity in entities:
        if entity.type == "text_mention" and entity.user:
            username = getattr(entity.user, "username", None)
            if isinstance(username, str) and username.strip():
                return username.strip()
        if entity.type == "mention":
            # Best-effort: parse "@username" from message text using entity offsets.
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
    force_reply_tracker: dict[tuple[int, int], int] = {}

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_chat or not update.effective_user:
            return

        tg_message = update.message
        attachments: list[FileMeta] = []
        for kind in ("document", "photo", "video", "audio", "voice", "animation", "video_note", "sticker"):
            meta = await _download_to_file_meta(tg_message, kind, context)
            if meta:
                attachments.append(meta)

        eu = update.effective_user
        sender_user_name = _telegram_user_name_for_store(eu)
        sender_telegram_display_name = _telegram_display_name_only(eu)

        reply_fu = tg_message.reply_to_message.from_user if tg_message.reply_to_message else None
        reply_target_user_name = _telegram_user_name_for_store(reply_fu) if reply_fu else None
        reply_target_telegram_display_name = _telegram_display_name_only(reply_fu) if reply_fu else None

        mu = _extract_mention_user(tg_message)
        if mu:
            mentioned_user_name = _telegram_user_name_for_store(mu)
            mentioned_telegram_display_name = _telegram_display_name_only(mu)
        else:
            un = _extract_mentioned_user_username(tg_message)
            mentioned_user_name = un if un else None
            mentioned_telegram_display_name = "" if un else None

        message_input = MessageInput(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            text=tg_message.text or tg_message.caption,
            reply_to_user_id=(
                tg_message.reply_to_message.from_user.id if tg_message.reply_to_message else None
            ),
            reply_to_username=(
                (tg_message.reply_to_message.from_user.username)
                if tg_message.reply_to_message and tg_message.reply_to_message.from_user
                else None
            ),
            mentioned_user_id=_extract_mentioned_user_id(tg_message),
            mentioned_username=_extract_mentioned_user_username(tg_message),
            sender_user_name=sender_user_name,
            sender_telegram_display_name=sender_telegram_display_name,
            reply_target_user_name=reply_target_user_name,
            reply_target_telegram_display_name=reply_target_telegram_display_name,
            mentioned_user_name=mentioned_user_name,
            mentioned_telegram_display_name=mentioned_telegram_display_name or "",
            attachments=attachments,
        )
        output = state_machine.handle_message(message_input)
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
        )

    application.add_handler(MessageHandler(filters.ALL, on_message))

