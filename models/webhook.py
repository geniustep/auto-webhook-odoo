from odoo import models, fields, api # type: ignore
import logging

_logger = logging.getLogger(__name__)

class WebhookMixin(models.AbstractModel):
    _name = 'webhook.mixin'
    _description = 'Webhook Mixin for tracking model changes'


    def _log_webhook_event(self, event):
        """تسجيل الحدث دون الحاجة إلى _is_tracked_model"""
        _logger.info(f"📡 WebhookMixin: Logging {event} for {self._name}")
        records = [{
            "model": record._name,
            "record_id": record.id,
            "event": event,
            "timestamp": fields.Datetime.now()
        } for record in self]

        self.env['update.webhook'].sudo().create(records)


    @api.model_create_multi
    def create(self, vals_list):
        records = super(WebhookMixin, self).create(vals_list)
        records._log_webhook_event("create")
        return records

    def write(self, vals):
        res = super(WebhookMixin, self).write(vals)
        self._log_webhook_event("write")
        return res

    def unlink(self):
        self._log_webhook_event("unlink")
        return super(WebhookMixin, self).unlink()
