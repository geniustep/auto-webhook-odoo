# -*- coding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class UserSyncState(models.Model):
    """
    Track synchronization state for each user/device combination

    This model stores the last sync state for BridgeCore Smart Sync,
    enabling incremental sync and multi-device support.
    """
    _name = 'user.sync.state'
    _description = 'User Synchronization State'
    _order = 'last_sync_time desc, user_id, device_id'
    _rec_name = 'display_name'

    # ===== Fields =====

    user_id = fields.Many2one(
        'res.users',
        string='User',
        required=True,
        ondelete='cascade',
        index=True,
        help='User who owns this sync state'
    )

    device_id = fields.Char(
        string='Device ID',
        required=True,
        size=255,
        index=True,
        help='Unique identifier for the device (e.g., UUID, IMEI, etc.)'
    )

    app_type = fields.Selection(
        selection=[
            ('sales_app', 'Sales App'),
            ('delivery_app', 'Delivery App'),
            ('warehouse_app', 'Warehouse App'),
            ('manager_app', 'Manager App'),
            ('mobile_app', 'Mobile App'),
        ],
        string='App Type',
        required=True,
        default='mobile_app',
        index=True,
        help='Type of application using this sync state'
    )

    last_event_id = fields.Integer(
        string='Last Event ID',
        default=0,
        index=True,
        help='ID of the last webhook event synced by this device'
    )

    last_sync_time = fields.Datetime(
        string='Last Sync Time',
        index=True,
        help='Timestamp of the last successful sync'
    )

    sync_count = fields.Integer(
        string='Sync Count',
        default=0,
        help='Total number of sync operations performed'
    )

    is_active = fields.Boolean(
        string='Active',
        default=True,
        index=True,
        help='Whether this sync state is currently active'
    )

    # Metadata
    device_info = fields.Text(
        string='Device Info',
        help='Additional device information (OS, version, etc.)'
    )

    app_version = fields.Char(
        string='App Version',
        size=50,
        help='Version of the mobile app'
    )

    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True
    )

    # Statistics
    last_event_count = fields.Integer(
        string='Last Event Count',
        help='Number of events received in last sync'
    )

    total_events_synced = fields.Integer(
        string='Total Events Synced',
        default=0,
        help='Total number of events synced over lifetime'
    )

    # ===== SQL Constraints =====

    _sql_constraints = [
        ('unique_user_device',
         'UNIQUE(user_id, device_id)',
         'User and device combination must be unique!')
    ]

    # ===== Computed Fields =====

    @api.depends('user_id', 'device_id', 'app_type')
    def _compute_display_name(self):
        """Compute display name for record"""
        for record in self:
            user_name = record.user_id.name if record.user_id else 'Unknown'
            device = record.device_id[:8] if record.device_id else 'Unknown'
            app = dict(record._fields['app_type'].selection).get(record.app_type, 'Unknown')
            record.display_name = f"{user_name} - {device}... ({app})"

    # ===== Validation =====

    @api.constrains('device_id')
    def _check_device_id(self):
        """Validate device_id format"""
        for record in self:
            if not record.device_id or len(record.device_id) < 3:
                raise ValidationError(_('Device ID must be at least 3 characters long'))

    @api.constrains('last_event_id')
    def _check_last_event_id(self):
        """Validate last_event_id is non-negative"""
        for record in self:
            if record.last_event_id < 0:
                raise ValidationError(_('Last event ID cannot be negative'))

    # ===== Business Logic Methods =====

    @api.model
    def get_or_create_state(self, user_id, device_id, app_type):
        """
        Get existing sync state or create new one

        Args:
            user_id (int): User ID
            device_id (str): Device unique identifier
            app_type (str): Application type

        Returns:
            dict: Sync state record data
        """
        # Search for existing state
        existing = self.search([
            ('user_id', '=', user_id),
            ('device_id', '=', device_id)
        ], limit=1)

        if existing:
            # Update app_type if different
            if existing.app_type != app_type:
                existing.write({'app_type': app_type})

            _logger.info(f"Found existing sync state: {existing.id} for user {user_id}, device {device_id}")
            return {
                'id': existing.id,
                'user_id': existing.user_id.id,
                'device_id': existing.device_id,
                'app_type': existing.app_type,
                'last_event_id': existing.last_event_id,
                'last_sync_time': existing.last_sync_time.isoformat() if existing.last_sync_time else None,
                'sync_count': existing.sync_count,
                'is_active': existing.is_active,
            }

        # Create new state
        new_state = self.create({
            'user_id': user_id,
            'device_id': device_id,
            'app_type': app_type,
            'last_event_id': 0,
            'sync_count': 0,
            'is_active': True,
        })

        _logger.info(f"Created new sync state: {new_state.id} for user {user_id}, device {device_id}")
        return {
            'id': new_state.id,
            'user_id': new_state.user_id.id,
            'device_id': new_state.device_id,
            'app_type': new_state.app_type,
            'last_event_id': new_state.last_event_id,
            'last_sync_time': None,
            'sync_count': new_state.sync_count,
            'is_active': new_state.is_active,
        }

    def update_sync_state(self, last_event_id, event_count=0):
        """
        Update sync state after successful sync

        Args:
            last_event_id (int): ID of last event synced
            event_count (int): Number of events in this sync
        """
        self.ensure_one()

        self.write({
            'last_event_id': last_event_id,
            'last_sync_time': fields.Datetime.now(),
            'sync_count': self.sync_count + 1,
            'last_event_count': event_count,
            'total_events_synced': self.total_events_synced + event_count,
        })

        _logger.info(
            f"Updated sync state {self.id}: "
            f"last_event_id={last_event_id}, "
            f"event_count={event_count}, "
            f"sync_count={self.sync_count}"
        )

    def reset_sync_state(self):
        """Reset sync state to force full sync"""
        self.ensure_one()

        self.write({
            'last_event_id': 0,
            'sync_count': 0,
            'last_event_count': 0,
        })

        _logger.info(f"Reset sync state {self.id}")

    def deactivate(self):
        """Deactivate this sync state"""
        self.ensure_one()
        self.write({'is_active': False})
        _logger.info(f"Deactivated sync state {self.id}")

    def activate(self):
        """Activate this sync state"""
        self.ensure_one()
        self.write({'is_active': True})
        _logger.info(f"Activated sync state {self.id}")

    @api.model
    def cleanup_old_states(self, days=90):
        """
        Cleanup inactive sync states older than specified days

        Args:
            days (int): Number of days threshold

        Returns:
            int: Number of deleted records
        """
        from datetime import timedelta

        cutoff_date = datetime.now() - timedelta(days=days)

        old_states = self.search([
            ('is_active', '=', False),
            ('last_sync_time', '<', cutoff_date)
        ])

        count = len(old_states)
        old_states.unlink()

        _logger.info(f"Cleaned up {count} old sync states")
        return count

    @api.model
    def get_sync_statistics(self, user_id=None):
        """
        Get sync statistics

        Args:
            user_id (int, optional): Filter by user ID

        Returns:
            dict: Statistics data
        """
        domain = []
        if user_id:
            domain.append(('user_id', '=', user_id))

        states = self.search(domain)

        return {
            'total_states': len(states),
            'active_states': len(states.filtered('is_active')),
            'inactive_states': len(states.filtered(lambda s: not s.is_active)),
            'total_syncs': sum(states.mapped('sync_count')),
            'total_events_synced': sum(states.mapped('total_events_synced')),
            'by_app_type': {
                app_type: len(states.filtered(lambda s: s.app_type == app_type))
                for app_type, _ in self._fields['app_type'].selection
            }
        }
