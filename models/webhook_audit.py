# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class WebhookAudit(models.Model):
    """Audit Log for Webhook Events"""

    _name = 'webhook.audit'
    _description = 'Webhook Audit Log'
    _order = 'timestamp desc'
    _rec_name = 'display_name'

    # Event Reference
    event_id = fields.Many2one(
        'webhook.event',
        string='Event',
        ondelete='cascade',
        index=True,
        help='Reference to the webhook event'
    )

    # Action Information
    action = fields.Selection(
        selection=[
            ('created', 'Created'),
            ('sent', 'Sent'),
            ('failed', 'Failed'),
            ('retried', 'Retried'),
            ('archived', 'Archived'),
            ('deleted', 'Deleted'),
            ('status_changed', 'Status Changed'),
        ],
        string='Action',
        required=True,
        index=True,
        help='Type of action performed'
    )
    timestamp = fields.Datetime(
        string='Timestamp',
        required=True,
        default=fields.Datetime.now,
        index=True,
        help='When the action occurred'
    )

    # User Information
    user_id = fields.Many2one(
        'res.users',
        string='User',
        default=lambda self: self.env.user,
        help='User who performed the action'
    )

    # Change Tracking
    old_values = fields.Json(
        string='Old Values',
        help='Values before the change'
    )
    new_values = fields.Json(
        string='New Values',
        help='Values after the change'
    )
    changed_fields = fields.Json(
        string='Changed Fields',
        help='List of fields that were changed'
    )

    # Request Information
    ip_address = fields.Char(
        string='IP Address',
        help='IP address of the request'
    )
    user_agent = fields.Char(
        string='User Agent',
        help='User agent of the request'
    )
    session_id = fields.Char(
        string='Session ID',
        help='Session ID of the request'
    )

    # Additional Information
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this audit entry'
    )

    # Computed Fields
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
    )

    @api.depends('action', 'timestamp', 'user_id')
    def _compute_display_name(self):
        """Compute display name"""
        for record in self:
            user_name = record.user_id.name if record.user_id else 'System'
            timestamp_str = record.timestamp.strftime('%Y-%m-%d %H:%M:%S') if record.timestamp else ''
            record.display_name = f"{record.action} by {user_name} at {timestamp_str}"

    @api.model
    def log_action(self, event_id, action, old_values=None, new_values=None, notes=None):
        """
        Log an audit action

        Args:
            event_id: ID of webhook.event
            action: Action type
            old_values: Dictionary of old values
            new_values: Dictionary of new values
            notes: Additional notes

        Returns:
            webhook.audit record
        """
        try:
            # Determine changed fields
            changed_fields = []
            if old_values and new_values:
                changed_fields = [
                    key for key in new_values.keys()
                    if old_values.get(key) != new_values.get(key)
                ]

            # Get request information
            request = self.env.context.get('request')
            ip_address = None
            user_agent = None

            if request:
                ip_address = request.httprequest.remote_addr
                user_agent = request.httprequest.headers.get('User-Agent')

            # Create audit log
            audit = self.create({
                'event_id': event_id,
                'action': action,
                'old_values': old_values,
                'new_values': new_values,
                'changed_fields': changed_fields,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'notes': notes,
            })

            return audit

        except Exception as e:
            _logger.error(f"Failed to create audit log: {e}")
            return False

    @api.model
    def get_event_history(self, event_id):
        """
        Get complete history for an event

        Args:
            event_id: ID of webhook.event

        Returns:
            List of audit records
        """
        return self.search([
            ('event_id', '=', event_id)
        ], order='timestamp asc')

    @api.model
    def get_user_actions(self, user_id, limit=100):
        """
        Get recent actions by a user

        Args:
            user_id: ID of res.users
            limit: Maximum number of records

        Returns:
            List of audit records
        """
        return self.search([
            ('user_id', '=', user_id)
        ], limit=limit, order='timestamp desc')

    @api.model
    def cleanup_old_logs(self, days=180):
        """
        Clean up old audit logs

        Args:
            days: Number of days to keep

        Returns:
            Number of deleted records
        """
        from datetime import timedelta

        cutoff_date = fields.Datetime.now() - timedelta(days=days)

        old_logs = self.search([
            ('timestamp', '<', cutoff_date)
        ])

        count = len(old_logs)
        old_logs.unlink()

        _logger.info(f"Deleted {count} old audit log records")

        return count

    def action_view_event(self):
        """View the related webhook event"""
        self.ensure_one()

        if not self.event_id:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No Event'),
                    'message': _('No event associated with this audit log'),
                    'type': 'warning',
                }
            }

        return {
            'name': _('Webhook Event'),
            'type': 'ir.actions.act_window',
            'res_model': 'webhook.event',
            'res_id': self.event_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
