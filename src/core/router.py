import logging
from typing import Dict, Callable, Any
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class CommandRouter:
    """
    Handles command routing and provides a clean interface for command handlers
    
    Usage:
        router = CommandRouter(services)
        router.register_command("start", handle_start)
        await router.route_command(update, context)
    """
    
    def __init__(self, services: "BotServices"):
        self.services = services
        self.commands: Dict[str, Callable] = {}
        self._setup_default_error_handler()
    
    def register_command(self, command: str, handler: Callable):
        """Register a command handler"""
        self.commands[command] = handler
    
    def register_commands(self, handlers: Dict[str, Callable]):
        """Register multiple command handlers at once"""
        self.commands.update(handlers)
    
    async def route_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route a command to its handler"""
        if not update.message or not update.message.text:
            return
            
        command = update.message.text.split()[0][1:]  # Remove /
        handler = self.commands.get(command)
        
        if not handler:
            await self._handle_unknown_command(update, context)
            return
        
        try:
            await handler(update, context)
        except Exception as e:
            await self._handle_command_error(update, context, e)
    
    async def _handle_unknown_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle unknown commands"""
        await update.message.reply_text(
            "❓ Unknown command. Use /help to see available commands.",
            parse_mode='Markdown'
        )
    
    async def _handle_command_error(
        self, 
        update: Update, 
        context: ContextTypes.DEFAULT_TYPE,
        error: Exception
    ):
        """Default error handler for command execution"""
        error_message = str(error)
        # Truncate very long error messages
        if len(error_message) > 100:
            error_message = error_message[:97] + "..."
            
        await update.message.reply_text(
            f"❌ Error executing command: `{error_message}`\n\n"
            "Please try again or check logs for details.",
            parse_mode='Markdown'
        )
        logger.error(
            "Command execution error",
            exc_info=error,
            extra={
                "command": update.message.text,
                "user_id": update.effective_user.id,
                "chat_id": update.effective_chat.id
            }
        )
    
    def _setup_default_error_handler(self):
        """Set up default error handler for unhandled exceptions"""
        async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
            logger.error(
                "Unhandled error in command handler",
                exc_info=context.error
            )
        self.error_handler = error_handler
