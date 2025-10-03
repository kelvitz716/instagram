"""Handle metrics command for the bot."""
from telegram import Update
from telegram.ext import ContextTypes
from prometheus_client.parser import text_string_to_metric_families
from prometheus_client import generate_latest

from .config import ADMIN_USER_IDS

async def metrics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show current metrics in a Telegram-friendly format."""
    if not update.effective_user or update.effective_user.id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔️ Sorry, this command is only available for administrators.")
        return

    # Get metrics from the metrics collector in the bot's services
    metrics_text = generate_latest().decode('utf-8')
    
    # Initialize metric categories with emojis
    metrics = {
        "📊 System Overview": [],
        "💾 Memory Usage": [],
        "🔄 Runtime Stats": [],
        "📈 Performance": [],
        "🔍 Debug Info": []
    }
    
    def format_bytes(bytes_value):
        """Format bytes into human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if bytes_value < 1024:
                return f"{bytes_value:.1f}{unit}"
            bytes_value /= 1024
        return f"{bytes_value:.1f}TB"
        
    def format_uptime(seconds):
        """Format uptime in a human-readable format"""
        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        minutes = int((seconds % 3600) // 60)
        
        if days > 0:
            return f"{days} days, {hours} hours, {minutes} min"
        elif hours > 0:
            return f"{hours} hours, {minutes} min"
        else:
            return f"{minutes} minutes"
    
    def get_status_indicator(name, value):
        """Get status indicator based on metric type and value"""
        if 'memory' in name:
            used_percent = (value / (1024 * 1024 * 1024)) * 100  # Convert to GB percentage
            if used_percent > 80:
                return "⛔️"  # Critical
            elif used_percent > 60:
                return "⚠️"  # Warning
            return "✅"  # Good
        elif 'cpu' in name:
            if value > 80:
                return "⛔️"
            elif value > 50:
                return "⚠️"
            return "✅"
        elif 'errors' in name or 'failed' in name:
            return "⛔️" if value > 0 else "✅"
        return "•"  # Default bullet point

    def get_metric_category(name):
        """Determine which category a metric belongs to"""
        name_lower = name.lower()
        if any(x in name_lower for x in ['memory', 'ram', 'heap']):
            return "💾 Memory Usage"
        elif any(x in name_lower for x in ['cpu', 'time', 'process']):
            return "📊 System Overview"
        elif any(x in name_lower for x in ['gc', 'python', 'version']):
            return "🔍 Debug Info"
        elif 'start' in name_lower:
            return "📊 System Overview"
        return "🔄 Runtime Stats"

    def format_metric(name, value, labels=None):
        """Format a single metric with improved readability"""
        # Clean up the metric name
        display_name = (name.replace('_', ' ')
                          .replace('process', '')
                          .replace('python', '')
                          .strip()
                          .title())
        
        # Format the value based on type and context
        if 'memory' in name.lower() or 'bytes' in name.lower():
            formatted_value = format_bytes(value)
        elif 'start_time' in name.lower():
            import time
            uptime = time.time() - value
            formatted_value = format_uptime(uptime)
        elif isinstance(value, float):
            if value.is_integer():
                formatted_value = f"{int(value):,}"
            elif 'seconds' in name.lower():
                formatted_value = f"{value:.1f}s"
            else:
                formatted_value = f"{value:.1f}"
        else:
            formatted_value = str(value)
        
        # Get status indicator
        status = get_status_indicator(name.lower(), value)
        
        # Format labels if present
        if labels and not any(x in name.lower() for x in ['gc', 'info']):
            label_str = f" ({', '.join(f'{k}={v}' for k, v in labels.items() if k != 'version')})"
        else:
            label_str = ""

        return f"{status} {display_name}{label_str}: {formatted_value}"

    # Process and categorize metrics
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            if 'python_gc' in sample.name and 'uncollectable' in sample.name:
                continue  # Skip uncollectable objects stats as they're usually 0
            
            metric = format_metric(sample.name, sample.value, sample.labels)
            category = get_metric_category(sample.name)
            metrics[category].append(metric)
    
    # Get current time
    from datetime import datetime
    current_time = datetime.now().strftime("%b %d, %Y at %I:%M %p")

    # Build final message with improved formatting
    message = "🚀 *MISSION STATUS REPORT*\n"
    message += "`" + "=" * 30 + "`\n"
    message += f"📅 Report Time: `{current_time}`\n\n"
    
    # System Overview section
    message += "*🔧 SYSTEM VITALS*\n"
    message += "`" + "-" * 30 + "`\n"
    
    # Add resource metrics with proper alignment
    system_metrics = []
    memory_metrics = []
    runtime_stats = []
    
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            name = sample.name.lower()
            value = sample.value
            
            # Format system vitals with status indicators
            if 'cpu' in name:
                status = "⛔️" if value > 10 else "⚠️" if value > 5 else "✅"
                system_metrics.append(f"├─ 🧠 CPU Usage    : {status} `{value:.1f}s total`")
            elif 'memory' in name and 'resident' in name:
                used_percent = (value / (1024 * 1024 * 1024)) * 100  # to GB percentage
                status = "⛔️" if used_percent > 80 else "⚠️" if used_percent > 60 else "✅"
                memory_metrics.append(f"├─ 💾 Memory Used  : {status} `{format_bytes(value)}`")
            elif 'memory' in name and 'virtual' in name:
                used_percent = (value / (1024 * 1024 * 1024)) * 100  # to GB percentage
                status = "⛔️" if used_percent > 80 else "⚠️" if used_percent > 60 else "✅"
                memory_metrics.append(f"├─ 💽 Virtual Mem  : {status} `{format_bytes(value)}`")
            elif 'fds' in name and 'open' in name:
                status = "⛔️" if value > 1000 else "⚠️" if value > 500 else "✅"
                system_metrics.append(f"├─ 📡 Open FDs    : {status} `{int(value):,}`")
            elif 'start_time' in name:
                import time
                uptime = time.time() - value
                status = "⚠️" if uptime > 7*24*3600 else "✅"  # Warning if up more than 7 days
                system_metrics.append(f"╰─ ⏱️ Uptime      : {status} `{format_uptime(uptime)}`")
            
            # Get Python version info
            if 'python_info' in name:
                runtime_version = sample.labels.get('version', '3.x.x')
                impl = sample.labels.get('implementation', 'CPython')
                runtime_stats.append(f"├─ 🐍 Runtime     : `{impl} {runtime_version}`")
    
    # Add system metrics in order
    message += "\n".join(sorted(system_metrics)) + "\n\n"
    
    # Memory section
    message += "*💾 MEMORY STATUS*\n"
    message += "`" + "-" * 30 + "`\n"
    message += "\n".join(sorted(memory_metrics)) + "\n\n"
    
    # Runtime Environment
    message += "*⚙️ RUNTIME ENVIRONMENT*\n"
    message += "`" + "-" * 30 + "`\n"
    message += "\n".join(runtime_stats)
    
    # GC Stats (in a collapsible format)
    gc_stats = []
    for family in text_string_to_metric_families(metrics_text):
        if 'python_gc' in family.name:
            for sample in family.samples:
                gen = sample.labels.get('generation', '?')
                if 'collections' in sample.name:
                    gc_stats.append(f"Gen{gen}={int(sample.value)}")
    
    if gc_stats:
        message += f"\n╰─ ♻️ GC Status   : `{' | '.join(gc_stats)}`\n\n"
    
    # Add legend footer
    message += "\n`" + "-" * 30 + "`\n"
    message += "📊 *Status Indicators*\n"
    message += "✅ Normal | ⚠️ Warning | ⛔️ Critical\n\n"
    message += "_This is an automated health report_"

    try:
        await update.message.reply_text(
            message,
            parse_mode="Markdown"
        )
    except Exception as e:
        # If message is too long, split it into chunks
        chunk_size = 4000
        chunks = [message[i:i + chunk_size] for i in range(0, len(message), chunk_size)]
        for chunk in chunks:
            await update.message.reply_text(
                chunk,
                parse_mode="Markdown"
            )