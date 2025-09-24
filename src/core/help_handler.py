    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command."""
        if not update.message:
            return
            
        help_text = (
            f"🤖 Instagram Downloader Bot v{BOT_VERSION}\n\n"
            "Commands:\n"
            "• Send any Instagram URL to download content\n"
            "• /session_upload - Upload cookies.txt file\n"
            "• /session_list - List and manage sessions\n"
            "• /stats - View download statistics\n\n"
            "Session Setup:\n"
            "1. Use browser extensions like 'Export Cookies' or\n   'Cookie Quick Manager' to export cookies\n"
            "2. Upload the cookies.txt file using /session_upload\n"
            "3. Start downloading content!\n\n"
            "Supported Content:\n"
            "• Posts (single/multiple photos/videos)\n"
            "• Reels\n"
            "• Stories (requires login)\n"
            "• Highlights\n\n"
            "For issues or feedback: @kelvitz716"
        )
        await update.message.reply_text(help_text)