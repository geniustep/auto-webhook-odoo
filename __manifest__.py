# -*- coding: utf-8 -*-
{
    'name': 'Auto Webhook - Enterprise Grade',
    'version': '2.0.0',
    'author': 'Odoo Zak, Geniustep',
    'category': 'Tools',
    'sequence': 10,
    'summary': 'Enterprise-Grade Webhook System for Odoo with BridgeCore Integration',
    'description': """
Enterprise Webhook Management System
=====================================

A comprehensive, production-ready webhook system for Odoo that provides:

Features:
---------
* **Real-time Event Tracking**: Automatically track create, write, and delete operations
* **Flexible Configuration**: Per-model webhook configuration with priority and categorization
* **Multiple Subscribers**: Support for multiple webhook endpoints with different auth methods
* **Template System**: Customizable payload templates using Jinja2
* **Retry Mechanism**: Intelligent retry with exponential backoff
* **Dead Letter Queue**: Handle permanently failed events
* **Audit Logging**: Complete audit trail of all webhook activities
* **Rate Limiting**: Control request rate per subscriber
* **Batch Processing**: Optional batch processing for high-volume events
* **BridgeCore Integration**: Seamless integration with BridgeCore API

Technical Highlights:
--------------------
* ORM-based detection (no database triggers)
* Performance-optimized with composite indexes
* Fail-safe design (errors don't block business operations)
* Compatible with Odoo 16/17/18
* RESTful webhook delivery
* JSON payload format
* Comprehensive error handling and logging

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
        # Security
        'security/ir.model.access.csv',

        # Data
        'data/webhook_cron.xml',
        'data/webhook_data.xml',

        # Views
        'views/webhook_event_views.xml',
        'views/webhook_config_views.xml',
        'views/webhook_subscriber_views.xml',
        'views/webhook_menuitem.xml',
    ],

    'installable': True,
    'auto_install': False,
    'application': True,

    'images': ['static/description/banner.png'],

    'price': 0.00,
    'currency': 'USD',
}
