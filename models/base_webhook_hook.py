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

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class BaseWebhookHook(models.AbstractModel):
    """
    Universal Webhook Hook on base model
    
    Intercepts create/write/unlink on ALL models and checks
    if there's an active webhook.rule for the model.
    """
    _inherit = 'base'

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
        
        # Trigger webhook AFTER transaction using @after_commit
        # This ensures records are fully saved with valid IDs
        if records and not self.env.context.get('webhook_disabled'):
            # Use after_commit to ensure IDs are assigned
            @self.env.cr.postcommit.add
            def trigger_webhooks():
                try:
                    # Ensure records still exist and have IDs
                    if records.exists():
                        self._webhook_trigger_create(records)
                except Exception as e:
                    _logger.error(f'Webhook trigger failed for create: {e}', exc_info=True)
        
        return records

    def write(self, vals):
        """
        Override write to trigger webhooks based on rules
        """
        # Execute original write
        result = super().write(vals)
        
        # Trigger webhook (fail-safe)
        try:
            self._webhook_trigger_write(vals)
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

    def _webhook_trigger_create(self, records):
        """
        Trigger webhooks for created records
        
        Args:
            records: Created records
        """
        # Early exit: Check if webhooks are disabled via context
        if self.env.context.get('webhook_disabled'):
            return
        
        # Early exit: Check if this model is tracked
        if not self._webhook_is_model_tracked():
            return
        
        # Get rules for this model and operation
        rules = self._webhook_get_rules('create')
        if not rules:
            return
        
        # Process each record
        for record in records:
            # Ensure record has valid ID
            if not record.id or isinstance(record.id, models.NewId):
                _logger.warning(
                    f'Skipping webhook for {record._name}: '
                    f'Record has no valid ID (id={record.id})'
                )
                continue
                
            for rule in rules:
                try:
                    # Check domain filter
                    if not rule._match_domain(record):
                        continue
                    
                    # Trigger event
                    rule.trigger_event(record, 'create')
                    
                except Exception as e:
                    _logger.error(
                        f'Webhook trigger failed for rule "{rule.name}": {e}'
                    )

    def _webhook_trigger_write(self, vals):
        """
        Trigger webhooks for updated records
        
        Args:
            vals: Updated values
        """
        # Early exit: Check if webhooks are disabled via context
        if self.env.context.get('webhook_disabled'):
            return
        
        # Early exit: Check if this model is tracked
        if not self._webhook_is_model_tracked():
            return
        
        # Get rules for this model and operation
        rules = self._webhook_get_rules('write')
        if not rules:
            return
        
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
                    
                except Exception as e:
                    _logger.error(
                        f'Webhook trigger failed for rule "{rule.name}": {e}'
                    )

    def _webhook_capture_for_unlink(self):
        """
        Capture record data before deletion
        
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
        if not rules:
            return []
        
        # Capture data for each record
        records_data = []
        for record in self:
            try:
                # Use first rule's payload preparation
                rule = rules[0]
                payload = rule._prepare_payload(record)
                records_data.append({
                    'id': record.id,
                    'model': record._name,
                    'payload': payload,
                    'rules': rules,
                })
            except Exception as e:
                _logger.error(f'Failed to capture unlink data: {e}')
        
        return records_data

    def _webhook_trigger_unlink(self, records_data):
        """
        Trigger webhooks for deleted records
        
        Args:
            records_data: List of captured record data
        """
        if not records_data:
            return
        
        for data in records_data:
            for rule in data.get('rules', []):
                try:
                    # Create event directly (record is already deleted)
                    self.env['update.webhook'].sudo().create({
                        'model': data['model'],
                        'record_id': data['id'],
                        'event': 'unlink',
                        'payload': data['payload'],
                        'priority': rule.priority,
                        'category': rule.category,
                        'user_id': self.env.user.id,
                    })
                    
                    # Update rule last trigger
                    rule.sudo().write({'last_trigger': self.env.cr.now()})
                    
                    _logger.debug(
                        f'Unlink webhook event created: '
                        f'{data["model"]}:{data["id"]}'
                    )
                    
                except Exception as e:
                    _logger.error(
                        f'Webhook trigger failed for unlink: {e}'
                    )

    # ═══════════════════════════════════════════════════════════
    # Helper Methods
    # ═══════════════════════════════════════════════════════════

    def _webhook_is_model_tracked(self):
        """
        Fast check if current model has any webhook rules
        
        Uses cached set of tracked models for O(1) lookup.
        
        Returns:
            bool: True if model is tracked
        """
        try:
            # Handle special cases
            if not hasattr(self, '_name') or not self._name:
                return False
            
            # Skip internal/technical models
            if self._name.startswith('ir.') or self._name.startswith('base.'):
                return False
            
            if self._name in ['webhook.rule', 'webhook.event', 'update.webhook',
                              'webhook.config', 'webhook.subscriber', 'webhook.audit',
                              'webhook.retry', 'webhook.template', 'user.sync.state']:
                return False
            
            # Check if webhook.rule model exists
            if 'webhook.rule' not in self.env:
                return False
            
            # Get tracked models from cache
            tracked_models = self.env['webhook.rule']._get_tracked_models()
            
            return self._name in tracked_models
            
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

