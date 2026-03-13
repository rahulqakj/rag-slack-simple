"""
Helper functions for Slack channel export and ingestion into knowledge base.
"""
import json
import os
import tempfile
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional

from src.scripts.export_slack_channel import (
    SlackExporterError,
    fetch_channel_messages,
    parse_epoch,
)


def fetch_user_map(token: str) -> Dict[str, Dict[str, str]]:
    """
    Fetch all users from Slack workspace and create a mapping of user_id -> user info.
    
    Args:
        token: Slack API token
        
    Returns:
        Dict mapping user_id to dict with name, real_name, display_name, image
    """
    url = "https://slack.com/api/users.list"
    headers = {"Authorization": f"Bearer {token}"}
    user_map = {}
    
    cursor = None
    while True:
        params = {"limit": 200}
        if cursor:
            params["cursor"] = cursor
            
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        if not data.get("ok"):
            raise SlackExporterError(f"Failed to fetch users: {data.get('error', 'Unknown error')}")
        
        for user in data.get("members", []):
            profile = user.get("profile", {})
            user_map[user["id"]] = {
                "name": user.get("name", ""),
                "real_name": profile.get("real_name", ""),
                "display_name": profile.get("display_name", ""),
                "image_72": profile.get("image_72", "")
            }
        
        cursor = data.get("response_metadata", {}).get("next_cursor")
        if not cursor:
            break
    
    return user_map


def export_and_ingest_slack_channel(
    token: str,
    channel_id: str,
    oldest: Optional[str],
    latest: Optional[str],
    include_threads: bool,
    knowledge_service,
    file_processor,
    workspace_domain: str = "kitabisa",
) -> Dict[str, any]:
    """
    Export Slack channel history and ingest into knowledge base.
    
    Args:
        token: Slack user token (xoxp-...)
        channel_id: Slack channel ID (e.g., GDDFBV5B2)
        oldest: Oldest timestamp (epoch or ISO date like "2024-01-01")
        latest: Latest timestamp (epoch or ISO date)
        include_threads: Whether to fetch thread replies
        knowledge_service: KnowledgeService instance
        file_processor: FileProcessor instance
        workspace_domain: Slack workspace domain (for generating links)
        
    Returns:
        Dict with status, message_count, ingested_chunks, and any errors
    """
    import uuid
    from src.config.database import DatabaseConfig
    
    result = {
        "status": "success",
        "message_count": 0,
        "ingested_chunks": 0,
        "errors": [],
        "debug_logs": []  # Add debug logs array
    }
    
    try:
        # Parse timestamps
        oldest_ts = parse_epoch(oldest) if oldest else None
        latest_ts = parse_epoch(latest) if latest else None
        
        # Try to fetch user mapping (for real names) - graceful fallback if missing scope
        try:
            user_map = fetch_user_map(token)
        except SlackExporterError as e:
            # If missing users:read scope, continue without user names
            if "missing_scope" in str(e):
                result["errors"].append("⚠️ Warning: Token missing 'users:read' scope - using User IDs instead of names")
                user_map = {}
            else:
                raise
        
        # Fetch messages from Slack
        result["debug_logs"].append(f"🔍 Step 1: Fetching messages with include_threads={include_threads}")
        
        messages, fetch_logs = fetch_channel_messages(
            token=token,
            channel_id=channel_id,
            oldest=oldest_ts,
            latest=latest_ts,
            limit=200,
            pause=1.0,
            include_threads=include_threads,
        )
        
        # Add fetch logs to result
        result["debug_logs"].extend(fetch_logs)
        
        result["message_count"] = len(messages)
        result["debug_logs"].append(f"✅ Step 1 Complete: Fetched {len(messages)} messages from Slack")
        
        # DEBUG: Check how many messages have replies field
        msgs_with_threads = sum(1 for m in messages if m.get("replies"))
        msgs_with_reply_count = sum(1 for m in messages if m.get("reply_count", 0) > 0)
        result["debug_logs"].append(f"📊 Messages with reply_count > 0: {msgs_with_reply_count}")
        result["debug_logs"].append(f"📊 Messages with 'replies' field: {msgs_with_threads}")
        
        if include_threads and msgs_with_reply_count > 0 and msgs_with_threads == 0:
            result["debug_logs"].append(f"⚠️ WARNING: {msgs_with_reply_count} messages have replies but 'replies' field is missing!")
            result["debug_logs"].append("⚠️ This means thread fetching failed or was skipped")
        
        if include_threads and msgs_with_threads > 0:
            result["debug_logs"].append(f"✅ Thread fetching SUCCESS: {msgs_with_threads} threads will be processed")
        
        result["debug_logs"].append(f"\n🔍 Step 2: Processing and ingesting messages...")
        
        if not messages:
            result["status"] = "warning"
            result["errors"].append("No messages found in the specified date range")
            return result
        
        # Process messages individually with rich metadata
        conn = DatabaseConfig.get_db_connection()
        cursor = conn.cursor()
        chunks_added = 0
        
        try:
            for msg in messages:
                # Generate message permalink
                msg_ts = msg.get("ts", "")
                msg_ts_clean = msg_ts.replace(".", "")
                message_permalink = f"https://{workspace_domain}.slack.com/archives/{channel_id}/p{msg_ts_clean}"
                
                # Extract message info
                user_id = msg.get("user", "Unknown")
                user_info = user_map.get(user_id, {})
                user_display = user_info.get("real_name") or user_info.get("display_name") or user_info.get("name") or user_id
                
                text = msg.get("text", "")
                timestamp = msg.get("ts", "")
                posted_at = datetime.fromtimestamp(float(timestamp), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if timestamp else ""
                
                # Build content with context
                content_lines = [
                    f"[{posted_at}] {user_display}:",
                    text,
                ]
                
                # Handle thread replies - FULL THREAD NOW
                thread_permalink = None
                thread_full_text = None
                # Check 'replies' field (actual thread replies WITHOUT parent)
                thread_messages = msg.get("replies", [])
                
                # Debug: Check if thread_messages exist
                if msg.get("reply_count", 0) > 0:
                    result["debug_logs"].append(f"📝 Message {timestamp} has {msg.get('reply_count')} replies, replies field: {len(thread_messages)} items")
                
                if thread_messages:
                    # These are already actual replies (parent excluded), no need to filter
                    thread_permalink = f"{message_permalink}?thread_ts={msg_ts}"
                    thread_lines = []
                    
                    # Add parent message first (for thread excerpt display)
                    parent_line = f"[{posted_at}] {user_display}: {text}"
                    
                    # Include ALL replies
                    for reply in thread_messages:
                        reply_user_id = reply.get("user", "Unknown")
                        reply_user_info = user_map.get(reply_user_id, {})
                        reply_user_display = reply_user_info.get("real_name") or reply_user_info.get("display_name") or reply_user_info.get("name") or reply_user_id
                        reply_text = reply.get("text", "")
                        reply_ts = reply.get("ts", "")
                        reply_time = datetime.fromtimestamp(float(reply_ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S") if reply_ts else ""
                        thread_lines.append(f"[{reply_time}] {reply_user_display}: {reply_text}")
                    
                    # Full thread text for display in sources (parent + replies)
                    thread_full_text = parent_line + "\n" + "\n".join(thread_lines)
                    
                    # Add to content - ALWAYS add if we have replies
                    content_lines.append(f"\n📝 Thread ({len(thread_messages)} replies):")
                    content_lines.extend([f"  ↳ {line}" for line in thread_lines])
                
                content = "\n".join(content_lines)
                
                # Create metadata with all fields expected by chat_interface
                metadata = {
                    "source": f"slack_{channel_id}",
                    "channel_id": channel_id,
                    "channel_name": channel_id,
                    "workspace_domain": workspace_domain,
                    "user_id": user_id,
                    "user_display_name": user_display,
                    "message_ts": timestamp,
                    "posted_at": posted_at,
                    "message_permalink": message_permalink,
                }
                
                if thread_permalink:
                    metadata["thread_permalink"] = thread_permalink
                if thread_full_text:
                    metadata["thread_root_excerpt"] = thread_full_text
                
                # Embed and store directly (bypassing add_to_knowledge_base to preserve metadata)
                embedding = knowledge_service.embedding_service.embed_text(content)
                if embedding:
                    cursor.execute(
                        "INSERT INTO knowledge_chunks (id, content, embedding, metadata) VALUES (%s, %s, %s, %s)",
                        (
                            str(uuid.uuid4()),
                            content,
                            '[' + ','.join(map(str, embedding)) + ']',
                            json.dumps(metadata)
                        )
                    )
                    chunks_added += 1
                    
                    # Log successful ingestion
                    if thread_full_text:
                        result["debug_logs"].append(f"  ✅ Ingested message with {len(thread_messages)} thread replies")
            
            conn.commit()
            result["ingested_chunks"] = chunks_added
            result["debug_logs"].append(f"\n✅ Step 2 Complete: Ingested {chunks_added} chunks to database")
        
        finally:
            cursor.close()
            conn.close()
        
    except SlackExporterError as exc:
        result["status"] = "error"
        result["errors"].append(f"Slack API error: {str(exc)}")
    except Exception as exc:
        result["status"] = "error"
        result["errors"].append(f"Unexpected error: {str(exc)}")
    
    return result


def format_slack_messages_as_text(messages: List[Dict], channel_id: str, workspace_domain: str = "kitabisa") -> str:
    """
    Convert Slack messages JSON to readable text format with thread context.
    
    Args:
        messages: List of Slack message dicts
        channel_id: Channel ID for reference
        workspace_domain: Slack workspace domain for generating message links
        
    Returns:
        Formatted text content
    """
    lines = [
        f"Slack Channel: {channel_id}",
        f"Workspace: {workspace_domain}.slack.com",
        f"Exported at: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        "=" * 80,
        ""
    ]
    
    for msg in messages:
        timestamp = float(msg.get("ts", 0))
        dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
        date_str = dt.strftime("%Y-%m-%d %H:%M:%S")
        
        user = msg.get("user", "unknown")
        text = msg.get("text", "")
        msg_ts = msg.get("ts", "").replace(".", "")
        
        # Generate Slack permalink
        permalink = f"https://{workspace_domain}.slack.com/archives/{channel_id}/p{msg_ts}"
        
        lines.append(f"[{date_str}] {user}:")
        lines.append(text)
        lines.append(f"🔗 Link: {permalink}")
        
        # Add thread messages if present
        thread_messages = msg.get("thread_messages", [])
        if thread_messages and len(thread_messages) > 1:  # Skip parent message
            lines.append("")
            lines.append("  📝 Thread Replies:")
            lines.append("  " + "-" * 76)
            for reply in thread_messages[1:]:  # Skip first (parent)
                reply_ts = float(reply.get("ts", 0))
                reply_dt = datetime.fromtimestamp(reply_ts, tz=timezone.utc)
                reply_date = reply_dt.strftime("%Y-%m-%d %H:%M:%S")
                reply_user = reply.get("user", "unknown")
                reply_text = reply.get("text", "")
                reply_msg_ts = reply.get("ts", "").replace(".", "")
                reply_link = f"https://{workspace_domain}.slack.com/archives/{channel_id}/p{reply_msg_ts}?thread_ts={msg.get('thread_ts', '')}"
                
                lines.append(f"    ↳ [{reply_date}] {reply_user}:")
                lines.append(f"      {reply_text}")
                lines.append(f"      🔗 {reply_link}")
                lines.append("")
            lines.append("  " + "-" * 76)
        
        lines.append("")
        lines.append("=" * 80)
        lines.append("")  # Extra blank line between messages
    
    return "\n".join(lines)


def validate_slack_token(token: str) -> bool:
    """
    Basic validation for Slack token format.
    
    Args:
        token: Slack token to validate
        
    Returns:
        True if token looks valid, False otherwise
    """
    if not token:
        return False
    
    # User tokens start with xoxp-, bot tokens with xoxb-
    return token.startswith(("xoxp-", "xoxb-"))


def validate_channel_id(channel_id: str) -> bool:
    """
    Basic validation for Slack channel ID format.
    
    Args:
        channel_id: Channel ID to validate
        
    Returns:
        True if ID looks valid, False otherwise
    """
    if not channel_id:
        return False
    
    # Channel IDs typically start with C or G and are alphanumeric
    return len(channel_id) >= 9 and channel_id[0] in ("C", "G") and channel_id.isalnum()
