async def send_media(
    bot,
    chat_id: int,
    media_type: str,
    file_id: str,
    caption: str | None = None,
    **kwargs
):
    """
    Универсальная отправка медиа.
    """

    mapping = {
        "photo": bot.send_photo,
        "voice": bot.send_voice,
        "document": bot.send_document,
        "video": bot.send_video,
        "audio": bot.send_audio,
    }

    if media_type and file_id:
        sender = mapping.get(media_type)

        if sender:
            await sender(
                chat_id=chat_id,
                caption=caption,
                **{media_type: file_id},
                **kwargs
            )
            return

    await bot.send_message(
        chat_id=chat_id,
        text=caption or "(медиа)",
        **kwargs
    )