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

    _sql_constraints = [
        ('unique_event_per_record',
         'unique(model, record_id, event)',
         'Duplicate webhook event for the same record is not allowed!')
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """ تطبيق القواعد عند إدخال سجل جديد في update.webhook """
        for vals in vals_list:
            try:
                existing_records = self.search([
                    ('model', '=', vals['model']),
                    ('record_id', '=', vals['record_id'])
                ])

                # 💥 تحقّق من وجود نفس السجل مسبقًا
                same_record = self.search([
                    ('model', '=', vals['model']),
                    ('record_id', '=', vals['record_id']),
                    ('event', '=', vals['event']),
                ], limit=1)

                if same_record:
                    _logger.warning(f"⚠️ Skipping duplicate webhook for model={vals['model']} record_id={vals['record_id']} event={vals['event']}")
                    continue

                if existing_records:
                    event_list = existing_records.mapped('event')
                    latest_create = sorted(
                        existing_records.filtered(lambda r: r.event == 'create'),
                        key=lambda r: r.timestamp, reverse=True
                    )
                    latest_create = latest_create[0] if latest_create else None

                    if vals['event'] == 'create':
                        existing_writes = existing_records.filtered(lambda r: r.event == 'write')
                        if existing_writes:
                            existing_writes.unlink()
                            _logger.info(f"🗑️ Removed existing Write events for record_id {vals['record_id']} after Create.")

                    if 'create' in event_list and vals['event'] == 'write':
                        _logger.info(f"⏳ Ignoring and removing Write for record_id {vals['record_id']} because Create already exists.")
                        continue

                # ✅ إنشاء السجل
                record = super(UpdateWebhook, self).create([vals])
                _logger.info(f"✅ Webhook event logged: {vals}")
                return record

            except Exception as e:
                self.env['webhook.errors'].create({
                    'model': vals.get('model', 'unknown'),
                    'record_id': vals.get('record_id', 0),
                    'error_message': str(e),
                    'timestamp': fields.Datetime.now()
                })
                _logger.error(f"❌ Error logging webhook event: {e}")



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