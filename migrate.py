#!/usr/bin/env python3
"""Apply database migrations."""
import asyncio
import logging
import sqlite3
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def apply_migrations():
    """Apply all pending migrations."""
    try:
        # Get database path from environment or use default
        db_path = Path("bot_data.db")
        migrations_dir = Path(__file__).parent / "migrations"
        
        # Create database connection
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create migrations table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Get applied migrations
        cursor.execute("SELECT name FROM migrations")
        applied = {row[0] for row in cursor.fetchall()}
        
        # Find and sort migration files
        migration_files = sorted(
            f for f in migrations_dir.glob("*.sql")
            if f.name not in applied
        )
        
        # Apply new migrations
        for migration_file in migration_files:
            logger.info(f"Applying migration: {migration_file.name}")
            
            try:
                with open(migration_file, 'r') as f:
                    sql = f.read()
                    
                cursor.executescript(sql)
                cursor.execute(
                    "INSERT INTO migrations (name) VALUES (?)",
                    (migration_file.name,)
                )
                conn.commit()
                logger.info(f"Successfully applied: {migration_file.name}")
                
            except Exception as e:
                logger.error(f"Failed to apply migration {migration_file.name}: {e}")
                conn.rollback()
                raise
                
        logger.info("All migrations applied successfully")
        
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        raise
        
    finally:
        conn.close()

if __name__ == "__main__":
    asyncio.run(apply_migrations())