# Auto Webhook - Enterprise Grade

Enterprise-level webhook management system for Odoo with BridgeCore integration.

## 🚀 Features

### Core Functionality
- **Real-time Event Tracking**: Automatically track create, write, and delete operations on Odoo models
- **Flexible Configuration**: Per-model webhook configuration with priority levels and categorization
- **Multiple Subscribers**: Support for multiple webhook endpoints with different authentication methods
- **Template System**: Customizable payload templates using Jinja2
- **Intelligent Retry**: Exponential backoff retry mechanism for failed events
- **Dead Letter Queue**: Dedicated queue for permanently failed events requiring manual intervention
- **Comprehensive Audit Log**: Complete audit trail of all webhook activities
- **Rate Limiting**: Control request rates per subscriber to prevent overload
- **Batch Processing**: Optional batch processing for high-volume event scenarios

### Technical Highlights
- **ORM-based Detection**: No database triggers required - uses Odoo's ORM hooks
- **Performance Optimized**: Composite database indexes for fast queries
- **Fail-Safe Design**: Webhook errors never block business operations
- **Compatible**: Works with Odoo 16, 17, and 18
- **RESTful Delivery**: Standard HTTP POST webhook delivery
- **JSON Payloads**: Clean, structured JSON format
- **Error Handling**: Comprehensive error handling and logging

## 📋 Requirements

- Odoo 16.0, 17.0, or 18.0
- Python 3.8+
- Python packages: `requests`, `jinja2`

## 🔧 Installation

```bash
cd /path/to/odoo/addons
git clone https://github.com/geniustep/auto-webhook-odoo.git
pip install requests jinja2
```

Then in Odoo: **Apps > Update Apps List > Search "Auto Webhook" > Install**

## ⚙️ Quick Start

### 1. Create Subscriber
**Webhooks > Configuration > Subscribers > Create**
- Name: "BridgeCore Production"
- Endpoint URL: `https://bridgecore.geniura.com/api/v1/webhooks/receive`
- Auth Type: Bearer Token / API Key
- Test Connection

### 2. Configure Model
**Webhooks > Configuration > Webhook Configs > Create**
- Model: Select model (e.g., "Sales Order")
- Events: Create/Write/Delete
- Priority: High/Medium/Low
- Subscribers: Select subscriber(s)
- Enable configuration

### 3. Verify
Create/edit a record → Check **Webhooks > Events > All Events**

## 📊 Usage

### Event Management
- **View Events**: Webhooks > Events > All Events
- **Filter**: By status, priority, model, date
- **Retry Failed**: Open event → Click "Retry Now"

### Advanced Features
- **Field Filtering**: Track only specific fields
- **Domain Filters**: `[('state', '=', 'done')]`
- **Batch Processing**: High-volume scenarios
- **Custom Templates**: Jinja2 payload formatting

## 🔄 Automated Jobs

| Job | Frequency | Purpose |
|-----|-----------|---------|
| Process Events | 1 min | Send pending events |
| Retry Failed | 1 min | Retry with backoff |
| Cleanup Old | Daily | Archive/delete old events |
| Cleanup Audit | Weekly | Remove old audit logs |

## 📚 Payload Format

```json
{
  "event_id": 123,
  "model": "sale.order",
  "record_id": 456,
  "event": "create",
  "timestamp": "2025-01-15T10:30:00Z",
  "priority": "high",
  "category": "business",
  "data": {
    "name": "SO001",
    "partner_id": {"id": 789, "name": "Customer ABC"},
    "amount_total": 1500.00
  }
}
```

## 🛠️ Custom Models

```python
from odoo import models

class MyModel(models.Model):
    _name = 'my.model'
    _inherit = ['my.model', 'webhook.mixin']
```

Then create webhook configuration for `my.model`.

## 🤝 Support

- **GitHub**: https://github.com/geniustep/auto-webhook-odoo
- **Website**: https://www.geniustep.com

## 📄 License

LGPL-3

## 👥 Authors

Odoo Zak, Geniustep Team

---

**Version 2.0.0** - Enterprise-Grade Webhook System for Odoo
