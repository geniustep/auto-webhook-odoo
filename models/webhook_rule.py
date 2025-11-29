# -*- coding: utf-8 -*-
"""
Webhook Rule - Config-Driven Event Tracking

This model allows adding webhook tracking to any Odoo model
via configuration instead of code inheritance.

Inspired by OCA auditlog module pattern.

Features:
- Add tracking to any model from UI
- Domain-based filtering
- Field-level tracking
- Smart caching for performance
- Rate limiting per rule
"""

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval
import logging
import threading

_logger = logging.getLogger(__name__)


class WebhookRule(models.Model):
    """
    Webhook Rule - Define which models and operations to track
    
    Usage:
    - Create a rule for a model (e.g., sale.order)
    - Select operations (create/write/unlink)
    - Optionally add domain filter and tracked fields
    - The base hook will automatically trigger webhooks
    """
    _name = 'webhook.rule'
    _description = 'Webhook Rule - Config-Driven Tracking'
    _order = 'sequence, model_name'
    _rec_name = 'name'

    # ═══════════════════════════════════════════════════════════
    # Class-level Cache (Thread-safe)
    # ═══════════════════════════════════════════════════════════
    
    _rules_cache = {}
    _tracked_models = set()
    _cache_lock = threading.Lock()
    _cache_valid = False

    # ═══════════════════════════════════════════════════════════
    # Fields
    # ═══════════════════════════════════════════════════════════

    name = fields.Char(
        string='Rule Name',
        required=True,
        help='Descriptive name for this rule'
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Order of rule execution'
    )

    active = fields.Boolean(
        string='Active',
        default=True,
        index=True,
        help='Inactive rules are ignored'
    )

    # Model Selection
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        domain=[('transient', '=', False)],
        help='Select the model to track'
    )

    model_name = fields.Char(
        string='Model Name',
        related='model_id.model',
        store=True,
        index=True,
        readonly=True,
        help='Technical name of the model'
    )

    # Operations
    operation = fields.Selection(
        selection=[
            ('create', 'Create'),
            ('write', 'Update'),
            ('unlink', 'Delete'),
        ],
        string='Operation',
        required=True,
        index=True,
        help='Type of operation to track'
    )

    # Domain Filter
    domain = fields.Char(
        string='Domain Filter',
        default='[]',
        help='Python domain to filter records, e.g. [(\'state\',\'=\',\'sale\')]'
    )

    # Field Tracking
    tracked_fields = fields.Char(
        string='Tracked Fields',
        help='Comma-separated field names. Empty = all fields.\n'
             'For write operations, event is only triggered if these fields change.'
    )

    # Webhook Settings
    subscriber_ids = fields.Many2many(
        'webhook.subscriber',
        'webhook_rule_subscriber_rel',
        'rule_id',
        'subscriber_id',
        string='Subscribers',
        help='Webhook endpoints to notify'
    )

    template_id = fields.Many2one(
        'webhook.template',
        string='Payload Template',
        help='Custom payload template (Jinja2)'
    )

    priority = fields.Selection(
        selection=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low'),
        ],
        string='Priority',
        default='medium',
        required=True,
        help='Event priority (high = instant send)'
    )

    category = fields.Selection(
        selection=[
            ('business', 'Business'),
            ('system', 'System'),
            ('notification', 'Notification'),
            ('custom', 'Custom'),
        ],
        string='Category',
        default='business',
        help='Event category for filtering'
    )

    instant_send = fields.Boolean(
        string='Instant Send',
        default=False,
        help='Send immediately instead of waiting for cron'
    )

    # Rate Limiting
    rate_limit = fields.Integer(
        string='Rate Limit',
        default=0,
        help='Max events per minute. 0 = unlimited'
    )

    debounce_seconds = fields.Integer(
        string='Debounce (seconds)',
        default=0,
        help='Wait X seconds before sending (groups rapid updates)'
    )

    # Test Mode
    test_mode = fields.Boolean(
        string='Test Mode',
        default=False,
        help='Log events but don\'t send them'
    )

    # Statistics
    event_count = fields.Integer(
        string='Event Count',
        compute='_compute_event_count',
        help='Number of events triggered by this rule'
    )

    last_trigger = fields.Datetime(
        string='Last Triggered',
        readonly=True,
        help='When this rule was last triggered'
    )

    # Description
    description = fields.Text(
        string='Description',
        help='Notes about this rule'
    )

    # ═══════════════════════════════════════════════════════════
    # SQL Constraints
    # ═══════════════════════════════════════════════════════════

    _sql_constraints = [
        ('unique_model_operation',
         'UNIQUE(model_name, operation, active)',
         'Only one active rule per model and operation!'),
        ('check_rate_limit',
         'CHECK(rate_limit >= 0)',
         'Rate limit must be non-negative'),
        ('check_debounce',
         'CHECK(debounce_seconds >= 0)',
         'Debounce seconds must be non-negative'),
    ]

    # ═══════════════════════════════════════════════════════════
    # Computed Fields
    # ═══════════════════════════════════════════════════════════

    def _compute_event_count(self):
        """Count events created by this rule"""
        for rule in self:
            count = self.env['update.webhook'].sudo().search_count([
                ('model', '=', rule.model_name),
                ('event', '=', rule.operation),
            ])
            rule.event_count = count

    # ═══════════════════════════════════════════════════════════
    # Validation
    # ═══════════════════════════════════════════════════════════

    @api.constrains('domain')
    def _check_domain(self):
        """Validate domain syntax"""
        for rule in self:
            if rule.domain and rule.domain != '[]':
                try:
                    domain = safe_eval(rule.domain)
                    if not isinstance(domain, list):
                        raise ValidationError(_('Domain must be a list'))
                except Exception as e:
                    raise ValidationError(
                        _('Invalid domain syntax: %s') % str(e)
                    )

    @api.constrains('tracked_fields', 'model_id')
    def _check_tracked_fields(self):
        """Validate tracked fields exist in model"""
        for rule in self:
            if rule.tracked_fields and rule.model_id:
                model = self.env[rule.model_name]
                fields_list = [f.strip() for f in rule.tracked_fields.split(',')]
                for field_name in fields_list:
                    if field_name and field_name not in model._fields:
                        raise ValidationError(
                            _('Field "%s" does not exist in model %s') % 
                            (field_name, rule.model_name)
                        )

    # ═══════════════════════════════════════════════════════════
    # Cache Management
    # ═══════════════════════════════════════════════════════════

    @api.model
    def _invalidate_cache(self):
        """Invalidate the rules cache"""
        with self._cache_lock:
            WebhookRule._rules_cache = {}
            WebhookRule._tracked_models = set()
            WebhookRule._cache_valid = False
        _logger.info('Webhook rules cache invalidated')

    @api.model
    def _rebuild_cache(self):
        """Rebuild the rules cache from database"""
        with self._cache_lock:
            WebhookRule._rules_cache = {}
            WebhookRule._tracked_models = set()
            
            # Load all active rules
            rules = self.sudo().search([('active', '=', True)])
            
            for rule in rules:
                cache_key = f"{rule.model_name}:{rule.operation}"
                if cache_key not in WebhookRule._rules_cache:
                    WebhookRule._rules_cache[cache_key] = []
                WebhookRule._rules_cache[cache_key].append(rule.id)
                WebhookRule._tracked_models.add(rule.model_name)
            
            WebhookRule._cache_valid = True
            
        _logger.info(
            f'Webhook rules cache rebuilt: '
            f'{len(WebhookRule._tracked_models)} models, '
            f'{len(rules)} rules'
        )

    @api.model
    def _get_tracked_models(self):
        """Get set of all tracked model names (fast check)"""
        if not WebhookRule._cache_valid:
            self._rebuild_cache()
        return WebhookRule._tracked_models

    @api.model
    def _get_rules_for(self, model_name, operation):
        """
        Get active rules for a model and operation
        
        Uses cache for performance (avoids DB query on every CRUD)
        
        Args:
            model_name: Technical model name (e.g., 'sale.order')
            operation: Operation type ('create', 'write', 'unlink')
            
        Returns:
            recordset of webhook.rule
        """
        # Ensure cache is valid
        if not WebhookRule._cache_valid:
            self._rebuild_cache()
        
        cache_key = f"{model_name}:{operation}"
        
        # Get rule IDs from cache
        rule_ids = WebhookRule._rules_cache.get(cache_key, [])
        
        if not rule_ids:
            return self.browse()
        
        # Return rules recordset
        return self.sudo().browse(rule_ids).exists()

    # ═══════════════════════════════════════════════════════════
    # CRUD Overrides (Cache Invalidation)
    # ═══════════════════════════════════════════════════════════

    @api.model_create_multi
    def create(self, vals_list):
        """Create rules and invalidate cache"""
        records = super().create(vals_list)
        self._invalidate_cache()
        return records

    def write(self, vals):
        """Update rules and invalidate cache"""
        result = super().write(vals)
        self._invalidate_cache()
        return result

    def unlink(self):
        """Delete rules and invalidate cache"""
        result = super().unlink()
        self._invalidate_cache()
        return result

    # ═══════════════════════════════════════════════════════════
    # Domain Matching
    # ═══════════════════════════════════════════════════════════

    def _match_domain(self, record):
        """
        Check if record matches the rule's domain filter
        
        Args:
            record: Record to check
            
        Returns:
            bool: True if matches (or no domain specified)
        """
        self.ensure_one()
        
        if not self.domain or self.domain == '[]':
            return True
        
        try:
            domain = safe_eval(self.domain)
            if not domain:
                return True
            
            # Search for the record with the domain
            matching = record.sudo().search([
                ('id', '=', record.id)
            ] + domain, limit=1)
            
            return bool(matching)
            
        except Exception as e:
            _logger.warning(
                f'Domain evaluation failed for rule {self.name}: {e}'
            )
            return True  # Default to matching on error

    def _match_tracked_fields(self, changed_vals):
        """
        Check if changed fields match tracked fields
        
        Args:
            changed_vals: Dictionary of changed field values
            
        Returns:
            bool: True if matches (or no tracked fields specified)
        """
        self.ensure_one()
        
        if not self.tracked_fields:
            return True
        
        if not changed_vals:
            return True
        
        tracked = set(f.strip() for f in self.tracked_fields.split(',') if f.strip())
        changed = set(changed_vals.keys())
        
        # Return True if any tracked field was changed
        return bool(tracked & changed)

    # ═══════════════════════════════════════════════════════════
    # Event Creation
    # ═══════════════════════════════════════════════════════════

    def trigger_event(self, record, operation, changed_vals=None):
        """
        Trigger a webhook event for a record
        
        Args:
            record: The record that triggered the event
            operation: Operation type ('create', 'write', 'unlink')
            changed_vals: Changed values (for write operation)
            
        Returns:
            update.webhook record or False
        """
        self.ensure_one()
        
        try:
            # Ensure record has an ID
            if not record or not record.id:
                _logger.warning(
                    f'Webhook trigger skipped for rule "{self.name}": '
                    f'Record has no ID (model: {record._name if record else "Unknown"})'
                )
                return False
            
            # Update last trigger time
            self.sudo().write({'last_trigger': fields.Datetime.now()})
            
            # Prepare payload
            payload_data = self._prepare_payload(record, changed_vals)
            
            # Get webhook config for additional metadata
            config = self.env['webhook.config'].sudo().search([
                ('model_name', '=', record._name)
            ], limit=1)
            
            # Create event in update.webhook using the optimized create_event method
            event = self.env['update.webhook'].sudo().create_event(
                model_name=record._name,
                record_id=record.id,
                event_type=operation,
                payload_data=payload_data,
                config=config if config else None
            )
            
            if not event:
                _logger.warning(
                    f'Failed to create webhook event for rule "{self.name}": '
                    f'{record._name}:{record.id} ({operation})'
                )
                return False
            
            _logger.debug(
                f'Webhook event created by rule "{self.name}": '
                f'{record._name}:{record.id} ({operation})'
            )
            
            # ALWAYS create webhook.event for subscribers (not just instant_send)
            # This ensures events appear in Webhook Events view
            if self.subscriber_ids and not self.test_mode:
                self._create_webhook_events(record, operation, payload_data, config)
            
            # Handle instant send - send immediately
            if self.instant_send and self.subscriber_ids and not self.test_mode:
                self._send_instant_events(record)
            
            return event
            
        except Exception as e:
            _logger.error(
                f'Failed to trigger webhook for rule "{self.name}": {e}',
                exc_info=True
            )
            return False

    def _prepare_payload(self, record, changed_vals=None):
        """
        Prepare webhook payload data
        
        Args:
            record: The record
            changed_vals: Changed values (for write)
            
        Returns:
            dict: Payload data
        """
        self.ensure_one()
        
        # If template is specified, use it
        if self.template_id:
            return self.template_id.render_template(record)
        
        # Get fields to include
        if self.tracked_fields:
            fields_to_include = [f.strip() for f in self.tracked_fields.split(',') if f.strip()]
        else:
            # All readable fields (excluding internal ones)
            fields_to_include = [
                f for f in record._fields.keys()
                if not f.startswith('_') and f not in [
                    'create_uid', 'write_uid', '__last_update',
                    'message_ids', 'message_follower_ids', 'activity_ids'
                ]
            ]
        
        # Build payload
        data = {}
        for field_name in fields_to_include:
            try:
                field = record._fields.get(field_name)
                if not field:
                    continue
                
                # Skip computed non-stored fields
                if field.compute and not field.store:
                    continue
                
                # Skip binary fields (just mark as present)
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
                        for r in (value[:50] if value else [])  # Limit to 50
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
            'rule_id': self.id,
            'rule_name': self.name,
        }
        
        # Add changed fields for write
        if changed_vals:
            data['_changed_fields'] = list(changed_vals.keys())
        
        return data

    def _create_webhook_events(self, record, operation, payload_data, config=None):
        """
        Create webhook.event entries for all subscribers
        This ensures events appear in Webhook Events view
        """
        self.ensure_one()
        
        if not record or not record.id:
            return
        
        if not self.subscriber_ids:
            return
        
        for subscriber in self.subscriber_ids.filtered('enabled'):
            try:
                # Create webhook.event for tracking
                event_vals = {
                    'model': record._name,
                    'record_id': record.id,
                    'event': operation,
                    'subscriber_id': subscriber.id,
                    'priority': self.priority,
                    'category': self.category,
                    'payload': payload_data,
                    'status': 'pending',
                }
                
                # Add config if available
                if config:
                    event_vals['config_id'] = config.id
                
                self.env['webhook.event'].sudo().create(event_vals)
                
                _logger.debug(
                    f'Webhook event created for subscriber {subscriber.name}: '
                    f'{record._name}:{record.id} ({operation})'
                )
                
            except Exception as e:
                _logger.error(f'Failed to create webhook.event: {e}')

    def _send_instant_events(self, record):
        """Send pending webhook events immediately (for instant_send rules)"""
        self.ensure_one()
        
        if not record or not record.id:
            return
        
        # Find pending events for this record
        pending_events = self.env['webhook.event'].sudo().search([
            ('model', '=', record._name),
            ('record_id', '=', record.id),
            ('status', '=', 'pending'),
        ], order='id desc', limit=len(self.subscriber_ids))
        
        for event in pending_events:
            try:
                # Commit before sending
                self.env.cr.commit()
                
                # Send immediately
                event._send_to_subscriber()
                
            except Exception as e:
                _logger.error(f'Instant send failed for event {event.id}: {e}')

    def _send_instant(self, record, operation, payload_data):
        """Legacy method - kept for backwards compatibility"""
        self._create_webhook_events(record, operation, payload_data)
        self._send_instant_events(record)

    # ═══════════════════════════════════════════════════════════
    # Actions
    # ═══════════════════════════════════════════════════════════

    def action_test_rule(self):
        """Test rule by simulating an event"""
        self.ensure_one()
        
        # Get a sample record
        try:
            model = self.env[self.model_name]
            sample = model.search([], limit=1)
            
            if not sample:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Test Failed'),
                        'message': _('No records found in model %s') % self.model_name,
                        'type': 'warning',
                    }
                }
            
            # Check domain match
            matches = self._match_domain(sample)
            
            # Prepare payload
            payload = self._prepare_payload(sample)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Result'),
                    'message': _(
                        'Rule test successful!\n'
                        'Sample: %s\n'
                        'Domain match: %s\n'
                        'Payload size: %d fields'
                    ) % (sample.display_name, matches, len(payload)),
                    'type': 'success',
                }
            }
            
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Error'),
                    'message': str(e),
                    'type': 'danger',
                }
            }

    def action_view_events(self):
        """View events created by this rule"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Webhook Events'),
            'res_model': 'update.webhook',
            'view_mode': 'list,form',
            'domain': [
                ('model', '=', self.model_name),
                ('event', '=', self.operation),
            ],
            'context': {'default_model': self.model_name},
        }

    def action_refresh_cache(self):
        """Manually refresh the rules cache"""
        self._rebuild_cache()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cache Refreshed'),
                'message': _('Webhook rules cache has been refreshed'),
                'type': 'success',
            }
        }

