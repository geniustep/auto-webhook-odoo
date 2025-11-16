# Auto Webhook Dual-Write System - دليل التطوير الجديد

## نظرة عامة

تم تطوير نظام **Dual-Write** لتحسين كفاءة Auto Webhook Odoo Module بإضافة:

1. **نظام Pull-based** للتكامل مع BridgeCore API
2. **إرسال فوري** للأحداث الحرجة (Instant Trigger)
3. **تخزين محسّن** لجميع الأحداث في `update.webhook`
4. **أداء أفضل** مع تقليل الحمل على النظام

---

## الهيكل الجديد

### 1. Model الجديد: `update.webhook`

**الملف:** `models/update_webhook.py`

**الغرض:**
- تخزين جميع أحداث webhook (create, write, unlink)
- دعم Pull-based API للقراءة من BridgeCore
- أرشفة تلقائية للأحداث القديمة

**الحقول الرئيسية:**
```python
- id: معرّف تلقائي متسلسل
- model: اسم النموذج (مثل 'sale.order')
- record_id: رقم السجل
- event: نوع الحدث (create/write/unlink)
- payload: البيانات الكاملة (JSON)
- timestamp: وقت الحدث
- user_id: المستخدم الذي قام بالتغيير
- is_processed: هل تمت معالجته من BridgeCore
- is_archived: للأرشفة التلقائية
- priority: الأولوية (high/medium/low)
- category: الفئة (business/system/notification/custom)
```

**Indexes للأداء:**
```sql
- idx_update_webhook_pull: (id, is_processed, is_archived)
- idx_update_webhook_model_time: (model, timestamp DESC)
- idx_update_webhook_cleanup: (is_processed, timestamp)
- idx_update_webhook_priority: (priority, is_processed, timestamp DESC)
```

---

### 2. منطق Dual-Write في `webhook_mixin.py`

**الاستراتيجية:**

```
عند حدوث event (create/write/unlink):

1. كتابة في update.webhook (دائماً) ← للـ Pull-based access
   ↓
2. قرار: هل نرسل فوراً؟
   ├─ نعم: إذا instant_send = True AND priority = high
   │   └─ إنشاء webhook.event + إرسال فوري
   └─ لا: فقط update.webhook
       └─ BridgeCore سيسحبها لاحقاً
```

**مثال على الكود:**
```python
def _process_webhook_event(self, event_type, changed_vals=None):
    # تحضير البيانات
    payload_data = self._prepare_webhook_data(changed_vals)

    # STEP 1: كتابة في update.webhook (دائماً)
    self._write_to_update_webhook(event_type, payload_data, config)

    # STEP 2: قرار الإرسال الفوري
    should_send_instant = config.instant_send and config.priority == 'high'

    if should_send_instant:
        # إنشاء webhook.event + إرسال فوري
        event = self.env['webhook.event'].create(...)
        self._trigger_webhook_instant(event)
```

---

### 3. Pull API Endpoints

**الملف:** `controllers/webhook_api.py`

#### a) Pull Events
```http
GET/POST /api/webhooks/pull

Parameters:
- last_event_id: آخر ID تم سحبه (default: 0)
- limit: عدد الأحداث (default: 100, max: 1000)
- models: قائمة النماذج (اختياري)
- priority: تصفية حسب الأولوية (اختياري)

Response:
{
  "success": true,
  "events": [...],
  "last_id": 550,
  "has_more": true,
  "count": 100,
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
# Pull latest 100 events
curl -X GET "https://odoo.example.com/api/webhooks/pull?last_event_id=0&limit=100" \
  -H "X-API-Key: your-api-key"

# Pull specific models with high priority
curl -X POST "https://odoo.example.com/api/webhooks/pull" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "last_event_id": 100,
    "limit": 50,
    "models": ["sale.order", "purchase.order"],
    "priority": "high"
  }'
```

#### b) Mark as Processed
```http
POST /api/webhooks/mark-processed

Body:
{
  "event_ids": [101, 102, 103, 104, 105]
}

Response:
{
  "success": true,
  "processed_count": 5,
  "message": "5 event(s) marked as processed"
}
```

#### c) Get Statistics
```http
GET /api/webhooks/stats?days=7

Response:
{
  "success": true,
  "stats": {
    "period_days": 7,
    "total": 1500,
    "processed": 1200,
    "pending": 300,
    "archived": 100,
    "by_model": [...],
    "by_priority": {...}
  }
}
```

#### d) Health Check
```http
GET /api/webhooks/health

Response:
{
  "status": "healthy",
  "version": "2.0.0",
  "module": "auto_webhook",
  "pending_events": 50,
  "timestamp": "2025-11-16T22:30:00"
}
```

---

### 4. المصادقة (Authentication)

**طريقة 1: API Key**
```bash
curl -H "X-API-Key: your-secret-api-key" \
  https://odoo.example.com/api/webhooks/pull
```

**إعداد API Key:**
```python
# في Odoo:
Settings > Technical > Parameters > System Parameters
Key: webhook.api_key
Value: your-secret-api-key-here
```

**طريقة 2: Session Authentication**
- استخدام session cookie من Odoo
- مناسب للاختبار من المتصفح

---

### 5. Cron Jobs للتنظيف

**الملف:** `data/update_webhook_cron.xml`

#### a) Cleanup Old Events (يومياً)
```xml
<record id="ir_cron_update_webhook_cleanup">
    <field name="name">Update Webhook: Cleanup Old Events</field>
    <field name="code">model.cleanup_old_events(days_to_archive=7, days_to_delete=30)</field>
    <field name="interval_number">1</field>
    <field name="interval_type">days</field>
</record>
```

**المنطق:**
- أرشفة الأحداث المُعالجة أقدم من 7 أيام
- حذف الأحداث المؤرشفة أقدم من 30 يوم

#### b) Archive Processed Events (كل 6 ساعات)
```xml
<record id="ir_cron_update_webhook_archive">
    <field name="name">Update Webhook: Archive Processed Events</field>
    <field name="code">model.cleanup_old_events(days_to_archive=3, days_to_delete=0)</field>
    <field name="interval_number">6</field>
    <field name="interval_type">hours</field>
</record>
```

---

## التثبيت والتحديث

### 1. تحديث Module

```bash
# Upgrade module
odoo-bin -u auto_webhook -d your_database

# أو من واجهة Odoo
Apps > Auto Webhook > Upgrade
```

### 2. التحقق من التثبيت

```python
# في Odoo shell
from odoo import api, SUPERUSER_ID

with api.Environment.manage():
    env = api.Environment(self.env.cr, SUPERUSER_ID, {})

    # التحقق من وجود update.webhook
    model = env['ir.model'].search([('model', '=', 'update.webhook')])
    print(f"Model exists: {bool(model)}")

    # التحقق من الـ indexes
    env.cr.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'update_webhook'
    """)
    indexes = [row[0] for row in env.cr.fetchall()]
    print(f"Indexes: {indexes}")
```

### 3. إنشاء API Key

```python
# في Odoo shell
env['ir.config_parameter'].set_param('webhook.api_key', 'your-super-secret-api-key-12345')
```

---

## أمثلة على الاستخدام

### مثال 1: BridgeCore Integration

```python
import requests
import time

API_URL = "https://odoo.example.com/api/webhooks/pull"
API_KEY = "your-api-key"
LAST_EVENT_ID = 0

while True:
    # Pull new events
    response = requests.get(
        API_URL,
        params={
            'last_event_id': LAST_EVENT_ID,
            'limit': 100,
        },
        headers={'X-API-Key': API_KEY}
    )

    data = response.json()

    if data['success'] and data['count'] > 0:
        events = data['events']

        # Process events
        for event in events:
            print(f"Processing event {event['id']}: {event['model']} - {event['event']}")
            # Your processing logic here

        # Mark as processed
        event_ids = [e['id'] for e in events]
        requests.post(
            f"{API_URL.replace('/pull', '/mark-processed')}",
            json={'event_ids': event_ids},
            headers={'X-API-Key': API_KEY}
        )

        # Update last ID
        LAST_EVENT_ID = data['last_id']

        # Check if there are more
        if not data['has_more']:
            print("No more events, waiting...")
            time.sleep(60)
    else:
        # No new events, wait
        time.sleep(60)
```

### مثال 2: Monitor High Priority Events

```python
import requests

response = requests.post(
    "https://odoo.example.com/api/webhooks/pull",
    json={
        'last_event_id': 0,
        'limit': 50,
        'priority': 'high'
    },
    headers={'X-API-Key': 'your-api-key'}
)

high_priority_events = response.json()['events']
for event in high_priority_events:
    print(f"⚠️ High priority: {event['model']} #{event['record_id']}")
```

---

## تحسينات الأداء

### 1. استخدام Indexes
جميع الاستعلامات الشائعة محسّنة بـ indexes:
- Pull query: `WHERE is_processed = false AND is_archived = false ORDER BY id`
- Cleanup query: `WHERE is_processed = true AND timestamp < cutoff`

### 2. Bulk Operations
```python
# Instead of:
for event_id in event_ids:
    event.mark_as_processed()

# Use:
env['update.webhook'].mark_batch_as_processed(event_ids)
```

### 3. Payload Size Monitoring
```python
# Get statistics
stats = env['update.webhook'].get_statistics(days=7)
print(f"Average payload size: {stats['avg_payload_size']} bytes")
```

---

## استكشاف الأخطاء

### 1. لا توجد أحداث في update.webhook

**الأسباب المحتملة:**
- webhook.config غير مفعّل للنموذج
- الـ event type غير مُفعّل في config
- خطأ في _write_to_update_webhook

**الحل:**
```python
# تفعيل webhook config
config = env['webhook.config'].search([('model_name', '=', 'sale.order')])
config.write({'enabled': True, 'events': 'create,write,unlink'})
```

### 2. API يُرجع 401 Unauthorized

**الأسباب:**
- API Key غير صحيح
- API Key غير موجود في system parameters

**الحل:**
```python
# إعداد/تحديث API Key
env['ir.config_parameter'].set_param('webhook.api_key', 'new-api-key')
```

### 3. الأداء بطيء

**الأسباب:**
- عدد كبير من الأحداث غير المُعالجة
- Indexes غير موجودة

**الحل:**
```sql
-- التحقق من الـ indexes
SELECT indexname FROM pg_indexes WHERE tablename = 'update_webhook';

-- إعادة بناء الـ indexes
REINDEX TABLE update_webhook;
```

---

## الفرق بين webhook.event و update.webhook

| Feature | webhook.event | update.webhook |
|---------|--------------|----------------|
| **الغرض** | إرسال Push-based | تخزين Pull-based |
| **متى يُنشأ** | فقط للأحداث الحرجة | دائماً لجميع الأحداث |
| **الإرسال** | Instant + Cron | لا يُرسل (Pull فقط) |
| **التنظيف** | حسب webhook_cron.xml | حسب update_webhook_cron.xml |
| **الحجم** | صغير (فقط الحرجة) | كبير (جميع الأحداث) |
| **الاستخدام** | للإشعارات الفورية | للتكامل مع BridgeCore |

---

## الخلاصة

### ✅ ما تم إنجازه:

1. ✅ Model جديد `update.webhook` مع indexes محسّنة
2. ✅ منطق Dual-Write في `webhook_mixin.py`
3. ✅ Pull API endpoints مع authentication
4. ✅ Cron jobs للتنظيف التلقائي
5. ✅ Views كاملة للإدارة من Odoo UI
6. ✅ Security rules وصلاحيات الأمان
7. ✅ توثيق شامل وأمثلة

### 🎯 معايير النجاح:

- ✅ يتم تسجيل جميع الأحداث في update.webhook
- ✅ الأحداث الحرجة تُرسل فوراً
- ✅ لا تأثير على أداء Odoo (<10ms للكتابة)
- ✅ BridgeCore يمكنه القراءة بسهولة عبر API
- ✅ سهولة الصيانة والتوسع

---

## المساهمة والدعم

للمزيد من المعلومات والدعم:
- GitHub: https://github.com/geniustep/auto-webhook-odoo
- Website: https://www.geniustep.com
- Email: support@geniustep.com

---

**النسخة:** 2.0.0
**آخر تحديث:** 2025-11-16
**المطوّر:** Odoo Zak, Geniustep
