# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class WebhookRetry(models.Model):
    """Dead Letter Queue for Failed Webhook Events"""

    _name = 'webhook.retry'
    _description = 'Webhook Dead Letter Queue'
    _order = 'failed_at desc'
    _rec_name = 'display_name'

    # Event Reference
    event_id = fields.Many2one(
        'webhook.event',
        string='Event',
        required=True,
        ondelete='cascade',
        help='Reference to the failed webhook event'
    )

    # Event Details (for quick reference)
    model = fields.Char(
        string='Model',
        related='event_id.model',
        store=True,
        readonly=True,
    )
    record_id = fields.Integer(
        string='Record ID',
        related='event_id.record_id',
        store=True,
        readonly=True,
    )
    event_type = fields.Selection(
        string='Event Type',
        related='event_id.event',
        store=True,
        readonly=True,
    )

    # Failure Information
    original_error = fields.Text(
        string='Original Error',
        help='Error message from the last failed attempt'
    )
    failed_at = fields.Datetime(
        string='Failed At',
        required=True,
        default=fields.Datetime.now,
        help='When the event was moved to dead letter queue'
    )
    retry_attempts = fields.Integer(
        string='Retry Attempts',
        default=0,
        help='Number of retry attempts made before moving to dead letter'
    )

    # Resolution
    resolution_status = fields.Selection(
        selection=[
            ('pending', 'Pending'),
            ('retrying', 'Retrying'),
            ('resolved', 'Resolved'),
            ('ignored', 'Ignored')
        ],
        string='Resolution Status',
        default='pending',
        required=True,
        help='Current resolution status'
    )
    resolved_at = fields.Datetime(
        string='Resolved At',
        help='When the issue was resolved'
    )
    resolved_by = fields.Many2one(
        'res.users',
        string='Resolved By',
        help='User who resolved the issue'
    )
    resolution_notes = fields.Text(
        string='Resolution Notes',
        help='Notes about the resolution'
    )

    # Computed Fields
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )
    can_retry = fields.Boolean(
        string='Can Retry',
        compute='_compute_can_retry',
        help='Whether this event can be retried'
    )

    @api.depends('model', 'record_id', 'event_type')
    def _compute_display_name(self):
        """Compute display name"""
        for record in self:
            record.display_name = f"[{record.model}] {record.event_type} #{record.record_id}"

    @api.depends('resolution_status', 'event_id')
    def _compute_can_retry(self):
        """Check if event can be retried"""
        for record in self:
            record.can_retry = (
                record.resolution_status in ['pending', 'retrying'] and
                record.event_id and
                record.event_id.exists()
            )

    def manual_retry(self):
        """Manually retry a failed event"""
        self.ensure_one()

        if not self.can_retry:
            raise ValidationError(_("This event cannot be retried"))

        try:
            # Update resolution status
            self.write({'resolution_status': 'retrying'})

            # Reset event status
            self.event_id.write({
                'status': 'pending',
                'retry_count': 0,
                'next_retry_at': False,
                'error_message': False,
                'error_type': False,
            })

            # Process the event
            result = self.event_id.process_event()

            if result:
                # Mark as resolved
                self.write({
                    'resolution_status': 'resolved',
                    'resolved_at': fields.Datetime.now(),
                    'resolved_by': self.env.user.id,
                    'resolution_notes': 'Manual retry successful',
                })

                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Success'),
                        'message': _('Event processed successfully'),
                        'type': 'success',
                    }
                }
            else:
                # Keep in retrying status
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Retry Failed'),
                        'message': _('Event retry failed. Check event logs.'),
                        'type': 'warning',
                    }
                }

        except Exception as e:
            _logger.error(f"Error during manual retry: {e}")

            self.write({'resolution_status': 'pending'})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                }
            }

    @api.model
    def bulk_retry(self, event_ids):
        """
        Bulk retry multiple events

        Args:
            event_ids: List of webhook.retry IDs

        Returns:
            Dictionary with results
        """
        records = self.browse(event_ids)

        success_count = 0
        failed_count = 0

        for record in records:
            try:
                if record.can_retry:
                    record.manual_retry()
                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                _logger.error(f"Error retrying event {record.id}: {e}")
                failed_count += 1

        return {
            'total': len(records),
            'success': success_count,
            'failed': failed_count,
        }

    def action_mark_ignored(self):
        """Mark event as ignored"""
        for record in self:
            record.write({
                'resolution_status': 'ignored',
                'resolved_at': fields.Datetime.now(),
                'resolved_by': self.env.user.id,
            })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Marked as Ignored'),
                'message': _('Selected events have been marked as ignored'),
                'type': 'info',
            }
        }

    def action_view_event(self):
        """View the related webhook event"""
        self.ensure_one()

        return {
            'name': _('Webhook Event'),
            'type': 'ir.actions.act_window',
            'res_model': 'webhook.event',
            'res_id': self.event_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
