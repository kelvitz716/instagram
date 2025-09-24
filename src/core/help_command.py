"""Help command handler for the Instagram bot."""
from typing import Optional
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class HelpCommandMixin:
    """Mixin for help command handling."""
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle the /help command."""
        if not update.message:
            return
            
        help_text = (
            "📸 Instagram Content Downloader Bot\n\n"
            "Main Commands:\n"
            "• Send any Instagram URL to download content\n"
            "• /start - Start the bot\n"
            "• /help - Show this help message\n"
            "• /stats - View download statistics\n\n"
            "Session Management:\n"
            "• /session_upload - Upload a cookies.txt file\n"
            "• /session_list - List and manage your sessions\n\n"
            "Supported Content Types:\n"
            "• Posts (single/multiple photos/videos)\n"
            "• Reels\n"
            "• Stories (requires login)\n"
            "• Highlights (requires login)\n\n"
            "Session Types:\n"
            "1. Firefox Browser:\n"
            "   - Uses cookies from your Firefox browser\n"
            "   - Must be logged into Instagram in Firefox\n\n"
            "2. Cookie File:\n"
            "   - Upload a cookies.txt file\n"
            "   - Export from Firefox using extensions:\n"
            "     • 'Export Cookies'\n"
            "     • 'Cookie Quick Manager'\n\n"
            "For support: @kelvitz716"
        )
        
        await update.message.reply_text(help_text)