"""Telegram handlers for Phase 3 state-machine integration."""

from __future__ import annotations

from datetime import datetime, timezone

from telegram import ForceReply, Message, Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.conversation.state_machine import FileMeta, MessageInput, build_filename


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
    return None


def register_handlers(application: Application, state_machine: object) -> None:
    def _needs_user_reply(output: str) -> bool:
        """
        In group/supergroup, Bot Privacy Mode prevents normal text messages from reaching the bot.
        We only need ForceReply when the bot is asking for the user to type the next input
        (e.g., jira_account_id, assignee, summary, description, etc.).
        """
        if not output:
            return False

        # Prompts that require free-form user input (not a '/' command).
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

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.effective_chat or not update.effective_user:
            return

        tg_message = update.message
        attachments: list[FileMeta] = []
        for kind in ("document", "photo", "video", "audio", "voice", "animation", "video_note", "sticker"):
            meta = await _download_to_file_meta(tg_message, kind, context)
            if meta:
                attachments.append(meta)

        message_input = MessageInput(
            chat_id=update.effective_chat.id,
            user_id=update.effective_user.id,
            text=tg_message.text or tg_message.caption,
            reply_to_user_id=(tg_message.reply_to_message.from_user.id if tg_message.reply_to_message else None),
            mentioned_user_id=_extract_mentioned_user_id(tg_message),
            attachments=attachments,
        )
        output = state_machine.handle_message(message_input)
        # In groups, Bot Privacy Mode hides plain-text messages unless they are
        # commands, @mentions, or replies to the bot. ForceReply nudges the client
        # to reply to our message so the next user input is delivered to the bot.
        chat_type = getattr(update.effective_chat, "type", None)
        reply_markup = (
            ForceReply(selective=True, input_field_placeholder="…")
            if chat_type in ("group", "supergroup") and _needs_user_reply(output)
            else None
        )
        await tg_message.reply_text(output, reply_markup=reply_markup)

    application.add_handler(MessageHandler(filters.ALL, on_message))

