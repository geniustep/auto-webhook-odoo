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
        
        # معالجة webhook لكل سجل
        for record in self:
            try:
                record._process_webhook_event('write', vals)
            except Exception as e:
                _logger.error(f"Webhook processing failed for {record._name}.write: {str(e)}")
        
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
        معالجة حدث webhook
        
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
        
        # الحصول على المشتركين المفعّلين
        subscribers = config.subscriber_ids.filtered(lambda s: s.enabled)
        
        if not subscribers:
            _logger.warning(f"No active subscribers for {self._name}")
            return
        
        # إنشاء events لكل مشترك
        for subscriber in subscribers:
            try:
                # تحضير البيانات
                payload_data = self._prepare_webhook_data(changed_vals)
                
                # إنشاء event
                event = self.env['webhook.event'].create({
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
                
                # إرسال فوري إذا كان مفعّل
                if config.instant_send:
                    self._trigger_webhook_instant(event)
                    
            except Exception as e:
                _logger.error(f"Failed to create webhook event for {subscriber.name}: {str(e)}")

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
        معالجة webhook للسجلات المحذوفة
        
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
        
        # الحصول على المشتركين
        subscribers = config.subscriber_ids.filtered(lambda s: s.enabled)
        
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
                if config.instant_send:
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
        
        config = self.env['webhook.config'].get_config_for_model(self._name)
        
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
                
                value = getattr(self, field_name, None)
                
                # معالجة أنواع الحقول المختلفة
                if field.type in ['many2one']:
                    data[field_name] = {
                        'id': value.id if value else False,
                        'name': value.display_name if value else ''
                    }
                elif field.type in ['one2many', 'many2many']:
                    data[field_name] = [{'id': r.id, 'name': r.display_name} for r in value]
                elif field.type == 'datetime':
                    data[field_name] = value.isoformat() if value else False
                elif field.type == 'date':
                    data[field_name] = value.isoformat() if value else False
                elif field.type == 'binary':
                    # تجنب إرسال البيانات الثنائية الكبيرة
                    data[field_name] = bool(value)
                else:
                    data[field_name] = value
                    
            except Exception as e:
                _logger.warning(f"Failed to get field {field_name}: {str(e)}")
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