# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval
import logging

_logger = logging.getLogger(__name__)


class WebhookConfig(models.Model):
    """Webhook Configuration per Model"""

    _name = 'webhook.config'
    _description = 'Webhook Configuration'
    _order = 'priority desc, name'

    # Basic Information
    name = fields.Char(
        string='Configuration Name',
        required=True,
        help='Name of this webhook configuration'
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        help='Model to track for webhook events'
    )
    model_name = fields.Char(
        string='Model Technical Name',
        related='model_id.model',
        store=True,
        index=True,
        help='Technical name of the model'
    )

    # Activation
    enabled = fields.Boolean(
        string='Enabled',
        default=True,
        help='Enable or disable webhook for this model'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Archive/Unarchive this configuration'
    )

    # Priority and Category
    priority = fields.Selection(
        selection=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low')
        ],
        string='Priority',
        default='medium',
        required=True,
        help='Default priority for events from this model'
    )
    category = fields.Selection(
        selection=[
            ('business', 'Business'),
            ('system', 'System'),
            ('notification', 'Notification'),
            ('custom', 'Custom')
        ],
        string='Category',
        default='business',
        help='Category for events from this model'
    )

    # Event Types
    events = fields.Selection(
        selection=[
            ('create', 'Create Only'),
            ('write', 'Write Only'),
            ('unlink', 'Delete Only'),
            ('create,write', 'Create & Write'),
            ('create,unlink', 'Create & Delete'),
            ('write,unlink', 'Write & Delete'),
            ('create,write,unlink', 'All Events')
        ],
        string='Tracked Events',
        default='create,write,unlink',
        required=True,
        help='Which events to track for this model'
    )

    # Field Filtering
    filtered_fields = fields.Many2many(
        'ir.model.fields',
        'webhook_config_field_rel',
        'config_id',
        'field_id',
        string='Tracked Fields',
        domain="[('model_id', '=', model_id)]",
        help='Track only these specific fields. Leave empty to track all fields.'
    )
    filter_domain = fields.Text(
        string='Filter Domain',
        help='Domain expression to filter records. Example: [(\'state\', \'=\', \'done\')]'
    )

    # Subscribers
    subscribers = fields.Many2many(
        'webhook.subscriber',
        'webhook_config_subscriber_rel',
        'config_id',
        'subscriber_id',
        string='Subscribers',
        help='Endpoints that will receive events from this model'
    )

    # Template
    template_id = fields.Many2one(
        'webhook.template',
        string='Default Template',
        ondelete='set null',
        domain="[('model_id', '=', model_id)]",
        help='Template to use for formatting event payloads'
    )

    # Batch Processing
    batch_enabled = fields.Boolean(
        string='Batch Processing',
        default=False,
        help='Enable batch processing for events from this model'
    )
    batch_size = fields.Integer(
        string='Batch Size',
        default=100,
        help='Number of events to batch together'
    )
    batch_timeout = fields.Integer(
        string='Batch Timeout (seconds)',
        default=60,
        help='Maximum time to wait before sending incomplete batch'
    )

    # Additional Information
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this configuration'
    )

    # Statistics
    total_events = fields.Integer(
        string='Total Events',
        compute='_compute_statistics',
        help='Total number of events generated'
    )
    pending_events = fields.Integer(
        string='Pending Events',
        compute='_compute_statistics',
        help='Number of pending events'
    )
    failed_events = fields.Integer(
        string='Failed Events',
        compute='_compute_statistics',
        help='Number of failed events'
    )

    # SQL Constraints
    _sql_constraints = [
        ('unique_model',
         'UNIQUE(model_id)',
         'A webhook configuration already exists for this model!'),
    ]

    @api.depends('model_name')
    def _compute_statistics(self):
        """Compute event statistics for this configuration"""
        for record in self:
            events = self.env['webhook.event'].search([
                ('config_id', '=', record.id)
            ])

            record.total_events = len(events)
            record.pending_events = len(events.filtered(lambda e: e.status == 'pending'))
            record.failed_events = len(events.filtered(lambda e: e.status == 'failed'))

    @api.model
    def get_config_for_model(self, model_name):
        """
        Get webhook configuration for a model

        Args:
            model_name: Technical name of the model

        Returns:
            webhook.config record or False
        """
        try:
            config = self.search([
                ('model_name', '=', model_name),
                ('enabled', '=', True),
                ('active', '=', True)
            ], limit=1)

            if not config:
                # Try to auto-create config for known models (only if transaction is clean)
                try:
                    config = self._auto_create_config(model_name)
                except Exception as e:
                    _logger.warning(f"Could not auto-create config for {model_name}: {e}")
                    return False

            return config
        except Exception as e:
            _logger.error(f"Error getting config for model {model_name}: {e}")
            return False

    @api.model
    def _auto_create_config(self, model_name):
        """
        Auto-create configuration for a model

        Args:
            model_name: Technical name of the model

        Returns:
            webhook.config record or False
        """
        # Check if model exists
        model = self.env['ir.model'].search([('model', '=', model_name)], limit=1)
        if not model:
            return False

        # Auto-classify priority based on model name
        priority = self._auto_classify_priority(model_name)

        try:
            config = self.create({
                'name': f'Auto Config - {model.name}',
                'model_id': model.id,
                'priority': priority,
                'enabled': False,  # Disabled by default for auto-created configs
                'events': 'create,write,unlink',
            })

            _logger.info(f"Auto-created webhook config for model {model_name}")
            return config

        except Exception as e:
            _logger.error(f"Failed to auto-create config for {model_name}: {e}")
            return False

    def _auto_classify_priority(self, model_name):
        """
        Auto-classify priority based on model name

        Args:
            model_name: Technical name of the model

        Returns:
            Priority level (high/medium/low)
        """
        # High priority models
        high_priority = [
            'sale.order',
            'purchase.order',
            'account.move',
            'account.payment',
            'stock.picking',
        ]

        # Medium priority models
        medium_priority = [
            'stock.move',
            'account.invoice',
            'res.partner',
            'product.product',
            'product.template',
        ]

        if model_name in high_priority:
            return 'high'
        elif model_name in medium_priority:
            return 'medium'
        else:
            return 'low'

    def should_track_event(self, record, event_type, changed_fields=None):
        """
        Check if an event should be tracked based on configuration

        Args:
            record: Record that triggered the event
            event_type: Type of event (create/write/unlink)
            changed_fields: Set of fields that changed (for write events)

        Returns:
            Boolean indicating if event should be tracked
        """
        self.ensure_one()

        # Check if this event type is tracked
        tracked_events = self.events.split(',')
        if event_type not in tracked_events:
            return False

        # Check filter domain
        if self.filter_domain:
            try:
                domain = safe_eval(self.filter_domain)
                if not record.filtered_domain(domain):
                    return False
            except Exception as e:
                _logger.error(f"Error evaluating filter domain: {e}")
                # Continue if domain evaluation fails

        # Check filtered fields (only for write events)
        if event_type == 'write' and self.filtered_fields:
            # If no changed fields provided, track the event
            if not changed_fields:
                return True

            # Check if any tracked field was changed
            tracked_field_names = set(self.filtered_fields.mapped('name'))
            if not tracked_field_names.intersection(changed_fields):
                return False

        return True

    def get_event_subscribers(self):
        """Get list of subscribers for this configuration"""
        self.ensure_one()
        return self.subscribers.filtered(lambda s: s.enabled and s.active)

    @api.onchange('model_id')
    def _onchange_model_id(self):
        """Auto-fill name and priority when model is selected"""
        if self.model_id:
            if not self.name:
                self.name = f"Webhook Config - {self.model_id.name}"

            # Auto-classify priority
            self.priority = self._auto_classify_priority(self.model_id.model)

    @api.constrains('batch_size', 'batch_timeout')
    def _check_batch_settings(self):
        """Validate batch settings"""
        for record in self:
            if record.batch_enabled:
                if record.batch_size < 1:
                    raise ValidationError(_("Batch size must be at least 1"))
                if record.batch_timeout < 1:
                    raise ValidationError(_("Batch timeout must be at least 1 second"))

    @api.constrains('filter_domain')
    def _check_filter_domain(self):
        """Validate filter domain syntax"""
        for record in self:
            if record.filter_domain:
                try:
                    safe_eval(record.filter_domain)
                except Exception as e:
                    raise ValidationError(
                        _("Invalid filter domain syntax: %s") % str(e)
                    )

    def action_view_events(self):
        """Open events view filtered by this configuration"""
        self.ensure_one()

        return {
            'name': _('Webhook Events'),
            'type': 'ir.actions.act_window',
            'res_model': 'webhook.event',
            'view_mode': 'tree,form',
            'domain': [('config_id', '=', self.id)],
            'context': {'default_config_id': self.id},
        }

    def action_test_webhook(self):
        """Test webhook configuration by sending a test event"""
        self.ensure_one()

        if not self.subscribers:
            raise ValidationError(_("No subscribers configured for this model"))

        # Create a test event
        test_event = self.env['webhook.event'].create({
            'model': self.model_name,
            'record_id': 0,  # Test event
            'event': 'create',
            'priority': self.priority,
            'category': self.category,
            'config_id': self.id,
            'subscriber_id': self.subscribers[0].id,
            'payload': {
                'test': True,
                'message': 'This is a test webhook event',
                'timestamp': fields.Datetime.now().isoformat(),
            }
        })

        # Process the test event
        try:
            test_event.process_event()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Successful'),
                    'message': _('Test webhook sent successfully'),
                    'type': 'success',
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Test Failed'),
                    'message': str(e),
                    'type': 'danger',
                }
            }
