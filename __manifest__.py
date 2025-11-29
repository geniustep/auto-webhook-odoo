# -*- coding: utf-8 -*-
{
    'name': 'Auto Webhook - Enterprise Grade',
    'version': '3.1.0',
    'author': 'Odoo Zak, Geniustep',
    'category': 'Tools',
    'sequence': 10,
    'summary': 'Enterprise-Grade Webhook System for Odoo with BridgeCore Integration - Bug Fixed Version',
    'description': """
Enterprise Webhook Management System - v3.1.0 (Bug Fixes)
===========================================================

A comprehensive, production-ready webhook system for Odoo that provides:

What's New in v3.1.0:
---------------------
* **Fixed Multiple Events Issue**: No more duplicate events on create/write
* **Config-Driven System**: All models use webhook.rule (no more webhook.mixin)
* **Better Performance**: Reduced database writes and improved caching
* **Easier Management**: Add/remove tracking for any model from UI
* **Automatic Rules**: Pre-configured rules for common Odoo models

Features:
---------
* **Real-time Event Tracking**: Automatically track create, write, and delete operations
* **Config-Driven Rules**: Define tracking rules from UI without code changes
* **Flexible Configuration**: Per-model webhook configuration with priority and categorization
* **Multiple Subscribers**: Support for multiple webhook endpoints with different auth methods
* **Template System**: Customizable payload templates using Jinja2
* **Retry Mechanism**: Intelligent retry with exponential backoff
* **Dead Letter Queue**: Handle permanently failed events
* **Audit Logging**: Complete audit trail of all webhook activities
* **Rate Limiting**: Control request rate per subscriber
* **Batch Processing**: Optional batch processing for high-volume events
* **BridgeCore Integration**: Seamless integration with BridgeCore API
* **Pull-based Storage**: All events stored in update.webhook for reliable pull access

Technical Highlights:
--------------------
* ORM-based detection (no database triggers)
* Universal base hook (tracks ALL models with rules)
* Smart caching for optimal performance
* Composite indexes for fast queries
* Fail-safe design (errors don't block business operations)
* Compatible with Odoo 16/17/18
* RESTful webhook delivery
* JSON payload format
* Comprehensive error handling and logging

Migration from v3.0.x:
----------------------
This version removes webhook.mixin in favor of webhook.rule system.
Your existing configurations will continue to work, but we recommend:
1. Review webhook.rule records after upgrade
2. Test your integrations
3. Remove any custom webhook.mixin inheritances

For documentation and support, visit: https://www.geniustep.com
    """,
    'website': 'https://www.geniustep.com',
    'license': 'LGPL-3',

    'depends': [
        'base',
        'mail',
        'sale',
        'product',
        'account',
        'purchase',
        'stock',
        'hr_expense',
        'hr',
    ],

    'external_dependencies': {
        'python': ['requests', 'jinja2'],
    },

    'data': [
        # Security (must be first)
        'security/ir.model.access.csv',
        
        # Models (create ir.model records)
        'data/ir_model_data.xml',

        # Data
        'data/webhook_cron.xml',
        'data/webhook_data.xml',  # Webhook configs and subscribers
        'data/webhook_rules_default.xml',  # Pre-configured webhook rules
        'data/update_webhook_cron.xml',  # Cleanup cron for update.webhook

        # Views
        'views/webhook_menuitem.xml',
        'views/webhook_event_views.xml',
        'views/webhook_config_views.xml',
        'views/webhook_subscriber_views.xml',
        'views/webhook_rule_views.xml',
        'views/update_webhook_views.xml',
        'views/user_sync_state_views.xml',
    ],

    'installable': True,
    'auto_install': False,
    'application': True,

    'images': ['static/description/banner.png'],

    'price': 0.00,
    
}
