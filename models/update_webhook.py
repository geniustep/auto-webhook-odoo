# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
import logging
import json
from datetime import timedelta

_logger = logging.getLogger(__name__)


class UpdateWebhook(models.Model):
    """
    Update Webhook - Pull-based Event Storage

    هذا الـ model يخزن جميع الأحداث (create, write, unlink) لجميع النماذج المتابعة
    مصمم للعمل مع نظام Pull-based حيث BridgeCore يسحب الأحداث بدلاً من Push

    Performance Optimizations:
    - Composite indexes for fast querying
    - Minimal validation for fast writes
    - Bulk operations support
    - Auto-archiving old records
    """

    _name = 'update.webhook'
    _description = 'Update Webhook - Pull-based Event Storage'
    _order = 'id desc'
    _rec_name = 'display_name'

    # === Basic Fields ===
    id = fields.Integer(
        string='ID',
        readonly=True,
        help='Auto-increment ID for sequential event tracking'
    )

    model = fields.Char(
        string='Model',
        required=True,
        index=True,
        help='Technical name of the model (e.g., sale.order)'
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
        help='Type of operation that triggered this event'
    )

    # === Payload ===
    payload = fields.Json(
        string='Payload',
        help='Complete event data in JSON format'
    )

    # === Timestamps ===
    timestamp = fields.Datetime(
        string='Timestamp',
        required=True,
        default=fields.Datetime.now,
        index=True,
        help='When the event occurred'
    )

    # === User Information ===
    user_id = fields.Many2one(
        'res.users',
        string='User',
        default=lambda self: self.env.user,
        index=True,
        help='User who triggered this event'
    )

    # === Processing Status ===
    is_processed = fields.Boolean(
        string='Processed',
        default=False,
        index=True,
        help='Whether this event has been pulled/processed by BridgeCore'
    )

    processed_at = fields.Datetime(
        string='Processed At',
        help='When this event was marked as processed'
    )

    # === Archiving ===
    is_archived = fields.Boolean(
        string='Archived',
        default=False,
        index=True,
        help='Whether this event has been archived (for cleanup)'
    )

    archived_at = fields.Datetime(
        string='Archived At',
        help='When this event was archived'
    )

    # === Relations ===
    config_id = fields.Many2one(
        'webhook.config',
        string='Webhook Config',
        index=True,
        ondelete='set null',
        help='Reference to the webhook configuration'
    )

    priority = fields.Selection(
        selection=[
            ('high', 'High'),
            ('medium', 'Medium'),
            ('low', 'Low')
        ],
        string='Priority',
        default='medium',
        index=True,
        help='Event priority (from config)'
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
        help='Event category (from config)'
    )

    # === Computed Fields ===
    display_name = fields.Char(
        string='Display Name',
        compute='_compute_display_name',
        store=True,
        help='Human-readable event description'
    )

    payload_size = fields.Integer(
        string='Payload Size (bytes)',
        compute='_compute_payload_size',
        help='Size of the payload in bytes'
    )

    age_days = fields.Integer(
        string='Age (days)',
        compute='_compute_age',
        help='How many days old this event is'
    )

    # === SQL Constraints ===
    # Note: record_id can be -1 for test events, 0 is not allowed
    _sql_constraints = [
        ('check_record_id',
         'CHECK(record_id != 0)',
         'Record ID cannot be 0 (use -1 for test events)'),
    ]

    @api.depends('model', 'event', 'record_id', 'timestamp')
    def _compute_display_name(self):
        """Compute human-readable display name"""
        for record in self:
            timestamp_str = record.timestamp.strftime('%Y-%m-%d %H:%M:%S') if record.timestamp else 'N/A'
            record.display_name = f"[{record.model}] {record.event} #{record.record_id} @ {timestamp_str}"

    @api.depends('payload')
    def _compute_payload_size(self):
        """Compute payload size in bytes"""
        for record in self:
            if record.payload:
                try:
                    record.payload_size = len(json.dumps(record.payload).encode('utf-8'))
                except Exception:
                    record.payload_size = 0
            else:
                record.payload_size = 0

    @api.depends('timestamp')
    def _compute_age(self):
        """Compute age in days"""
        for record in self:
            if record.timestamp:
                delta = fields.Datetime.now() - record.timestamp
                record.age_days = delta.days
            else:
                record.age_days = 0

    def _auto_init(self):
        """Create composite indexes for optimal performance"""
        res = super()._auto_init()

        # Composite indexes for common query patterns
        indexes = [
            # Primary pull query: unprocessed events by ID
            ('idx_update_webhook_pull',
             'id, is_processed, is_archived',
             "is_processed = false AND is_archived = false"),

            # Query by model and timestamp
            ('idx_update_webhook_model_time',
             'model, timestamp DESC'),

            # Cleanup query: old processed events
            ('idx_update_webhook_cleanup',
             'is_processed, timestamp',
             "is_processed = true"),

            # Archive query
            ('idx_update_webhook_archive',
             'is_archived, timestamp'),

            # Priority-based queries
            ('idx_update_webhook_priority',
             'priority, is_processed, timestamp DESC'),

            # User activity tracking
            ('idx_update_webhook_user',
             'user_id, timestamp DESC'),
        ]

        for index_name, columns, *where in indexes:
            where_clause = where[0] if where else None
            self._create_index_if_not_exists(index_name, columns, where_clause)

        return res

    def _create_index_if_not_exists(self, index_name, columns, where_clause=None):
        """Helper method to create index if it doesn't exist"""
        try:
            self.env.cr.execute(f"""
                SELECT 1 FROM pg_indexes
                WHERE tablename = 'update_webhook'
                AND indexname = '{index_name}'
            """)

            if not self.env.cr.fetchone():
                where_sql = f" WHERE {where_clause}" if where_clause else ""
                sql = f"CREATE INDEX {index_name} ON update_webhook ({columns}){where_sql}"
                _logger.info(f"Creating index: {sql}")
                self.env.cr.execute(sql)
        except Exception as e:
            _logger.warning(f"Failed to create index {index_name}: {e}")

    @api.model
    def create_event(self, model_name, record_id, event_type, payload_data, config=None):
        """
        Fast event creation method

        Args:
            model_name: Technical name of the model
            record_id: ID of the record
            event_type: Type of event (create/write/unlink)
            payload_data: Complete payload as dict
            config: webhook.config record (optional)

        Returns:
            update.webhook record or False
        """
        try:
            vals = {
                'model': model_name,
                'record_id': record_id,
                'event': event_type,
                'payload': payload_data,
                'timestamp': fields.Datetime.now(),
                'user_id': self.env.user.id,
                'is_processed': False,
                'is_archived': False,
            }

            # Add config information if provided
            if config:
                vals.update({
                    'config_id': config.id,
                    'priority': config.priority,
                    'category': config.category,
                })

            # Fast create without extra validations
            # Use sudo() to avoid permission issues during write operations
            return self.sudo().create(vals)

        except Exception as e:
            _logger.error(f"Failed to create update.webhook event: {e}")
            return False

    @api.model
    def create_bulk_events(self, events_data):
        """
        Bulk create multiple events at once

        Args:
            events_data: List of dicts with event data

        Returns:
            List of created records
        """
        try:
            vals_list = []
            now = fields.Datetime.now()
            user_id = self.env.user.id

            for event in events_data:
                vals = {
                    'model': event['model'],
                    'record_id': event['record_id'],
                    'event': event['event_type'],
                    'payload': event.get('payload', {}),
                    'timestamp': now,
                    'user_id': user_id,
                    'is_processed': False,
                    'is_archived': False,
                }

                if event.get('config'):
                    vals.update({
                        'config_id': event['config'].id,
                        'priority': event['config'].priority,
                        'category': event['config'].category,
                    })

                vals_list.append(vals)

            # Bulk create
            return self.sudo().create(vals_list)

        except Exception as e:
            _logger.error(f"Failed to bulk create update.webhook events: {e}")
            return self.browse()

    @api.model
    def pull_events(self, last_event_id=0, limit=100, models=None, priority=None):
        """
        Pull unprocessed events for BridgeCore API

        Args:
            last_event_id: Last event ID that was pulled (default: 0)
            limit: Maximum number of events to return (default: 100)
            models: List of model names to filter (optional)
            priority: Priority filter (high/medium/low) (optional)

        Returns:
            {
                'events': [...],
                'last_id': 550,
                'has_more': true,
                'count': 100
            }
        """
        try:
            domain = [
                ('id', '>', last_event_id),
                ('is_processed', '=', False),
                ('is_archived', '=', False),
            ]

            # Add model filter
            if models:
                domain.append(('model', 'in', models))

            # Add priority filter
            if priority:
                domain.append(('priority', '=', priority))

            # Search for events
            events = self.sudo().search(
                domain,
                limit=limit,
                order='id asc'
            )

            # Check if there are more events
            has_more = False
            if events:
                last_id = events[-1].id
                has_more = bool(self.sudo().search_count([
                    ('id', '>', last_id),
                    ('is_processed', '=', False),
                    ('is_archived', '=', False),
                ]))
            else:
                last_id = last_event_id

            # Format events for response
            events_data = []
            for event in events:
                events_data.append({
                    'id': event.id,
                    'model': event.model,
                    'record_id': event.record_id,
                    'event': event.event,
                    'timestamp': event.timestamp.isoformat() if event.timestamp else None,
                    'payload': event.payload,
                    'priority': event.priority,
                    'category': event.category,
                    'user_id': event.user_id.id if event.user_id else None,
                    'user_name': event.user_id.name if event.user_id else None,
                })

            return {
                'events': events_data,
                'last_id': last_id,
                'has_more': has_more,
                'count': len(events_data),
            }

        except Exception as e:
            _logger.error(f"Failed to pull events: {e}")
            return {
                'events': [],
                'last_id': last_event_id,
                'has_more': False,
                'count': 0,
                'error': str(e),
            }

    def mark_as_processed(self):
        """Mark events as processed"""
        try:
            self.sudo().write({
                'is_processed': True,
                'processed_at': fields.Datetime.now(),
            })
            _logger.info(f"Marked {len(self)} events as processed")
            return True
        except Exception as e:
            _logger.error(f"Failed to mark events as processed: {e}")
            return False

    @api.model
    def mark_batch_as_processed(self, event_ids):
        """
        Mark multiple events as processed (bulk operation)

        Args:
            event_ids: List of event IDs
        """
        try:
            events = self.sudo().browse(event_ids)
            events.write({
                'is_processed': True,
                'processed_at': fields.Datetime.now(),
            })
            _logger.info(f"Marked {len(events)} events as processed (batch)")
            return True
        except Exception as e:
            _logger.error(f"Failed to mark batch as processed: {e}")
            return False

    @api.model
    def cleanup_old_events(self, days_to_archive=7, days_to_delete=30):
        """
        Cleanup old events (called by cron)

        Args:
            days_to_archive: Archive processed events older than this (default: 7 days)
            days_to_delete: Delete archived events older than this (default: 30 days)
        """
        try:
            # Step 1: Archive old processed events
            archive_cutoff = fields.Datetime.now() - timedelta(days=days_to_archive)
            to_archive = self.sudo().search([
                ('is_processed', '=', True),
                ('is_archived', '=', False),
                ('timestamp', '<', archive_cutoff),
            ])

            if to_archive:
                to_archive.write({
                    'is_archived': True,
                    'archived_at': fields.Datetime.now(),
                })
                _logger.info(f"Archived {len(to_archive)} old processed events")

            # Step 2: Delete very old archived events
            delete_cutoff = fields.Datetime.now() - timedelta(days=days_to_delete)
            to_delete = self.sudo().search([
                ('is_archived', '=', True),
                ('timestamp', '<', delete_cutoff),
            ])

            if to_delete:
                count = len(to_delete)
                to_delete.unlink()
                _logger.info(f"Deleted {count} very old archived events")

            return {
                'archived': len(to_archive) if to_archive else 0,
                'deleted': count if to_delete else 0,
            }

        except Exception as e:
            _logger.error(f"Failed to cleanup old events: {e}")
            return {'archived': 0, 'deleted': 0, 'error': str(e)}

    @api.model
    def get_statistics(self, days=7):
        """
        Get statistics about events

        Args:
            days: Number of days to look back (default: 7)

        Returns:
            Dict with statistics
        """
        try:
            cutoff = fields.Datetime.now() - timedelta(days=days)

            total = self.sudo().search_count([
                ('timestamp', '>=', cutoff)
            ])

            processed = self.sudo().search_count([
                ('timestamp', '>=', cutoff),
                ('is_processed', '=', True),
            ])

            pending = self.sudo().search_count([
                ('timestamp', '>=', cutoff),
                ('is_processed', '=', False),
                ('is_archived', '=', False),
            ])

            archived = self.sudo().search_count([
                ('timestamp', '>=', cutoff),
                ('is_archived', '=', True),
            ])

            # Events by model
            self.env.cr.execute("""
                SELECT model, COUNT(*) as count
                FROM update_webhook
                WHERE timestamp >= %s
                GROUP BY model
                ORDER BY count DESC
                LIMIT 10
            """, (cutoff,))

            by_model = [
                {'model': row[0], 'count': row[1]}
                for row in self.env.cr.fetchall()
            ]

            # Events by priority
            self.env.cr.execute("""
                SELECT priority, COUNT(*) as count
                FROM update_webhook
                WHERE timestamp >= %s
                GROUP BY priority
                ORDER BY count DESC
            """, (cutoff,))

            by_priority = {
                row[0]: row[1]
                for row in self.env.cr.fetchall()
            }

            return {
                'period_days': days,
                'total': total,
                'processed': processed,
                'pending': pending,
                'archived': archived,
                'by_model': by_model,
                'by_priority': by_priority,
            }

        except Exception as e:
            _logger.error(f"Failed to get statistics: {e}")
            return {'error': str(e)}

    def action_mark_processed(self):
        """Action: Mark selected events as processed"""
        self.mark_as_processed()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('%d event(s) marked as processed') % len(self),
                'type': 'success',
            }
        }

    def action_unmark_processed(self):
        """Action: Unmark events as processed (for re-processing)"""
        try:
            self.sudo().write({
                'is_processed': False,
                'processed_at': False,
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('%d event(s) unmarked as processed') % len(self),
                    'type': 'success',
                }
            }
        except Exception as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                }
            }
