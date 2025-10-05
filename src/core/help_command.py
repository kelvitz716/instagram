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
                "📱 INSTAGRAM DOWNLOADER HELP\n"
                "==============================\n\n"
                "🎯 QUICK START\n"
                "------------------------------\n"
                "• Simply paste any Instagram URL\n"
                "• Bot will auto-detect and download\n\n"
                
                "📋 AVAILABLE COMMANDS\n"
                "------------------------------\n"
                "├─ 🚀 /start - Launch the bot\n"
                "├─ 📖 /help - Show this guide\n"
                "├─ 📊 /stats - View statistics\n"
                "├─ 🧹 /cleanup - Clear downloads\n"
                "├─ 📈 /metrics - Show performance\n"
                "╰─ 🔄 /telegram_status - Check status\n\n"
                
                "🔑 SESSION MANAGEMENT\n"
                "------------------------------\n"
                "╰─ 🔐 /session - Manage Instagram Login\n\n"
                
                "📥 SUPPORTED CONTENT\n"
                "------------------------------\n"
                "├─ 📷 Posts & Carousels\n"
                "├─ 🎬 Reels & IGTV\n"
                "├─ 📱 Stories (login required)\n"
                "╰─ ⭐ Highlights (login required)\n\n"
                
                "🔐 SESSION OPTIONS\n"
                "------------------------------\n"
                "1️⃣ Firefox Browser\n"
                "   • Use Firefox cookies\n"
                "   • Must be logged in\n\n"
                "2️⃣ Cookie File\n"
                "   • Upload cookies.txt\n"
                "   • Export via extensions:\n"
                "     ├─ 'Export Cookies'\n"
                "     ╰─ 'Cookie Quick Manager'\n\n"
                
                "ℹ️ SUPPORT\n"
                "------------------------------\n"
                "📞 Contact: @kelvitz716"
            )
        
        await update.message.reply_text(help_text)