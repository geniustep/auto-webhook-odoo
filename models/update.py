from odoo import models, fields, api # type: ignore
import logging
from datetime import timedelta

_logger = logging.getLogger(__name__)

class UpdateWebhook(models.Model):
    _name = "update.webhook"
    _description = "Store webhook updates from FastAPI"
    _order = "timestamp desc"

    model = fields.Char(string="Model", required=True, index=True)
    record_id = fields.Integer(string="Record ID", required=True, index=True)
    event = fields.Selection(
        selection=[('create', 'Create'), ('write', 'Write'), ('unlink', 'Unlink')],
        string="Event",
        required=True,
        index=True,
    )
    timestamp = fields.Datetime(
        string="Timestamp",
        readonly=True,
        required=True,
        default=fields.Datetime.now,
    )

    # Note: Removed unique constraint to allow multiple events for same record
    # This is intentional to track all changes properly

    @api.model_create_multi
    def create(self, vals_list):
        """
        تطبيق القواعد عند إدخال سجل جديد في update.webhook
        
        Rules:
        1. Allow all events to be created (no blocking)
        2. For same record_id:
           - If create comes after write: Delete all previous writes
           - If write comes after create: Ignore the write (create already captures all data)
        """
        created_records = self.env['update.webhook'].browse()
        
        for vals in vals_list:
            try:
                model = vals.get('model')
                record_id = vals.get('record_id')
                event = vals.get('event')
                
                if not model or not record_id or not event:
                    _logger.warning(f"⚠️ Skipping invalid webhook vals: {vals}")
                    continue
                
                # Check for existing records for this model + record_id
                existing_records = self.search([
                    ('model', '=', model),
                    ('record_id', '=', record_id)
                ])
                
                if existing_records:
                    existing_events = existing_records.mapped('event')
                    
                    # Rule 1: If new event is 'create' and there are existing 'write' events
                    # -> Delete all previous writes (create supersedes write)
                    if event == 'create' and 'write' in existing_events:
                        writes_to_delete = existing_records.filtered(lambda r: r.event == 'write')
                        if writes_to_delete:
                            writes_to_delete.unlink()
                            _logger.info(f"🗑️ Deleted {len(writes_to_delete)} write events for {model}:{record_id} (create supersedes)")
                    
                    # Rule 2: If new event is 'write' and there's already a 'create' event
                    # -> Skip this write (create already has all data)
                    elif event == 'write' and 'create' in existing_events:
                        _logger.info(f"⏭️ Skipping write event for {model}:{record_id} (create already exists)")
                        continue
                
                # Create the new record
                record = super(UpdateWebhook, self).create([vals])
                created_records |= record
                _logger.debug(f"✅ Webhook event created: {model}:{record_id} ({event})")
                
            except Exception as e:
                # Log error but don't stop processing other events
                _logger.error(f"❌ Error creating webhook event: {e}", exc_info=True)
                
                # Try to log to webhook.errors if available
                try:
                    if 'webhook.errors' in self.env:
                        self.env['webhook.errors'].create({
                            'model': vals.get('model', 'unknown'),
                            'record_id': vals.get('record_id', 0),
                            'error_message': str(e),
                            'timestamp': fields.Datetime.now()
                        })
                except Exception:
                    pass  # If even error logging fails, just continue
        
        return created_records



class WebhookErrors(models.Model):
    _name = "webhook.errors"
    _description = "Log errors occurring in webhook tracking"
    _order = "timestamp desc"

    model = fields.Char(string="Model", required=True, index=True)
    record_id = fields.Integer(string="Record ID", required=True, index=True)
    error_message = fields.Text(string="Error Message", required=True)
    timestamp = fields.Datetime(
        string="Timestamp",
        readonly=True,
        required=True,
        default=fields.Datetime.now,
    )


class WebhookCleanupCron(models.Model):
    _name = 'webhook.cleanup.cron'
    _description = 'Cron Job to clean up outdated webhook records'

    @api.model
    def clean_webhook_records(self):
        webhook_records = self.env['update.webhook'].search([])
        for record in webhook_records:
            model_obj = self.env.get(record.model)
            if model_obj and not model_obj.search([('id', '=', record.record_id)]):
                record.unlink()
                _logger.info(f"🗑️ Removed orphaned webhook record_id {record.record_id} from {record.model}.")