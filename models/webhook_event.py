# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
import json
import requests
from datetime import timedelta

_logger = logging.getLogger(__name__)


class WebhookEvent(models.Model):
    """Enhanced Webhook Event Model for Enterprise-Grade Event Tracking"""

    _name = 'webhook.event'
    _description = 'Webhook Event'
    _order = 'priority desc, timestamp desc'
    _rec_name = 'display_name'

    # Basic Fields
    model = fields.Char(
        string='Model',
        required=True,
        index=True,
        help='Technical name of the model'
    )
    record_id = fields.Integer(
        string='Record ID',
        required=True,
        index=True,
        help='ID of the record that triggered the event'
    )
    event = fields.Selection(
        selection=[
            ('create', 'Create'),
            ('write', 'Write'),
            ('unlink', 'Delete')
        ],
        string='Event Type',
        required=True,
        index=True,
        help='Type of operation that triggered the event'
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        required=True,
        default=fields.Datetime.now,
        index=True,
        help='When the event was created'
    )

    # Priority and Categorization
    priority = fields.Selection(
        selection=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low')
        ],
        string='Priority',
        required=True,
        default='medium',
        index=True,
        help='Event priority for processing order'
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
        index=True,
        help='Event category for filtering and reporting'
    )

    # Status and Processing
    status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('dead', 'Dead Letter')
        ],
        string='Status',
        required=True,
        default='pending',
        index=True,
        help='Current status of the event'
    )

    # Retry Management
    retry_count = fields.Integer(
        string='Retry Count',
        default=0,
        help='Number of retry attempts made'
    )
    max_retries = fields.Integer(
        string='Max Retries',
        default=5,
        help='Maximum number of retry attempts allowed'
    )
    next_retry_at = fields.Datetime(
        string='Next Retry At',
        index=True,
        help='Scheduled time for next retry attempt'
    )

    # Error Information
    error_message = fields.Text(
        string='Error Message',
        help='Last error message encountered'
    )
    error_type = fields.Char(
        string='Error Type',
        help='Type of error (timeout, connection, etc.)'
    )
    error_code = fields.Integer(
        string='Error Code',
        help='HTTP error code or system error code'
    )

    # Payload and Data
    payload = fields.Json(
        string='Payload',
        help='Complete event data including old and new values'
    )
    changed_fields = fields.Json(
        string='Changed Fields',
        help='List of fields that were modified (for write events)'
    )

    # Relations
    subscriber_id = fields.Many2one(
        'webhook.subscriber',
        string='Subscriber',
        index=True,
        ondelete='set null',
        help='Subscriber endpoint for this event'
    )
    template_id = fields.Many2one(
        'webhook.template',
        string='Template',
        ondelete='set null',
        help='Template used to format the event payload'
    )
    config_id = fields.Many2one(
        'webhook.config',
        string='Configuration',
        index=True,
        ondelete='set null',
        help='Webhook configuration for this model'
    )

    # Response Information
    sent_at = fields.Datetime(
        string='Sent At',
        help='When the event was successfully sent'
    )
    response_code = fields.Integer(
        string='Response Code',
        help='HTTP response code from the subscriber'
    )
    response_body = fields.Text(
        string='Response Body',
        help='Response body from the subscriber'
    )
    processing_time = fields.Float(
        string='Processing Time (ms)',
        help='Time taken to process and send the event in milliseconds'
    )

    # Computed Fields
    bridgecore_url = fields.Char(
        string='BridgeCore URL',
        related='subscriber_id.endpoint_url',
        readonly=True,
        help='Target URL for webhook delivery'
    )
    is_archived = fields.Boolean(
        string='Archived',
        default=False,
        help='Whether this event has been archived'
    )
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
        help='Human-readable name for the event'
    )
    can_retry = fields.Boolean(
        string='Can Retry',
        compute='_compute_can_retry',
        help='Whether this event can be retried'
    )
    next_retry_in = fields.Char(
        string='Next Retry In',
        compute='_compute_next_retry_in',
        help='Human-readable time until next retry'
    )

    # SQL Constraints
    _sql_constraints = [
        ('check_retry_count',
         'CHECK(retry_count <= max_retries)',
         'Retry count cannot exceed max retries'),
        ('check_priority',
         "CHECK(priority IN ('high', 'medium', 'low'))",
         'Invalid priority value'),
    ]

    @api.depends('model', 'event', 'record_id', 'status')
    def _compute_display_name(self):
        """Compute human-readable display name"""
        for record in self:
            record.display_name = f"[{record.model}] {record.event} #{record.record_id} - {record.status}"

    @api.depends('retry_count', 'max_retries', 'status')
    def _compute_can_retry(self):
        """Check if event can be retried"""
        for record in self:
            record.can_retry = (
                record.retry_count < record.max_retries and
                record.status == 'failed'
            )

    @api.depends('next_retry_at')
    def _compute_next_retry_in(self):
        """Compute human-readable time until next retry"""
        for record in self:
            if not record.next_retry_at:
                record.next_retry_in = False
            else:
                now = fields.Datetime.now()
                if record.next_retry_at > now:
                    delta = record.next_retry_at - now
                    minutes = int(delta.total_seconds() / 60)
                    if minutes < 60:
                        record.next_retry_in = f"in {minutes} minute(s)"
                    else:
                        hours = int(minutes / 60)
                        record.next_retry_in = f"in {hours} hour(s)"
                else:
                    record.next_retry_in = "Ready for retry"

    def _auto_init(self):
        """Create composite indexes for better performance"""
        res = super()._auto_init()

        # Composite indexes
        indexes = [
            ('idx_webhook_event_processing', 'model, status, priority, timestamp DESC'),
            ('idx_webhook_event_retry', 'status, next_retry_at', "WHERE status='failed'"),
            ('idx_webhook_event_subscriber', 'subscriber_id, status, timestamp DESC'),
            ('idx_webhook_event_config', 'config_id, timestamp DESC'),
            ('idx_webhook_event_pending', 'timestamp', "WHERE status='pending'"),
        ]

        for index_name, columns, *where in indexes:
            where_clause = where[0] if where else None
            self._create_index_if_not_exists(index_name, columns, where_clause)

        return res

    def _create_index_if_not_exists(self, index_name, columns, where_clause=None):
        """Helper method to create index if it doesn't exist"""
        self.env.cr.execute(f"""
            SELECT 1 FROM pg_indexes
            WHERE tablename = 'webhook_event'
            AND indexname = '{index_name}'
        """)

        if not self.env.cr.fetchone():
            where_sql = f" WHERE {where_clause}" if where_clause else ""
            sql = f"CREATE INDEX {index_name} ON webhook_event ({columns}){where_sql}"
            _logger.info(f"Creating index: {sql}")
            self.env.cr.execute(sql)

    @api.model
    def create_event(self, model_name, record_id, event_type, vals=None, config=None, subscriber=None):
        """
        Static method to create a webhook event

        Args:
            model_name: Technical name of the model
            record_id: ID of the record
            event_type: Type of event (create/write/unlink)
            vals: Dictionary of values (for payload)
            config: webhook.config record
            subscriber: webhook.subscriber record

        Returns:
            webhook.event record or False
        """
        try:
            event_vals = {
                'model': model_name,
                'record_id': record_id,
                'event': event_type,
                'status': 'pending',
                'payload': vals or {},
            }

            # Add config information
            if config:
                event_vals.update({
                    'config_id': config.id,
                    'priority': config.priority,
                    'category': config.category,
                })

                # Add template if configured
                if config.template_id:
                    event_vals['template_id'] = config.template_id.id

                # Add subscriber if configured
                if config.subscribers:
                    event_vals['subscriber_id'] = config.subscribers[0].id

            # Override subscriber if provided
            if subscriber:
                event_vals['subscriber_id'] = subscriber.id

            return self.sudo().create(event_vals)

        except Exception as e:
            _logger.error(f"Failed to create webhook event: {e}")
            return False

    def process_event(self):
        """Process a single webhook event"""
        self.ensure_one()

        if self.status not in ['pending', 'failed']:
            _logger.warning(f"Event {self.id} has status {self.status}, cannot process")
            return False

        try:
            # Update status to processing
            self.write({'status': 'processing'})

            # Get subscriber
            if not self.subscriber_id:
                raise ValidationError(_("No subscriber configured for this event"))

            # Build payload
            payload = self._build_payload()

            # Send to subscriber
            start_time = fields.Datetime.now()
            response = self.subscriber_id.send_event_data(payload)
            end_time = fields.Datetime.now()

            processing_time = (end_time - start_time).total_seconds() * 1000

            # Update event with success
            self.write({
                'status': 'sent',
                'sent_at': end_time,
                'response_code': response.get('status_code'),
                'response_body': json.dumps(response.get('body', {})),
                'processing_time': processing_time,
                'error_message': False,
                'error_type': False,
                'error_code': False,
            })

            # Create audit log
            self.env['webhook.audit'].sudo().create({
                'event_id': self.id,
                'action': 'sent',
                'timestamp': end_time,
            })

            return True

        except Exception as e:
            _logger.error(f"Failed to process event {self.id}: {e}")

            # Schedule retry
            self.schedule_retry(str(e))

            return False

    def schedule_retry(self, error_message=None):
        """Schedule retry with exponential backoff"""
        self.ensure_one()

        if self.retry_count >= self.max_retries:
            self.mark_as_dead(error_message)
            return False

        # Calculate next retry time using exponential backoff
        base_delay = 60  # 60 seconds
        delay_seconds = base_delay * (2 ** self.retry_count)
        next_retry = fields.Datetime.now() + timedelta(seconds=delay_seconds)

        # Update event
        self.write({
            'status': 'failed',
            'retry_count': self.retry_count + 1,
            'next_retry_at': next_retry,
            'error_message': error_message,
            'error_type': 'retry_scheduled',
        })

        # Create audit log
        self.env['webhook.audit'].sudo().create({
            'event_id': self.id,
            'action': 'retried',
            'timestamp': fields.Datetime.now(),
        })

        _logger.info(f"Event {self.id} scheduled for retry {self.retry_count} at {next_retry}")

        return True

    def mark_as_dead(self, error_message=None):
        """Move event to dead letter queue"""
        self.ensure_one()

        self.write({
            'status': 'dead',
            'error_message': error_message,
            'error_type': 'max_retries_exceeded',
        })

        # Create dead letter record
        self.env['webhook.retry'].sudo().create({
            'event_id': self.id,
            'original_error': error_message,
            'failed_at': fields.Datetime.now(),
            'retry_attempts': self.retry_count,
            'resolution_status': 'pending',
        })

        # Send notification to admins
        try:
            self.env['webhook.notification.service'].notify_dead_letter(self)
        except Exception as e:
            _logger.error(f"Failed to send dead letter notification: {e}")

        _logger.warning(f"Event {self.id} moved to dead letter queue")

        return True

    @api.model
    def process_pending_events(self, limit=100):
        """Process pending events in batch"""
        events = self.search([
            ('status', '=', 'pending')
        ], limit=limit, order='priority desc, timestamp asc')

        _logger.info(f"Processing {len(events)} pending events")

        success_count = 0
        failed_count = 0

        for event in events:
            try:
                if event.process_event():
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                _logger.error(f"Error processing event {event.id}: {e}")
                failed_count += 1

        _logger.info(f"Processed {success_count} events successfully, {failed_count} failed")

        return {
            'total': len(events),
            'success': success_count,
            'failed': failed_count,
        }

    @api.model
    def process_retries(self):
        """Process events ready for retry"""
        now = fields.Datetime.now()
        events = self.search([
            ('status', '=', 'failed'),
            ('next_retry_at', '<=', now),
            ('retry_count', '<', self._fields['max_retries'].default)
        ], limit=50)

        _logger.info(f"Processing {len(events)} retry events")

        for event in events:
            try:
                event.process_event()
            except Exception as e:
                _logger.error(f"Error retrying event {event.id}: {e}")

    @api.model
    def cleanup_old_events(self, days=90):
        """Clean up old events (archive or delete)"""
        cutoff_date = fields.Datetime.now() - timedelta(days=days)

        # Archive important events (sent successfully)
        important_events = self.search([
            ('timestamp', '<', cutoff_date),
            ('status', '=', 'sent'),
            ('priority', 'in', ['high', 'medium']),
            ('is_archived', '=', False)
        ])

        if important_events:
            important_events.write({'is_archived': True})
            _logger.info(f"Archived {len(important_events)} important events")

        # Delete old unimportant events
        old_events = self.search([
            ('timestamp', '<', cutoff_date),
            ('status', 'in', ['sent', 'dead']),
            ('priority', '=', 'low'),
        ])

        if old_events:
            count = len(old_events)
            old_events.unlink()
            _logger.info(f"Deleted {count} old unimportant events")

        return True

    def _build_payload(self):
        """Build the payload for webhook delivery"""
        self.ensure_one()

        payload = {
            'event_id': self.id,
            'model': self.model,
            'record_id': self.record_id,
            'event': self.event,
            'timestamp': self.timestamp.isoformat(),
            'priority': self.priority,
            'category': self.category,
        }

        # Add custom payload data
        if self.payload:
            payload['data'] = self.payload

        # Add changed fields for write events
        if self.event == 'write' and self.changed_fields:
            payload['changed_fields'] = self.changed_fields

        # Apply template if configured
        if self.template_id:
            try:
                payload = self.template_id.render_payload(self, payload)
            except Exception as e:
                _logger.error(f"Error applying template {self.template_id.id}: {e}")

        return payload

    def action_retry_now(self):
        """Manual retry action from UI"""
        for record in self:
            if record.can_retry:
                record.process_event()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Retry Initiated'),
                'message': _('Event retry has been initiated'),
                'type': 'success',
            }
        }

    def action_mark_dead(self):
        """Manual mark as dead action from UI"""
        for record in self:
            record.mark_as_dead("Manually marked as dead by user")

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Moved to Dead Letter'),
                'message': _('Event moved to dead letter queue'),
                'type': 'warning',
            }
        }
