# -*- coding: utf-8 -*-
"""
Base Webhook Hook - Universal Event Tracking

This module provides a universal hook on the 'base' model that automatically
tracks CRUD operations for any model that has an active webhook.rule.

Key Features:
- Single hook for all models (no inheritance needed)
- Fast early-exit for non-tracked models
- Thread-safe caching
- Fail-safe error handling (never blocks business operations)
- Context-based disabling for batch operations

Usage:
- Create webhook.rule for a model from UI
- Hook automatically triggers webhooks
- No code changes needed per model

Performance:
- Uses class-level cache for tracked models
- Early exit if model not tracked (~0.01ms overhead)
- Lazy loading of rules only when needed
"""

from odoo import models, api, fields
import logging
import threading
import time

_logger = logging.getLogger(__name__)


class BaseWebhookHook(models.AbstractModel):
    """
    Universal Webhook Hook on base model
    
    Intercepts create/write/unlink on ALL models and checks
    if there's an active webhook.rule for the model.
    """
    _inherit = 'base'
    
    # ═══════════════════════════════════════════════════════════
    # Debouncing Cache (Thread-safe)
    # Prevents multiple webhook triggers for same record within short time
    # ═══════════════════════════════════════════════════════════
    
    _webhook_debounce_cache = {}  # {model:record_id: timestamp}
    _webhook_debounce_lock = threading.Lock()
    _DEBOUNCE_SECONDS = 3  # Don't trigger again within 3 seconds

    # ═══════════════════════════════════════════════════════════
    # CRUD Overrides
    # ═══════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create to trigger webhooks based on rules
        """
        # Execute original create
        records = super().create(vals_list)
        
        # Trigger webhook immediately (not after_commit) with debouncing
        if records and not self.env.context.get('webhook_disabled'):
            try:
                for record in records:
                    if record.exists() and record.id:
                        # Check debounce before triggering
                        if self._webhook_should_trigger(record._name, record.id, 'create'):
                            self._webhook_trigger_create(record)
            except Exception as e:
                _logger.error(f'Webhook trigger failed for create: {e}', exc_info=True)
        
        return records

    def write(self, vals):
        """
        Override write to trigger webhooks based on rules
        With debouncing to prevent multiple events for same record
        """
        # Skip write events if we're in create context
        if self.env.context.get('skip_webhook_write'):
            return super().write(vals)
        
        # Execute original write
        result = super().write(vals)
        
        # Trigger webhook (fail-safe) with debouncing
        if not self.env.context.get('webhook_disabled'):
            try:
                # Filter records that pass debounce check
                records_to_trigger = self.filtered(
                    lambda r: self._webhook_should_trigger(r._name, r.id, 'write')
                )
                
                if records_to_trigger:
                    records_to_trigger._webhook_trigger_write(vals)
            except Exception as e:
                _logger.error(f'Webhook trigger failed for write: {e}')
        
        return result

    def unlink(self):
        """
        Override unlink to trigger webhooks based on rules
        """
        # Capture data before deletion
        records_data = []
        try:
            records_data = self._webhook_capture_for_unlink()
        except Exception as e:
            _logger.error(f'Failed to capture data for unlink webhook: {e}')
        
        # Execute original unlink
        result = super().unlink()
        
        # Trigger webhook (fail-safe)
        try:
            self._webhook_trigger_unlink(records_data)
        except Exception as e:
            _logger.error(f'Webhook trigger failed for unlink: {e}')
        
        return result

    # ═══════════════════════════════════════════════════════════
    # Webhook Trigger Methods
    # ═══════════════════════════════════════════════════════════

    def _webhook_trigger_create(self, record):
        """
        Trigger webhooks for created record
        
        Supports both webhook.rule and webhook.config based tracking.
        
        Args:
            record: Created record (single record)
        """
        # Early exit: Check if webhooks are disabled via context
        if self.env.context.get('webhook_disabled'):
            return
        
        # Early exit: Check if this model is tracked
        if not record._webhook_is_model_tracked():
            return
        
        # Ensure record has valid ID
        if not record.id or isinstance(record.id, models.NewId):
            _logger.warning(
                f'Skipping webhook for {record._name}: '
                f'Record has no valid ID (id={record.id})'
            )
            return
        
        # Method 1: Try webhook.rule based triggering
        rules = record._webhook_get_rules('create')
        rules_triggered = False
        
        if rules:
            for rule in rules:
                try:
                    # Check domain filter
                    if not rule._match_domain(record):
                        continue
                    
                    # Trigger event
                    rule.trigger_event(record, 'create')
                    rules_triggered = True
                    
                except Exception as e:
                    _logger.error(
                        f'Webhook trigger failed for rule "{rule.name}": {e}'
                    )
        
        # Method 2: If no rules, try webhook.config based triggering
        if not rules_triggered:
            self._webhook_trigger_via_config(record, 'create')

    def _webhook_trigger_write(self, vals):
        """
        Trigger webhooks for updated records
        
        Supports both webhook.rule and webhook.config based tracking.
        
        Args:
            vals: Updated values
        """
        # Early exit: Check if webhooks are disabled via context
        if self.env.context.get('webhook_disabled'):
            return
        
        # Early exit: Check if this model is tracked
        if not self._webhook_is_model_tracked():
            return
        
        # Method 1: Try webhook.rule based triggering
        rules = self._webhook_get_rules('write')
        rules_triggered = False
        
        if rules:
            # Process each record
            for record in self:
                for rule in rules:
                    try:
                        # Check tracked fields filter
                        if not rule._match_tracked_fields(vals):
                            continue
                        
                        # Check domain filter
                        if not rule._match_domain(record):
                            continue
                        
                        # Trigger event
                        rule.trigger_event(record, 'write', vals)
                        rules_triggered = True
                        
                    except Exception as e:
                        _logger.error(
                            f'Webhook trigger failed for rule "{rule.name}": {e}'
                        )
        
        # Method 2: If no rules, try webhook.config based triggering
        if not rules_triggered:
            for record in self:
                self._webhook_trigger_via_config(record, 'write', vals)

    def _webhook_capture_for_unlink(self):
        """
        Capture record data before deletion
        
        Supports both webhook.rule and webhook.config based tracking.
        
        Returns:
            list: List of dicts with record id and data
        """
        # Early exit: Check if webhooks are disabled via context
        if self.env.context.get('webhook_disabled'):
            return []
        
        # Early exit: Check if this model is tracked
        if not self._webhook_is_model_tracked():
            return []
        
        # Get rules for this model and operation
        rules = self._webhook_get_rules('unlink')
        
        # Also check for webhook.config
        config = None
        if 'webhook.config' in self.env:
            config = self.env['webhook.config'].sudo().search([
                ('model_name', '=', self._name),
                ('enabled', '=', True),
                ('active', '=', True)
            ], limit=1)
            
            # If config exists, check if unlink is enabled
            if config and 'unlink' not in config.events.split(','):
                config = None
        
        # Exit if no rules and no config
        if not rules and not config:
            return []
        
        # Capture data for each record
        records_data = []
        for record in self:
            try:
                # Prepare payload
                if rules:
                    # Use first rule's payload preparation
                    payload = rules[0]._prepare_payload(record)
                else:
                    # Use config-based payload preparation
                    payload = self._webhook_prepare_payload(record, 'unlink', config=config)
                
                records_data.append({
                    'id': record.id,
                    'model': record._name,
                    'payload': payload,
                    'rules': rules,
                    'config': config,
                })
            except Exception as e:
                _logger.error(f'Failed to capture unlink data: {e}')
        
        return records_data

    def _webhook_trigger_unlink(self, records_data):
        """
        Trigger webhooks for deleted records
        
        Supports both webhook.rule and webhook.config based tracking.
        
        Args:
            records_data: List of captured record data
        """
        if not records_data:
            return
        
        for data in records_data:
            rules = data.get('rules', [])
            rules_triggered = False
            
            # Method 1: Try webhook.rule based triggering
            for rule in rules:
                try:
                    # Get webhook config for additional metadata
                    config = self.env['webhook.config'].sudo().search([
                        ('model_name', '=', data['model'])
                    ], limit=1)
                    
                    # Create event using update.webhook.create_event
                    self.env['update.webhook'].sudo().create_event(
                        model_name=data['model'],
                        record_id=data['id'],
                        event_type='unlink',
                        payload_data=data['payload'],
                        config=config if config else None
                    )
                    
                    # Update rule last trigger
                    rule.sudo().write({'last_trigger': fields.Datetime.now()})
                    
                    rules_triggered = True
                    
                    _logger.debug(
                        f'Unlink webhook event created: '
                        f'{data["model"]}:{data["id"]}'
                    )
                    
                except Exception as e:
                    _logger.error(
                        f'Webhook trigger failed for unlink: {e}'
                    )
            
            # Method 2: If no rules, try webhook.config based triggering
            if not rules_triggered:
                self._webhook_trigger_unlink_via_config(data)

    # ═══════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════

    @classmethod
    def _webhook_should_trigger(cls, model_name, record_id, operation):
        """
        Check if webhook should trigger (debouncing)
        
        Prevents multiple triggers for same record within DEBOUNCE_SECONDS.
        This is useful when Odoo triggers multiple writes for same record
        (e.g., computed fields, related fields).
        
        Special rules:
        - 'create' and 'write' share the same debounce window
          (because Odoo often does create() then write() immediately)
        - 'unlink' has its own debounce window
        
        Args:
            model_name: Technical model name
            record_id: Record ID
            operation: Operation type (create/write/unlink)
            
        Returns:
            bool: True if should trigger, False if debounced
        """
        # Create and Write share same debounce key
        # This prevents write() right after create() from triggering
        if operation in ('create', 'write'):
            cache_key = f"{model_name}:{record_id}:create_write"
        else:
            cache_key = f"{model_name}:{record_id}:{operation}"
        
        current_time = time.time()
        
        with cls._webhook_debounce_lock:
            # Clean old entries (older than 60 seconds)
            keys_to_delete = [
                k for k, v in cls._webhook_debounce_cache.items()
                if current_time - v > 60
            ]
            for k in keys_to_delete:
                del cls._webhook_debounce_cache[k]
            
            # Check if recently triggered (any operation on same record)
            last_trigger = cls._webhook_debounce_cache.get(cache_key, 0)
            
            if current_time - last_trigger < cls._DEBOUNCE_SECONDS:
                _logger.debug(
                    f'Webhook debounced for {cache_key} '
                    f'(triggered {current_time - last_trigger:.2f}s ago)'
                )
                return False
            
            # Update cache and allow trigger
            cls._webhook_debounce_cache[cache_key] = current_time
            return True

    def _webhook_is_model_tracked(self):
        """
        Fast check if current model has any webhook rules OR webhook config
        
        Uses cached set of tracked models for O(1) lookup.
        Also checks webhook.config for manually added models.
        
        Returns:
            bool: True if model is tracked
        """
        try:
            # Handle special cases
            if not hasattr(self, '_name') or not self._name:
                return False
            
            # Skip internal/technical models EXCEPT res.partner
            if self._name.startswith('ir.'):
                return False
            
            if self._name in ['webhook.rule', 'webhook.event', 'update.webhook',
                              'webhook.config', 'webhook.subscriber', 'webhook.audit',
                              'webhook.retry', 'webhook.template', 'user.sync.state',
                              'webhook.errors', 'webhook.cleanup.cron']:
                return False
            
            # Check 1: webhook.rule (rules-based tracking)
            if 'webhook.rule' in self.env:
                tracked_models = self.env['webhook.rule']._get_tracked_models()
                if self._name in tracked_models:
                    return True
            
            # Check 2: webhook.config (config-based tracking for manually added models)
            if 'webhook.config' in self.env:
                config = self.env['webhook.config'].sudo().search([
                    ('model_name', '=', self._name),
                    ('enabled', '=', True),
                    ('active', '=', True)
                ], limit=1)
                if config:
                    return True
            
            return False
            
        except Exception as e:
            _logger.debug(f'Error checking if model is tracked: {e}')
            return False

    def _webhook_get_rules(self, operation):
        """
        Get webhook rules for current model and operation
        
        Args:
            operation: Operation type ('create', 'write', 'unlink')
            
        Returns:
            recordset: webhook.rule records
        """
        try:
            return self.env['webhook.rule']._get_rules_for(self._name, operation)
        except Exception as e:
            _logger.error(f'Failed to get webhook rules: {e}')
            return self.env['webhook.rule'].browse()

    def _webhook_trigger_via_config(self, record, operation, vals=None):
        """
        Trigger webhook via webhook.config (for manually added models)
        
        This method is called when no webhook.rule exists but webhook.config does.
        It creates events in both update.webhook and webhook.event.
        
        Args:
            record: The record that triggered the event
            operation: Operation type ('create', 'write', 'unlink')
            vals: Changed values (for write operation)
        """
        try:
            # Get webhook config
            if 'webhook.config' not in self.env:
                return
            
            config = self.env['webhook.config'].sudo().search([
                ('model_name', '=', record._name),
                ('enabled', '=', True),
                ('active', '=', True)
            ], limit=1)
            
            if not config:
                return
            
            # Check if this event type is enabled
            if operation not in config.events.split(','):
                return
            
            # Check filter domain
            if config.filter_domain:
                try:
                    from odoo.tools.safe_eval import safe_eval
                    domain = safe_eval(config.filter_domain)
                    if domain:
                        matching = record.sudo().search([
                            ('id', '=', record.id)
                        ] + domain, limit=1)
                        if not matching:
                            return
                except Exception as e:
                    _logger.warning(f'Domain filter error: {e}')
            
            # Check filtered fields for write events
            if operation == 'write' and config.filtered_fields and vals:
                tracked_field_names = set(config.filtered_fields.mapped('name'))
                changed_fields = set(vals.keys())
                if not tracked_field_names.intersection(changed_fields):
                    return
            
            # Prepare payload data
            payload_data = self._webhook_prepare_payload(record, operation, vals, config)
            
            # Step 1: Create event in update.webhook (for pull-based access)
            try:
                self.env['update.webhook'].sudo().create_event(
                    model_name=record._name,
                    record_id=record.id,
                    event_type=operation,
                    payload_data=payload_data,
                    config=config
                )
                _logger.debug(f'Created update.webhook event: {record._name}:{record.id} ({operation})')
            except Exception as e:
                _logger.error(f'Failed to create update.webhook event: {e}')
            
            # Step 2: Create webhook.event for subscribers (for push-based delivery)
            subscribers = config.subscribers.filtered(lambda s: s.enabled and s.active)
            if subscribers and config.instant_send:
                for subscriber in subscribers:
                    try:
                        event = self.env['webhook.event'].sudo().create({
                            'model': record._name,
                            'record_id': record.id,
                            'event': operation,
                            'config_id': config.id,
                            'subscriber_id': subscriber.id,
                            'priority': config.priority,
                            'category': config.category,
                            'payload': payload_data,
                            'status': 'pending',
                            'changed_fields': list(vals.keys()) if vals else [],
                        })
                        
                        _logger.info(f'Created webhook.event: {event.id} for {record._name}:{record.id}')
                        
                        # Instant send for high priority
                        if config.instant_send and config.priority == 'high':
                            try:
                                self.env.cr.commit()
                                event._send_to_subscriber()
                            except Exception as e:
                                _logger.error(f'Instant send failed: {e}')
                                
                    except Exception as e:
                        _logger.error(f'Failed to create webhook.event for {subscriber.name}: {e}')
                        
        except Exception as e:
            _logger.error(f'Webhook trigger via config failed: {e}', exc_info=True)

    def _webhook_prepare_payload(self, record, operation, vals=None, config=None):
        """
        Prepare webhook payload data
        
        Args:
            record: The record
            operation: Operation type
            vals: Changed values (for write)
            config: webhook.config record
            
        Returns:
            dict: Payload data
        """
        try:
            # Get fields to include
            if config and config.filtered_fields:
                fields_to_include = config.filtered_fields.mapped('name')
            else:
                # All readable fields (excluding internal ones)
                fields_to_include = [
                    f for f in record._fields.keys()
                    if not f.startswith('_') and f not in [
                        'create_uid', 'write_uid', '__last_update',
                        'message_ids', 'message_follower_ids', 'activity_ids'
                    ]
                ]
            
            # Build data
            data = {}
            for field_name in fields_to_include:
                try:
                    field = record._fields.get(field_name)
                    if not field:
                        continue
                    
                    # Skip computed non-stored fields
                    if field.compute and not field.store:
                        continue
                    
                    # Skip binary fields
                    if field.type == 'binary':
                        data[field_name] = bool(getattr(record, field_name, None))
                        continue
                    
                    value = getattr(record, field_name, None)
                    
                    # Handle field types
                    if field.type == 'many2one':
                        data[field_name] = {
                            'id': value.id if value else False,
                            'name': value.display_name if value else ''
                        }
                    elif field.type in ['one2many', 'many2many']:
                        data[field_name] = [
                            {'id': r.id, 'name': r.display_name}
                            for r in (value[:50] if value else [])
                        ]
                    elif field.type == 'datetime':
                        data[field_name] = value.isoformat() if value else False
                    elif field.type == 'date':
                        data[field_name] = value.isoformat() if value else False
                    else:
                        data[field_name] = value
                        
                except Exception as e:
                    _logger.warning(f'Failed to get field {field_name}: {e}')
                    data[field_name] = None
            
            # Add metadata
            data['_metadata'] = {
                'model': record._name,
                'id': record.id,
                'display_name': record.display_name if hasattr(record, 'display_name') else str(record.id),
                'operation': operation,
                'timestamp': fields.Datetime.now().isoformat(),
            }
            
            # Add changed fields for write
            if vals:
                data['_changed_fields'] = list(vals.keys())
            
            return data
            
        except Exception as e:
            _logger.error(f'Failed to prepare payload: {e}')
            return {
                '_metadata': {
                    'model': record._name,
                    'id': record.id,
                    'operation': operation,
                    'error': str(e)
                }
            }

    def _webhook_trigger_unlink_via_config(self, data):
        """
        Trigger unlink webhook via webhook.config (for manually added models)
        
        Args:
            data: Dict with 'id', 'model', 'payload', 'config' keys
        """
        try:
            config = data.get('config')
            if not config:
                # Try to get config
                if 'webhook.config' not in self.env:
                    return
                
                config = self.env['webhook.config'].sudo().search([
                    ('model_name', '=', data['model']),
                    ('enabled', '=', True),
                    ('active', '=', True)
                ], limit=1)
            
            if not config:
                return
            
            # Check if unlink is enabled
            if 'unlink' not in config.events.split(','):
                return
            
            # Step 1: Create event in update.webhook
            try:
                self.env['update.webhook'].sudo().create_event(
                    model_name=data['model'],
                    record_id=data['id'],
                    event_type='unlink',
                    payload_data=data['payload'],
                    config=config
                )
                _logger.debug(f'Created update.webhook unlink event: {data["model"]}:{data["id"]}')
            except Exception as e:
                _logger.error(f'Failed to create update.webhook unlink event: {e}')
            
            # Step 2: Create webhook.event for subscribers
            subscribers = config.subscribers.filtered(lambda s: s.enabled and s.active)
            if subscribers and config.instant_send:
                for subscriber in subscribers:
                    try:
                        event = self.env['webhook.event'].sudo().create({
                            'model': data['model'],
                            'record_id': data['id'],
                            'event': 'unlink',
                            'config_id': config.id,
                            'subscriber_id': subscriber.id,
                            'priority': config.priority,
                            'category': config.category,
                            'payload': data['payload'],
                            'status': 'pending',
                        })
                        
                        _logger.info(f'Created webhook.event for unlink: {event.id}')
                        
                        # Instant send for high priority
                        if config.priority == 'high':
                            try:
                                self.env.cr.commit()
                                event._send_to_subscriber()
                            except Exception as e:
                                _logger.error(f'Instant send failed: {e}')
                                
                    except Exception as e:
                        _logger.error(f'Failed to create unlink webhook.event: {e}')
                        
        except Exception as e:
            _logger.error(f'Unlink webhook via config failed: {e}', exc_info=True)
