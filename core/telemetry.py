import requests
import os
from datetime import datetime

class TelemetryManager:
    """
    Handles real-time notifications for critical trade events.
    Supports console output and optional Discord/Slack webhooks.
    
    HARDENING: Validates webhook URL, fails silently, never crashes.
    """
    def __init__(self, webhook_url: str = None):
        # Get from env if not provided
        env_url = os.getenv("TELEMETRY_WEBHOOK_URL")
        raw_url = webhook_url or env_url
        
        # Validate webhook URL
        self.webhook_enabled = False
        if raw_url and isinstance(raw_url, str) and raw_url.startswith("http"):
            self.webhook_url = raw_url
            self.webhook_enabled = True
        else:
            self.webhook_url = None
            # Log once at boot if URL was provided but invalid
            if raw_url:
                print(f"[TELEMETRY] WEBHOOK_DISABLED (invalid URL provided: {raw_url})")
            else:
                print(f"[TELEMETRY] WEBHOOK_DISABLED (no URL configured)")

    def notify(self, event_type: str, message: str, severity: str = "INFO"):
        """Sends a notification to console and optionally to webhook."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_msg = f"[{timestamp}] [{severity}] {event_type}: {message}"
        
        # 1. Local Console (Always)
        print(f"\n[TELEMETRY] {formatted_msg}")
        
        # 2. External Webhook (Only if enabled and valid)
        if self.webhook_enabled and self.webhook_url:
            try:
                payload = {"text": formatted_msg}
                requests.post(self.webhook_url, json=payload, timeout=5)
            except Exception:
                # Fail silently - never crash, never spam console
                pass

# Global instance
telemetry = TelemetryManager()
