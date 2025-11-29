# Core webhook models
from . import webhook_event
from . import webhook_config
from . import webhook_subscriber
from . import webhook_template
from . import webhook_retry
from . import webhook_audit
from . import update  # Keep for backward compatibility
from . import update_webhook  # New: Pull-based event storage
from . import user_sync_state  # New: Track sync state for BridgeCore Smart Sync
from . import webhook_rule  # New: Config-driven webhook rules
from . import base_webhook_hook  # New: Universal base hook (replaces webhook_mixin)

# Legacy models (deprecated - kept for backward compatibility)
# Note: webhook_mixin and list_model are deprecated in favor of base_webhook_hook + webhook_rule
# These are commented out to prevent duplicate event creation
# from . import webhook_mixin
# from . import webhook_webhook
# from . import list_model