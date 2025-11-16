# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
import json
from jinja2 import Template, TemplateError

_logger = logging.getLogger(__name__)


class WebhookTemplate(models.Model):
    """Webhook Template for Custom Event Formatting"""

    _name = 'webhook.template'
    _description = 'Webhook Template'
    _order = 'name'

    # Basic Information
    name = fields.Char(
        string='Template Name',
        required=True,
        help='Name of the template'
    )
    code = fields.Char(
        string='Template Code',
        required=True,
        help='Unique code for the template'
    )
    model_id = fields.Many2one(
        'ir.model',
        string='Model',
        required=True,
        ondelete='cascade',
        help='Model this template applies to'
    )
    model_name = fields.Char(
        string='Model Technical Name',
        related='model_id.model',
        store=True,
        help='Technical name of the model'
    )
    event_type = fields.Selection(
        selection=[
            ('create', 'Create'),
            ('write', 'Write'),
            ('unlink', 'Delete'),
            ('custom', 'Custom')
        ],
        string='Event Type',
        default='create',
        help='Type of event this template applies to'
    )

    # Template Configuration
    payload_template = fields.Text(
        string='Payload Template',
        required=True,
        help='Jinja2 template for the event payload'
    )
    included_fields = fields.Many2many(
        'ir.model.fields',
        'webhook_template_include_field_rel',
        'template_id',
        'field_id',
        string='Included Fields',
        domain="[('model_id', '=', model_id)]",
        help='Fields to include in the payload'
    )
    excluded_fields = fields.Many2many(
        'ir.model.fields',
        'webhook_template_exclude_field_rel',
        'template_id',
        'field_id',
        string='Excluded Fields',
        domain="[('model_id', '=', model_id)]",
        help='Fields to exclude from the payload'
    )

    # Transformations
    transformations = fields.Json(
        string='Field Transformations',
        help='JSON object defining field transformations'
    )

    # Status
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Archive/Unarchive this template'
    )
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this template'
    )

    # SQL Constraints
    _sql_constraints = [
        ('unique_code',
         'UNIQUE(code)',
         'Template code must be unique!'),
    ]

    @api.constrains('code')
    def _check_code(self):
        """Validate template code"""
        for record in self:
            if record.code and not record.code.replace('_', '').replace('-', '').isalnum():
                raise ValidationError(
                    _("Template code can only contain letters, numbers, hyphens and underscores")
                )

    @api.constrains('payload_template')
    def _check_payload_template(self):
        """Validate Jinja2 template syntax"""
        for record in self:
            if record.payload_template:
                try:
                    Template(record.payload_template)
                except TemplateError as e:
                    raise ValidationError(
                        _("Invalid Jinja2 template syntax: %s") % str(e)
                    )

    @api.constrains('transformations')
    def _check_transformations(self):
        """Validate transformations JSON"""
        for record in self:
            if record.transformations:
                if not isinstance(record.transformations, dict):
                    raise ValidationError(
                        _("Transformations must be a JSON object")
                    )

    def render_payload(self, event, base_payload):
        """
        Render template with event data

        Args:
            event: webhook.event record
            base_payload: Base payload dictionary

        Returns:
            Rendered payload dictionary
        """
        self.ensure_one()

        try:
            # Get the record
            record = self.env[event.model].browse(event.record_id)
            if not record.exists():
                _logger.warning(f"Record {event.model}:{event.record_id} not found")
                return base_payload

            # Build template context
            context = {
                'event': event.event,
                'model': event.model,
                'record_id': event.record_id,
                'record': self._prepare_record_data(record),
                'timestamp': event.timestamp.isoformat(),
                'priority': event.priority,
                'category': event.category,
                'changed_fields': event.changed_fields or [],
            }

            # Add base payload data
            if base_payload.get('data'):
                context['data'] = base_payload['data']

            # Render template
            template = Template(self.payload_template)
            rendered = template.render(**context)

            # Parse rendered JSON
            payload = json.loads(rendered)

            # Apply transformations
            if self.transformations:
                payload = self._apply_transformations(payload)

            return payload

        except TemplateError as e:
            _logger.error(f"Template rendering error: {e}")
            return base_payload

        except json.JSONDecodeError as e:
            _logger.error(f"Invalid JSON from template: {e}")
            return base_payload

        except Exception as e:
            _logger.error(f"Error rendering template: {e}")
            return base_payload

    def _prepare_record_data(self, record):
        """
        Prepare record data for template context

        Args:
            record: Odoo record

        Returns:
            Dictionary of record data
        """
        self.ensure_one()

        data = {}

        # Get all fields
        fields_to_include = self.included_fields or record._fields.values()

        for field in fields_to_include:
            field_name = field.name if hasattr(field, 'name') else str(field)

            # Skip excluded fields
            if self.excluded_fields and field_name in self.excluded_fields.mapped('name'):
                continue

            # Skip computed fields without store
            if hasattr(field, 'store') and not field.store:
                continue

            try:
                value = record[field_name]

                # Convert field value to JSON-serializable format
                if isinstance(value, models.BaseModel):
                    # Many2one
                    if value:
                        data[field_name] = {
                            'id': value.id,
                            'name': value.display_name,
                        }
                    else:
                        data[field_name] = None

                elif isinstance(value, (list, tuple)):
                    # Many2many or One2many
                    data[field_name] = [{
                        'id': rec.id,
                        'name': rec.display_name,
                    } for rec in value]

                elif hasattr(value, 'isoformat'):
                    # Date or Datetime
                    data[field_name] = value.isoformat()

                else:
                    # Simple field
                    data[field_name] = value

            except Exception as e:
                _logger.warning(f"Could not read field {field_name}: {e}")
                continue

        return data

    def _apply_transformations(self, payload):
        """
        Apply field transformations to payload

        Args:
            payload: Payload dictionary

        Returns:
            Transformed payload
        """
        self.ensure_one()

        if not self.transformations:
            return payload

        for field_name, transformation in self.transformations.items():
            if field_name not in payload:
                continue

            try:
                value = payload[field_name]

                # Apply transformation based on type
                if transformation == 'currency_format':
                    payload[field_name] = f"{value:.2f}"

                elif transformation == 'uppercase':
                    payload[field_name] = str(value).upper()

                elif transformation == 'lowercase':
                    payload[field_name] = str(value).lower()

                elif transformation == 'date_only' and hasattr(value, 'date'):
                    payload[field_name] = value.date().isoformat()

                elif transformation == 'boolean_string':
                    payload[field_name] = 'yes' if value else 'no'

                # Add more transformations as needed

            except Exception as e:
                _logger.warning(f"Failed to apply transformation {transformation} to {field_name}: {e}")

        return payload

    def preview(self, record_id):
        """
        Preview template output

        Args:
            record_id: ID of a record to use for preview

        Returns:
            Dictionary with preview data
        """
        self.ensure_one()

        if not record_id:
            raise ValidationError(_("Please provide a record ID for preview"))

        try:
            # Get the record
            record = self.env[self.model_name].browse(record_id)
            if not record.exists():
                raise ValidationError(_("Record not found"))

            # Create a mock event
            mock_event = self.env['webhook.event'].new({
                'model': self.model_name,
                'record_id': record_id,
                'event': self.event_type,
                'priority': 'medium',
                'category': 'business',
                'timestamp': fields.Datetime.now(),
            })

            # Build base payload
            base_payload = {
                'event_id': 0,
                'model': self.model_name,
                'record_id': record_id,
                'event': self.event_type,
            }

            # Render template
            rendered = self.render_payload(mock_event, base_payload)

            return {
                'success': True,
                'payload': rendered,
            }

        except Exception as e:
            return {
                'success': False,
                'error': str(e),
            }

    def action_preview_template(self):
        """UI action to preview template"""
        self.ensure_one()

        # Get a sample record
        sample_record = self.env[self.model_name].search([], limit=1)
        if not sample_record:
            raise ValidationError(_("No records found for model %s") % self.model_id.name)

        result = self.preview(sample_record.id)

        if result['success']:
            message = json.dumps(result['payload'], indent=2)
            notification_type = 'success'
        else:
            message = result['error']
            notification_type = 'danger'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Template Preview'),
                'message': message,
                'type': notification_type,
                'sticky': True,
            }
        }

    @api.model
    def create_default_template(self, model_id, template_type='standard'):
        """
        Create a default template for a model

        Args:
            model_id: ir.model ID
            template_type: Type of template to create

        Returns:
            webhook.template record
        """
        model = self.env['ir.model'].browse(model_id)
        if not model.exists():
            raise ValidationError(_("Model not found"))

        # Standard template
        if template_type == 'standard':
            payload_template = """{
  "event": "{{ event }}",
  "model": "{{ model }}",
  "record": {
    "id": {{ record_id }},
    {% for key, value in record.items() %}
    "{{ key }}": {{ value | tojson }}{% if not loop.last %},{% endif %}
    {% endfor %}
  },
  "timestamp": "{{ timestamp }}"
}"""

        # Minimal template
        elif template_type == 'minimal':
            payload_template = """{
  "event": "{{ event }}",
  "model": "{{ model }}",
  "id": {{ record_id }},
  "timestamp": "{{ timestamp }}"
}"""

        else:
            payload_template = "{}"

        # Create template
        template = self.create({
            'name': f"{model.name} - {template_type.title()} Template",
            'code': f"{model.model.replace('.', '_')}_{template_type}",
            'model_id': model.id,
            'payload_template': payload_template,
        })

        return template
