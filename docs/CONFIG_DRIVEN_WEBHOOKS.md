# 🎯 Config-Driven Webhooks (v3.0)

## 📋 نظرة عامة

بدءاً من الإصدار 3.0، يدعم **auto-webhook-odoo** نظام **Config-Driven Webhooks** الذي يتيح لك:

- ✅ إضافة تتبع لأي model من الـ UI بدون كتابة كود
- ✅ تحديد العمليات المُراد تتبعها (create/write/unlink)
- ✅ فلترة السجلات باستخدام domains
- ✅ تتبع حقول محددة فقط
- ✅ إدارة مركزية لجميع القواعد

---

## 🏗️ الهيكل المعماري

```
                    ┌──────────────────────┐
                    │   Odoo UI            │
                    │   (webhook.rule)     │
                    └──────────┬───────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────┐
│                    Base Webhook Hook                      │
│              (_inherit = 'base')                          │
│                                                           │
│  create() ──┐                                             │
│  write()  ──┼──▶ _webhook_trigger() ──▶ webhook.rule     │
│  unlink() ──┘                                             │
└──────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   update.webhook     │
                    │   (Event Storage)    │
                    └──────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │   BridgeCore API     │
                    │   (Pull/Push)        │
                    └──────────────────────┘
```

---

## 🚀 كيفية الاستخدام

### إضافة Model جديد للتتبع

1. اذهب إلى: **Webhooks → Configuration → Rules**
2. اضغط **Create**
3. املأ الحقول:
   - **Rule Name**: اسم وصفي
   - **Model**: اختر الـ model (مثل `sale.order`)
   - **Operation**: `Create` / `Update` / `Delete`
   - **Priority**: `High` (فوري) / `Medium` / `Low`
   - **Subscribers**: اختر نقاط النهاية

4. اضغط **Save**

**هذا كل شيء!** 🎉 الآن سيتم تتبع هذا الـ model تلقائياً.

---

## ⚙️ خيارات متقدمة

### Domain Filter (تصفية السجلات)

فقط تتبع السجلات التي تطابق شرط معين:

```python
# فقط طلبات البيع المؤكدة
[('state', '=', 'sale')]

# فقط الفواتير المدفوعة
[('payment_state', '=', 'paid')]

# فقط العملاء النشطين
[('active', '=', True), ('customer_rank', '>', 0)]
```

### Tracked Fields (تتبع حقول محددة)

للـ write operations، فقط أرسل webhook إذا تغيرت هذه الحقول:

```
state, amount_total, partner_id
```

### Rate Limiting

- **Rate Limit**: حد أقصى للأحداث في الدقيقة (0 = بلا حد)
- **Debounce**: انتظر X ثانية قبل الإرسال (لتجميع التحديثات السريعة)

### Test Mode

فعّل **Test Mode** لتسجيل الأحداث بدون إرسالها فعلياً. مفيد للاختبار.

---

## 📊 القواعد الافتراضية

عند تثبيت الموديول، يتم إنشاء قواعد لـ 13 model تلقائياً:

| Model | Operations | Priority | Instant Send |
|-------|-----------|----------|--------------|
| `sale.order` | create, write, unlink | High | ✅ |
| `purchase.order` | create, write | High | ✅ |
| `account.move` | create, write | High | ✅ |
| `account.payment` | create, write | High | ✅ |
| `stock.picking` | create, write | Medium | ❌ |
| `stock.move` | write | Medium | ❌ |
| `res.partner` | create, write | Medium | ❌ |
| `product.template` | create, write | Low | ❌ |
| `product.category` | write | Low | ❌ |
| `hr.employee` | write | Low | ❌ |
| `hr.expense` | create, write | Medium | ❌ |

---

## 🔧 الأداء

### Smart Caching

النظام يستخدم cache ذكي لتجنب queries غير ضرورية:

```python
# Cache للـ models المتتبعة
WebhookRule._tracked_models = {'sale.order', 'res.partner', ...}

# Cache للقواعد
WebhookRule._rules_cache = {
    'sale.order:create': [rule_id_1, rule_id_2],
    'sale.order:write': [rule_id_3],
    ...
}
```

### Early Exit

```python
def write(self, vals):
    result = super().write(vals)
    
    # ⚡ O(1) check - لا DB query
    if self._name not in tracked_models:
        return result
    
    # Only then check rules...
```

### تعطيل Webhooks مؤقتاً

```python
# في batch operations أو scripts
with self.env.cr.savepoint():
    records.with_context(webhook_disabled=True).write({...})
```

---

## 🔄 الفرق عن النظام القديم

| الجانب | النظام القديم (v2) | النظام الجديد (v3) |
|--------|-------------------|-------------------|
| إضافة model | تعديل كود Python | UI فقط |
| إعادة تشغيل | مطلوب | غير مطلوب |
| مرونة | محدودة | عالية جداً |
| صيانة | صعبة | سهلة |
| Domain filters | ❌ | ✅ |
| Field tracking | ❌ | ✅ |

---

## 📝 أمثلة عملية

### مثال 1: تتبع طلبات البيع المؤكدة فقط

```
Model: sale.order
Operation: write
Domain: [('state', '=', 'sale')]
Tracked Fields: state, amount_total
Priority: High
Instant Send: ✅
```

### مثال 2: تتبع المنتجات عند تغيير السعر

```
Model: product.template
Operation: write
Domain: []
Tracked Fields: list_price, standard_price
Priority: Medium
Instant Send: ❌
```

### مثال 3: تتبع العملاء الجدد

```
Model: res.partner
Operation: create
Domain: [('customer_rank', '>', 0)]
Priority: Medium
Instant Send: ❌
```

---

## 🛠️ إدارة Cache

### تحديث Cache يدوياً

من واجهة الـ rule:
1. افتح أي rule
2. اضغط **Refresh Cache**

أو من Python:
```python
self.env['webhook.rule']._rebuild_cache()
```

### متى يتم Invalidate تلقائياً؟

- عند إنشاء rule جديدة
- عند تعديل rule
- عند حذف rule
- عند تغيير active status

---

## ⚠️ ملاحظات هامة

1. **القواعد القديمة**: الـ models الموجودة في `list_model.py` ستستمر بالعمل مؤقتاً.
   يُنصح بتفعيل القواعد الجديدة وتعطيل القديمة تدريجياً.

2. **Unique Constraint**: لا يمكن وجود rule مكررة (نفس model + operation + active).

3. **الأداء**: Hook على `base` يضيف overhead ~0.01ms لكل عملية CRUD.
   هذا مقبول في معظم الحالات.

4. **Error Handling**: فشل webhook لا يؤثر على العملية الأصلية.
   الأخطاء تُسجل في logs فقط.

---

## 🔗 روابط مفيدة

- [OCA Auditlog](https://github.com/OCA/server-tools/tree/16.0/auditlog) - الإلهام الأصلي
- [BridgeCore Integration](./INTEGRATION_GUIDE.md)
- [API Documentation](./API_ENDPOINTS.md)

---

**آخر تحديث**: نوفمبر 2025  
**الإصدار**: 3.0.0  
**الحالة**: ✅ Production Ready

---

*Made with ❤️ by Geniustep Team*

