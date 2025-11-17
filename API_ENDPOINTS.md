# 🔌 API Endpoints Documentation

## 📋 نظرة عامة

هذا الملف يوثق جميع الـ API endpoints المطلوبة في مشروع **Auto Webhook** للتكامل مع BridgeCore والتطبيقات الخارجية.

---

## 🔐 المصادقة (Authentication)

جميع الـ endpoints تتطلب مصادقة باستخدام أحد الطرق التالية:

### 1. API Key (مُوصى به)
```http
X-API-Key: your-secret-api-key-here
```

**الإعداد:**
- `Settings → Technical → Parameters → System Parameters`
- Key: `webhook.api_key`
- Value: `your-secret-api-key-here`

### 2. Session Authentication
- استخدام session cookie من Odoo
- مناسب للاختبار من المتصفح

---

## 📡 Pull-Based API Endpoints

### 1. Pull Events - سحب الأحداث

**Endpoint:** `GET/POST /api/webhooks/pull`

**الوصف:** سحب الأحداث من جدول `update.webhook` (Pull-based)

**المصادقة:** مطلوبة (API Key أو Session)

**Parameters (GET):**
```
?last_event_id=0          # آخر ID تم سحبه (default: 0)
&limit=100                # عدد الأحداث (default: 100, max: 1000)
&models=sale.order,product.template  # تصفية حسب النماذج (اختياري)
&priority=high            # تصفية حسب الأولوية (high/medium/low) (اختياري)
```

**Body (POST):**
```json
{
  "last_event_id": 0,
  "limit": 100,
  "models": ["sale.order", "product.template"],
  "priority": "high"
}
```

**Response:**
```json
{
  "success": true,
  "events": [
    {
      "id": 101,
      "model": "sale.order",
      "record_id": 336,
      "event": "write",
      "payload": {
        "name": "SO001",
        "amount_total": 1000.0,
        "state": "sale"
      },
      "created_at": "2025-11-16T22:30:00",
      "priority": "high"
    }
  ],
  "last_id": 200,
  "has_more": true,
  "count": 100,
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
# GET Request
curl -X GET "https://odoo.example.com/api/webhooks/pull?last_event_id=0&limit=100" \
  -H "X-API-Key: your-api-key"

# POST Request
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

---

### 2. Mark as Processed - تحديد الأحداث كمُعالجة

**Endpoint:** `POST /api/webhooks/mark-processed`

**الوصف:** تحديد قائمة من الأحداث كمُعالجة بعد استلامها من BridgeCore

**المصادقة:** مطلوبة

**Body:**
```json
{
  "event_ids": [101, 102, 103, 104, 105]
}
```

**Response:**
```json
{
  "success": true,
  "processed_count": 5,
  "message": "5 event(s) marked as processed",
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X POST "https://odoo.example.com/api/webhooks/mark-processed" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "event_ids": [101, 102, 103, 104, 105]
  }'
```

---

### 3. Get Statistics - الحصول على الإحصائيات

**Endpoint:** `GET /api/webhooks/stats`

**الوصف:** الحصول على إحصائيات شاملة عن الأحداث

**المصادقة:** مطلوبة

**Parameters:**
```
?days=7  # عدد الأيام للرجوع (default: 7)
```

**Response:**
```json
{
  "success": true,
  "stats": {
    "period_days": 7,
    "total": 1500,
    "processed": 1200,
    "pending": 300,
    "archived": 100,
    "by_model": [
      {
        "model": "sale.order",
        "count": 500,
        "processed": 450,
        "pending": 50
      },
      {
        "model": "product.template",
        "count": 300,
        "processed": 250,
        "pending": 50
      }
    ],
    "by_priority": {
      "high": 800,
      "medium": 500,
      "low": 200
    }
  },
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X GET "https://odoo.example.com/api/webhooks/stats?days=30" \
  -H "X-API-Key: your-api-key"
```

---

### 4. Health Check - فحص الحالة

**Endpoint:** `GET /api/webhooks/health`

**الوصف:** فحص حالة النظام وعدد الأحداث المعلقة

**المصادقة:** غير مطلوبة (public)

**Response:**
```json
{
  "status": "healthy",
  "version": "2.1.0",
  "module": "auto_webhook",
  "pending_events": 50,
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X GET "https://odoo.example.com/api/webhooks/health"
```

---

### 5. CORS Options - معالجة CORS Preflight

**Endpoint:** `OPTIONS /api/webhooks/*`

**الوصف:** معالجة طلبات CORS preflight للسماح بالوصول من المتصفحات

**Response Headers:**
```
Access-Control-Allow-Origin: *
Access-Control-Allow-Methods: GET, POST, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-API-Key
Access-Control-Max-Age: 86400
```

---

## 👤 User Sync State API Endpoints

### 6. Get or Create Sync State - الحصول على أو إنشاء حالة المزامنة

**Endpoint:** `GET/POST /api/webhooks/sync-state`

**الوصف:** الحصول على حالة المزامنة لمستخدم/جهاز معين أو إنشاء واحدة جديدة

**المصادقة:** مطلوبة

**Parameters (GET):**
```
?user_id=117              # ID المستخدم (مطلوب)
&device_id=abc123         # معرف الجهاز (مطلوب)
&app_type=sales_app       # نوع التطبيق (اختياري, default: mobile_app)
```

**Body (POST):**
```json
{
  "user_id": 117,
  "device_id": "abc123",
  "app_type": "sales_app",
  "device_info": "Android 13, Samsung Galaxy S21",
  "app_version": "1.0.0"
}
```

**Response:**
```json
{
  "success": true,
  "sync_state": {
    "id": 1,
    "user_id": 117,
    "device_id": "abc123",
    "app_type": "sales_app",
    "last_event_id": 500,
    "last_sync_time": "2025-11-16T22:00:00",
    "sync_count": 25,
    "total_events_synced": 500,
    "is_active": true
  },
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X POST "https://odoo.example.com/api/webhooks/sync-state" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "user_id": 117,
    "device_id": "abc123",
    "app_type": "sales_app"
  }'
```

---

### 7. Update Sync State - تحديث حالة المزامنة

**Endpoint:** `POST /api/webhooks/sync-state/update`

**الوصف:** تحديث حالة المزامنة بعد سحب الأحداث

**المصادقة:** مطلوبة

**Body:**
```json
{
  "user_id": 117,
  "device_id": "abc123",
  "last_event_id": 600,
  "events_synced": 100
}
```

**Response:**
```json
{
  "success": true,
  "sync_state": {
    "id": 1,
    "last_event_id": 600,
    "last_sync_time": "2025-11-16T22:30:00",
    "sync_count": 26,
    "total_events_synced": 600
  },
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X POST "https://odoo.example.com/api/webhooks/sync-state/update" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "user_id": 117,
    "device_id": "abc123",
    "last_event_id": 600,
    "events_synced": 100
  }'
```

---

### 8. Get Sync Statistics - الحصول على إحصائيات المزامنة

**Endpoint:** `GET /api/webhooks/sync-state/stats`

**الوصف:** الحصول على إحصائيات المزامنة لمستخدم معين

**المصادقة:** مطلوبة

**Parameters:**
```
?user_id=117              # ID المستخدم (مطلوب)
&device_id=abc123         # معرف الجهاز (اختياري)
&app_type=sales_app       # نوع التطبيق (اختياري)
```

**Response:**
```json
{
  "success": true,
  "stats": {
    "user_id": 117,
    "total_devices": 2,
    "active_devices": 1,
    "total_syncs": 50,
    "total_events_synced": 5000,
    "last_sync_time": "2025-11-16T22:30:00",
    "devices": [
      {
        "device_id": "abc123",
        "app_type": "sales_app",
        "last_sync_time": "2025-11-16T22:30:00",
        "sync_count": 25,
        "total_events_synced": 2500,
        "is_active": true
      }
    ]
  },
  "timestamp": "2025-11-16T22:30:00"
}
```

**مثال على الاستخدام:**
```bash
curl -X GET "https://odoo.example.com/api/webhooks/sync-state/stats?user_id=117" \
  -H "X-API-Key: your-api-key"
```

---

## 🔄 Push-Based Webhook Endpoints (BridgeCore)

### 9. BridgeCore Webhook Receiver (اختياري)

**Endpoint:** `POST https://api.bridgecore.ma/webhook`

**الوصف:** هذا هو الـ endpoint الذي يستقبل الأحداث من Odoo (يتم إرسالها من Odoo إلى BridgeCore)

**ملاحظة:** هذا الـ endpoint موجود في BridgeCore، وليس في Odoo. Odoo يرسل الأحداث إلى هذا الـ endpoint.

**الإعداد في Odoo:**
- `Webhooks → Configuration → Subscribers`
- اختر `BridgeCore Default Endpoint`
- URL: `https://api.bridgecore.ma/webhook`
- Auth Type: `Bearer Token` (إذا لزم الأمر)

---

## 📊 ملخص الـ Endpoints

| # | Endpoint | Method | Auth | الوصف |
|---|----------|--------|------|-------|
| 1 | `/api/webhooks/pull` | GET/POST | ✅ | سحب الأحداث من `update.webhook` |
| 2 | `/api/webhooks/mark-processed` | POST | ✅ | تحديد الأحداث كمُعالجة |
| 3 | `/api/webhooks/stats` | GET | ✅ | الحصول على الإحصائيات |
| 4 | `/api/webhooks/health` | GET | ❌ | فحص الحالة |
| 5 | `/api/webhooks/options` | OPTIONS | ❌ | CORS preflight |
| 6 | `/api/webhooks/sync-state` | GET/POST | ✅ | الحصول على/إنشاء حالة المزامنة |
| 7 | `/api/webhooks/sync-state/update` | POST | ✅ | تحديث حالة المزامنة |
| 8 | `/api/webhooks/sync-state/stats` | GET | ✅ | إحصائيات المزامنة |

---

## 🚀 سيناريوهات الاستخدام

### السيناريو 1: Pull Events (BridgeCore)

```bash
# 1. الحصول على حالة المزامنة
SYNC_STATE=$(curl -X POST "https://odoo.example.com/api/webhooks/sync-state" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d '{
    "user_id": 117,
    "device_id": "abc123",
    "app_type": "sales_app"
  }')

LAST_EVENT_ID=$(echo $SYNC_STATE | jq -r '.sync_state.last_event_id')

# 2. سحب الأحداث الجديدة
EVENTS=$(curl -X GET "https://odoo.example.com/api/webhooks/pull?last_event_id=$LAST_EVENT_ID&limit=100" \
  -H "X-API-Key: your-api-key")

# 3. معالجة الأحداث في BridgeCore
# ... process events ...

# 4. تحديد الأحداث كمُعالجة
EVENT_IDS=$(echo $EVENTS | jq -r '.events[].id')
curl -X POST "https://odoo.example.com/api/webhooks/mark-processed" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d "{\"event_ids\": $EVENT_IDS}"

# 5. تحديث حالة المزامنة
NEW_LAST_ID=$(echo $EVENTS | jq -r '.last_id')
curl -X POST "https://odoo.example.com/api/webhooks/sync-state/update" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your-api-key" \
  -d "{
    \"user_id\": 117,
    \"device_id\": \"abc123\",
    \"last_event_id\": $NEW_LAST_ID,
    \"events_synced\": $(echo $EVENTS | jq -r '.count')
  }"
```

### السيناريو 2: Health Monitoring

```bash
# فحص الحالة كل 5 دقائق
while true; do
  HEALTH=$(curl -s "https://odoo.example.com/api/webhooks/health")
  STATUS=$(echo $HEALTH | jq -r '.status')
  PENDING=$(echo $HEALTH | jq -r '.pending_events')
  
  if [ "$STATUS" != "healthy" ] || [ "$PENDING" -gt 1000 ]; then
    echo "⚠️ Alert: Status=$STATUS, Pending=$PENDING"
    # إرسال تنبيه
  fi
  
  sleep 300
done
```

---

## ⚠️ ملاحظات مهمة

1. **Rate Limiting**: يُنصح بتطبيق rate limiting على الـ endpoints
2. **SSL/TLS**: استخدم HTTPS دائماً في الإنتاج
3. **API Key Security**: احفظ API keys بشكل آمن ولا تشاركها
4. **Error Handling**: تعامل مع الأخطاء بشكل صحيح
5. **Logging**: سجّل جميع الطلبات للأغراض الأمنية

---

## 🔧 التطوير المستقبلي

### Endpoints مُخطط لها (لم تُنفذ بعد):

1. **Webhook Event Replay**
   - `POST /api/webhooks/replay` - إعادة إرسال حدث معين

2. **Webhook Configuration Management**
   - `GET /api/webhooks/configs` - الحصول على جميع الإعدادات
   - `POST /api/webhooks/configs` - إنشاء/تحديث إعداد

3. **Webhook Subscriber Management**
   - `GET /api/webhooks/subscribers` - الحصول على جميع المشتركين
   - `POST /api/webhooks/subscribers/test` - اختبار اتصال مشترك

4. **Webhook Event Search**
   - `GET /api/webhooks/search` - البحث في الأحداث

---

**آخر تحديث**: نوفمبر 2025  
**الإصدار**: 2.1.0

