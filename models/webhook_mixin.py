# -*- coding: utf-8 -*-

from odoo import models, fields, api  # pyright: ignore[reportMissingImports]
import logging

_logger = logging.getLogger(__name__)


class WebhookMixin(models.AbstractModel):
    """
    Mixin class لإضافة وظائف webhook لأي نموذج
    يوفر تتبع تلقائي للأحداث (create, write, unlink)
    """
    _name = 'webhook.mixin'
    _description = 'Webhook Mixin for Automatic Event Tracking'

    # علامة لتتبع ما إذا كان السجل قد تم معالجته
    _webhook_processed = False

    @api.model_create_multi
    def create(self, vals_list):
        """Override create للتتبع التلقائي"""
        records = super(WebhookMixin, self).create(vals_list)
        
        # معالجة webhook لكل سجل
        for record in records:
            try:
                record._process_webhook_event('create')
            except Exception as e:
                _logger.error(f"Webhook processing failed for {record._name}.create: {str(e)}")
        
        return records

    def write(self, vals):
        """Override write للتتبع التلقائي"""
        result = super(WebhookMixin, self).write(vals)
        
        # الحل: كتابة في update.webhook فقط (بدون webhook.event)
        # webhook.event سيتم إنشاؤه لاحقاً بواسطة cron job من update.webhook
        # هذا يضمن أن write() سريع ولا يسبب مشاكل
        
        for record in self:
            try:
                # التحقق من حالة transaction
                try:
                    self.env.cr.execute("SELECT 1")
                except Exception:
                    _logger.warning(f"Transaction in failed state, skipping webhook for {record._name}:{record.id}")
                    continue
                
                # فقط كتابة في update.webhook (سريع وآمن)
                # استخدام sudo() لتجنب مشاكل الصلاحيات
                try:
                    # التحقق من وجود webhook.config
                    if 'webhook.config' not in self.env:
                        continue
                    
                    # استخدام sudo() للحصول على config
                    config = self.env['webhook.config'].sudo().get_config_for_model(record._name)
                    if not config or not config.enabled:
                        continue
                    
                    if 'write' not in config.events.split(','):
                        continue
                    
                    # استخدام sudo() لتحضير البيانات وتجنب مشاكل الصلاحيات
                    record_sudo = record.sudo()
                    
                    # تحضير البيانات بشكل آمن
                    # استخدام getattr للتحقق من وجود method
                    if not hasattr(record_sudo, '_prepare_webhook_data'):
                        _logger.warning(f"_prepare_webhook_data not found for {record._name}:{record.id}")
                        continue
                    
                    try:
                        payload_data = record_sudo._prepare_webhook_data(vals)
                    except AttributeError:
                        _logger.warning(f"Cannot access _prepare_webhook_data for {record._name}:{record.id}")
                        continue
                    except Exception as e:
                        _logger.warning(f"Failed to prepare webhook data for {record._name}:{record.id}: {str(e)}")
                        continue
                    
                    # التحقق من وجود _write_to_update_webhook
                    if not hasattr(record_sudo, '_write_to_update_webhook'):
                        _logger.warning(f"_write_to_update_webhook not found for {record._name}:{record.id}")
                        continue
                    
                    # كتابة في update.webhook فقط (باستخدام sudo)
                    try:
                        record_sudo._write_to_update_webhook('write', payload_data, config)
                    except AttributeError:
                        _logger.warning(f"Cannot access _write_to_update_webhook for {record._name}:{record.id}")
                    except Exception as e:
                        _logger.error(f"Failed to write to update.webhook for {record._name}:{record.id}: {str(e)}", exc_info=True)
                except Exception as e:
                    _logger.error(f"Webhook config check failed for {record._name}:{record.id}: {str(e)}", exc_info=True)
                    # لا نرفع الخطأ - نستمر
            except Exception as e:
                _logger.error(f"Webhook processing failed for {record._name}:{record.id}: {str(e)}", exc_info=True)
                # لا نرفع الخطأ - نستمر
        
        return result

    def unlink(self):
        """Override unlink للتتبع التلقائي"""
        # حفظ بيانات السجلات قبل الحذف
        records_data = []
        for record in self:
            try:
                records_data.append({
                    'record': record,
                    'data': record._prepare_webhook_data()
                })
            except Exception as e:
                _logger.error(f"Failed to prepare data for {record._name}.unlink: {str(e)}")
        
        # حذف السجلات
        result = super(WebhookMixin, self).unlink()
        
        # معالجة webhook بعد الحذف
        for record_info in records_data:
            try:
                self._process_webhook_event_for_unlinked(
                    record_info['record'],
                    record_info['data']
                )
            except Exception as e:
                _logger.error(f"Webhook processing failed for unlink: {str(e)}")
        
        return result

    def _process_webhook_event(self, event_type, changed_vals=None):
        """
        معالجة حدث webhook مع Dual-Write Strategy

        Strategy:
        1. دائماً: كتابة في update.webhook (للـ Pull-based access)
        2. اختيارياً: كتابة في webhook.event (للإرسال الفوري للأحداث الحرجة)

        Args:
            event_type: نوع الحدث (create/write/unlink)
            changed_vals: القيم المتغيرة (للـ write فقط)
        """
        self.ensure_one()

        # الحصول على config الخاص بالنموذج
        config = self.env['webhook.config'].get_config_for_model(self._name)

        if not config or not config.enabled:
            _logger.debug(f"Webhook disabled for model {self._name}")
            return

        # التحقق من نوع الحدث مفعّل
        if event_type not in config.events.split(','):
            _logger.debug(f"Event type {event_type} not enabled for {self._name}")
            return

        # تحضير البيانات مرة واحدة
        try:
            payload_data = self._prepare_webhook_data(changed_vals)
        except Exception as e:
            _logger.error(f"Failed to prepare webhook data for {self._name}:{self.id}: {str(e)}", exc_info=True)
            # لا نرفع الخطأ - نعود بدون معالجة webhook
            return

        # === STEP 1: كتابة في update.webhook (دائماً) ===
        try:
            self._write_to_update_webhook(event_type, payload_data, config)
            _logger.debug(f"Written to update.webhook: {self._name}:{self.id} ({event_type})")
        except Exception as e:
            _logger.error(f"Failed to write to update.webhook for {self._name}:{self.id}: {str(e)}", exc_info=True)
            # لا نوقف المعالجة حتى لو فشلت الكتابة في update.webhook
            # نستمر في محاولة إنشاء webhook.event إذا لزم الأمر

        # === STEP 2: قرار الإرسال الفوري ===
        # إرسال فوري فقط إذا:
        # - instant_send مفعّل AND priority = high
        # - أو إذا كان هناك مشتركين نشطين

        try:
            subscribers = config.subscriber_ids.filtered(lambda s: s.enabled)
        except Exception as e:
            _logger.error(f"Failed to get subscribers for {self._name}:{self.id}: {str(e)}", exc_info=True)
            return

        if not subscribers:
            _logger.debug(f"No active subscribers for {self._name}, skipping webhook.event creation")
            return

        # قرار: هل نرسل فوراً؟
        should_send_instant = config.instant_send and config.priority == 'high'

        # إنشاء webhook.event فقط إذا كان هناك مشتركين
        # (للأحداث الحرجة أو حسب الحاجة)
        if should_send_instant or config.instant_send:
            # إنشاء events لكل مشترك
            for subscriber in subscribers:
                try:
                    # إنشاء event
                    event = self.env['webhook.event'].sudo().create({
                        'model': self._name,
                        'record_id': self.id,
                        'event': event_type,
                        'config_id': config.id,
                        'subscriber_id': subscriber.id,
                        'priority': config.priority,
                        'payload': payload_data,
                        'status': 'pending',
                    })

                    _logger.info(f"Webhook event created: {event.id} for {self._name}:{self.id}")

                    # إرسال فوري للأحداث الحرجة
                    if should_send_instant:
                        try:
                            self._trigger_webhook_instant(event)
                        except Exception as e:
                            _logger.error(f"Failed to trigger instant webhook for event {event.id}: {str(e)}", exc_info=True)

                except Exception as e:
                    _logger.error(f"Failed to create webhook event for {subscriber.name} ({self._name}:{self.id}): {str(e)}", exc_info=True)
                    # نستمر في محاولة إنشاء events للمشتركين الآخرين

    def _write_to_update_webhook(self, event_type, payload_data, config):
        """
        كتابة الحدث في جدول update.webhook

        هذه الـ method مصممة لتكون سريعة جداً (<10ms) ولا تعيق العمليات الأساسية

        Args:
            event_type: نوع الحدث (create/write/unlink)
            payload_data: البيانات الكاملة
            config: webhook.config record

        Returns:
            update.webhook record or False
        """
        try:
            # استخدام create_event السريعة
            # sudo() لتجنب مشاكل الصلاحيات أثناء الـ write
            update_webhook = self.env['update.webhook'].sudo().create_event(
                model_name=self._name,
                record_id=self.id,
                event_type=event_type,
                payload_data=payload_data,
                config=config
            )

            return update_webhook

        except Exception as e:
            _logger.error(f"Failed to write to update.webhook for {self._name}:{self.id}: {str(e)}")
            return False

    def _trigger_webhook_instant(self, event):
        """
        إرسال webhook فوري بدون انتظار Cron

        Args:
            event: webhook.event record
        """
        try:
            # التحقق من حالة الـ event
            if event.status != 'pending':
                return

            _logger.info(f"Triggering instant webhook for event {event.id}")

            # Commit التغييرات الحالية قبل الإرسال
            self.env.cr.commit()

            # إرسال الـ event
            event._send_to_subscriber()

            _logger.info(f"Instant webhook sent successfully: {event.id}")

        except Exception as e:
            _logger.error(f"Instant webhook trigger failed for event {event.id}: {str(e)}")
            # في حالة الفشل، سيتم إعادة المحاولة عبر Cron

    def _process_webhook_event_for_unlinked(self, record, data):
        """
        معالجة webhook للسجلات المحذوفة مع Dual-Write Strategy

        Args:
            record: السجل المحذوف
            data: بيانات السجل قبل الحذف
        """
        # الحصول على config
        config = self.env['webhook.config'].get_config_for_model(record._name)

        if not config or not config.enabled:
            return

        # التحقق من نوع الحدث
        if 'unlink' not in config.events.split(','):
            return

        # === STEP 1: كتابة في update.webhook (دائماً) ===
        try:
            self.env['update.webhook'].sudo().create_event(
                model_name=record._name,
                record_id=record.id,
                event_type='unlink',
                payload_data=data,
                config=config
            )
            _logger.debug(f"Written to update.webhook: {record._name}:{record.id} (unlink)")
        except Exception as e:
            _logger.error(f"Failed to write unlink to update.webhook: {str(e)}")

        # === STEP 2: قرار الإرسال الفوري ===
        subscribers = config.subscriber_ids.filtered(lambda s: s.enabled)

        if not subscribers:
            return

        should_send_instant = config.instant_send and config.priority == 'high'

        if should_send_instant or config.instant_send:
            for subscriber in subscribers:
                try:
                    # إنشاء event
                    event = self.env['webhook.event'].create({
                        'model': record._name,
                        'record_id': record.id,
                        'event': 'unlink',
                        'config_id': config.id,
                        'subscriber_id': subscriber.id,
                        'priority': config.priority,
                        'payload': data,
                        'status': 'pending',
                    })

                    # إرسال فوري إذا كان مفعّل
                    if should_send_instant:
                        # استخدام self بدلاً من record (المحذوف)
                        self._trigger_webhook_instant(event)

                except Exception as e:
                    _logger.error(f"Failed to create unlink webhook event: {str(e)}")

    def _prepare_webhook_data(self, changed_vals=None):
        """
        تحضير بيانات الـ payload
        
        Args:
            changed_vals: القيم المتغيرة (للـ write فقط)
            
        Returns:
            dict: البيانات المُحضّرة
        """
        self.ensure_one()
        
        # استخدام sudo() لتجنب مشاكل الصلاحيات
        config = self.env['webhook.config'].sudo().get_config_for_model(self._name)
        
        # الحصول على الحقول المطلوبة
        if config and config.filtered_fields:
            fields_to_include = [f.strip() for f in config.filtered_fields.split(',')]
        else:
            # جميع الحقول القابلة للقراءة
            fields_to_include = [
                f for f in self._fields.keys()
                if not f.startswith('_') and f not in ['create_uid', 'write_uid', '__last_update']
            ]
        
        # تحضير البيانات
        data = {}
        for field_name in fields_to_include:
            try:
                field = self._fields.get(field_name)
                if not field:
                    continue
                
                # تخطي الحقول المحسوبة التي قد تسبب مشاكل
                if field.compute and not field.store:
                    continue
                
                # تخطي الحقول الثنائية الكبيرة
                if field.type == 'binary':
                    data[field_name] = bool(getattr(self, field_name, None))
                    continue
                
                value = getattr(self, field_name, None)
                
                # معالجة أنواع الحقول المختلفة
                if field.type in ['many2one']:
                    data[field_name] = {
                        'id': value.id if value else False,
                        'name': value.display_name if value else ''
                    }
                elif field.type in ['one2many', 'many2many']:
                    # تقليل البيانات المرسلة
                    data[field_name] = [{'id': r.id, 'name': r.display_name} for r in value[:100]]  # حد أقصى 100
                elif field.type == 'datetime':
                    data[field_name] = value.isoformat() if value else False
                elif field.type == 'date':
                    data[field_name] = value.isoformat() if value else False
                else:
                    data[field_name] = value
                    
            except Exception as e:
                _logger.warning(f"Failed to get field {field_name} for {self._name}:{self.id}: {str(e)}")
                data[field_name] = None
        
        # إضافة معلومات إضافية
        data['_metadata'] = {
            'model': self._name,
            'id': self.id,
            'display_name': self.display_name,
            'create_date': self.create_date.isoformat() if self.create_date else None,
            'write_date': self.write_date.isoformat() if self.write_date else None,
        }
        
        # إضافة الحقول المتغيرة فقط (للـ write)
        if changed_vals:
            data['_changed_fields'] = list(changed_vals.keys())
        
        return data

    def _get_webhook_config(self):
        """الحصول على إعدادات webhook للنموذج الحالي"""
        self.ensure_one()
        return self.env['webhook.config'].get_config_for_model(self._name)