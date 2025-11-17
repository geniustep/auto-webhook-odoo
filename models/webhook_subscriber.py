# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging
import requests
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)


class WebhookSubscriber(models.Model):
    """Webhook Subscriber - Endpoint Management"""

    _name = 'webhook.subscriber'
    _description = 'Webhook Subscriber'
    _order = 'name'

    # Basic Information
    name = fields.Char(
        string='Subscriber Name',
        required=True,
        help='Name of the subscriber endpoint'
    )
    endpoint_url = fields.Char(
        string='Endpoint URL',
        required=True,
        help='BridgeCore or other webhook endpoint URL'
    )

    # Authentication
    auth_type = fields.Selection(
        selection=[
            ('none', 'None'),
            ('basic', 'Basic Auth'),
            ('bearer', 'Bearer Token'),
            ('api_key', 'API Key')
        ],
        string='Authentication Type',
        default='none',
        required=True,
        help='Type of authentication to use'
    )
    auth_token = fields.Char(
        string='Auth Token',
        help='Bearer token or Basic auth credentials'
    )
    api_key = fields.Char(
        string='API Key',
        help='API key for authentication'
    )
    api_key_header = fields.Char(
        string='API Key Header',
        default='X-API-Key',
        help='Header name for API key authentication'
    )

    # Connection Settings
    enabled = fields.Boolean(
        string='Enabled',
        default=True,
        help='Enable or disable this subscriber'
    )
    active = fields.Boolean(
        string='Active',
        default=True,
        help='Archive/Unarchive this subscriber'
    )
    timeout = fields.Integer(
        string='Timeout (seconds)',
        default=30,
        help='Request timeout in seconds'
    )
    verify_ssl = fields.Boolean(
        string='Verify SSL',
        default=True,
        help='Verify SSL certificates'
    )

    # Rate Limiting
    rate_limit = fields.Integer(
        string='Rate Limit (req/min)',
        default=0,
        help='Maximum requests per minute (0 = unlimited)'
    )
    rate_limit_window = fields.Integer(
        string='Rate Limit Window (seconds)',
        default=60,
        help='Time window for rate limiting'
    )

    # Retry Settings
    retry_enabled = fields.Boolean(
        string='Retry Enabled',
        default=True,
        help='Enable automatic retry on failure'
    )
    max_retries = fields.Integer(
        string='Max Retries',
        default=5,
        help='Maximum number of retry attempts'
    )

    # Statistics
    last_success_at = fields.Datetime(
        string='Last Success',
        readonly=True,
        help='Timestamp of last successful delivery'
    )
    last_failure_at = fields.Datetime(
        string='Last Failure',
        readonly=True,
        help='Timestamp of last failed delivery'
    )
    total_sent = fields.Integer(
        string='Total Sent',
        compute='_compute_statistics',
        help='Total number of events sent'
    )
    total_failed = fields.Integer(
        string='Total Failed',
        compute='_compute_statistics',
        help='Total number of failed events'
    )
    success_rate = fields.Float(
        string='Success Rate (%)',
        compute='_compute_statistics',
        help='Success rate percentage'
    )

    # Additional Settings
    custom_headers = fields.Text(
        string='Custom Headers',
        help='Additional HTTP headers (JSON format)'
    )
    notes = fields.Text(
        string='Notes',
        help='Additional notes about this subscriber'
    )

    # SQL Constraints
    _sql_constraints = [
        ('unique_endpoint',
         'UNIQUE(endpoint_url)',
         'A subscriber with this endpoint URL already exists!'),
        ('check_timeout',
         'CHECK(timeout > 0)',
         'Timeout must be greater than 0'),
        ('check_rate_limit',
         'CHECK(rate_limit >= 0)',
         'Rate limit must be 0 or positive'),
    ]

    @api.depends('endpoint_url')
    def _compute_statistics(self):
        """Compute statistics for this subscriber"""
        for record in self:
            events = self.env['webhook.event'].search([
                ('subscriber_id', '=', record.id)
            ])

            total = len(events)
            sent = len(events.filtered(lambda e: e.status == 'sent'))
            failed = len(events.filtered(lambda e: e.status in ['failed', 'dead']))

            record.total_sent = sent
            record.total_failed = failed
            record.success_rate = (sent / total * 100) if total > 0 else 0.0

    def send_event(self, event_id):
        """
        Send a single webhook event

        Args:
            event_id: ID of webhook.event record

        Returns:
            Dictionary with status and response
        """
        self.ensure_one()

        event = self.env['webhook.event'].browse(event_id)
        if not event.exists():
            raise ValidationError(_("Event not found"))

        # Check rate limit
        if not self.check_rate_limit():
            return {
                'success': False,
                'status_code': 429,
                'body': {'error': 'Rate limit exceeded'},
            }

        # Build payload
        payload = event._build_payload()

        # Send request
        return self.send_event_data(payload)

    def send_event_data(self, payload):
        """
        Send event data to endpoint

        Args:
            payload: Dictionary containing event data

        Returns:
            Dictionary with status_code and body
        """
        self.ensure_one()

        if not self.enabled:
            raise ValidationError(_("Subscriber is disabled"))

        try:
            # Prepare headers
            headers = {
                'Content-Type': 'application/json',
                'User-Agent': 'Odoo-Webhook/1.0',
            }

            # Add authentication
            if self.auth_type == 'bearer' and self.auth_token:
                headers['Authorization'] = f'Bearer {self.auth_token}'
            elif self.auth_type == 'api_key' and self.api_key:
                headers[self.api_key_header] = self.api_key
            elif self.auth_type == 'basic' and self.auth_token:
                headers['Authorization'] = f'Basic {self.auth_token}'

            # Add custom headers
            if self.custom_headers:
                try:
                    custom = json.loads(self.custom_headers)
                    headers.update(custom)
                except Exception as e:
                    _logger.error(f"Invalid custom headers JSON: {e}")

            # Send request
            response = requests.post(
                self.endpoint_url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl
            )

            # Update last success
            if response.status_code < 400:
                self.sudo().write({'last_success_at': fields.Datetime.now()})
            else:
                self.sudo().write({'last_failure_at': fields.Datetime.now()})

            return {
                'success': response.status_code < 400,
                'status_code': response.status_code,
                'body': response.json() if response.content else {},
            }

        except requests.exceptions.Timeout:
            _logger.error(f"Timeout sending to {self.endpoint_url}")
            self.sudo().write({'last_failure_at': fields.Datetime.now()})

            return {
                'success': False,
                'status_code': 408,
                'body': {'error': 'Request timeout'},
            }

        except requests.exceptions.ConnectionError as e:
            _logger.error(f"Connection error sending to {self.endpoint_url}: {e}")
            self.sudo().write({'last_failure_at': fields.Datetime.now()})

            return {
                'success': False,
                'status_code': 503,
                'body': {'error': 'Connection error'},
            }

        except Exception as e:
            _logger.error(f"Error sending to {self.endpoint_url}: {e}")
            self.sudo().write({'last_failure_at': fields.Datetime.now()})

            return {
                'success': False,
                'status_code': 500,
                'body': {'error': str(e)},
            }

    def send_batch(self, event_ids):
        """
        Send multiple events in a batch

        Args:
            event_ids: List of webhook.event IDs

        Returns:
            Dictionary with results
        """
        self.ensure_one()

        events = self.env['webhook.event'].browse(event_ids)
        if not events:
            return {'success': False, 'message': 'No events provided'}

        # Build batch payload
        batch_payload = {
            'batch': True,
            'timestamp': fields.Datetime.now().isoformat(),
            'events': [event._build_payload() for event in events]
        }

        # Send batch
        result = self.send_event_data(batch_payload)

        return result

    def test_connection(self):
        """
        Test connection to endpoint

        Returns:
            Dictionary with status and message
        """
        self.ensure_one()

        # First, try a simple HEAD or GET request to check if endpoint exists
        try:
            # Try HEAD request first (lighter)
            response = requests.head(
                self.endpoint_url,
                timeout=5,
                verify=self.verify_ssl,
                allow_redirects=True
            )
            # If HEAD works, endpoint exists
            if response.status_code < 500:
                endpoint_exists = True
            else:
                endpoint_exists = False
        except:
            endpoint_exists = False

        test_payload = {
            'test': True,
            'message': 'Connection test from Odoo Webhook Module',
            'timestamp': fields.Datetime.now().isoformat(),
            'subscriber': self.name,
        }

        try:
            result = self.send_event_data(test_payload)

            if result['success']:
                return {
                    'status': 'success',
                    'message': _('Connection test successful (Status: %s)') % result['status_code'],
                    'response_code': result['status_code'],
                }
            else:
                error_msg = result['body'].get('error') or result['body'].get('detail') or 'Unknown error'
                status_code = result.get('status_code', 'N/A')
                
                # More detailed error message
                if status_code == 404:
                    error_msg = _('Endpoint not found (404). The URL may be incorrect or BridgeCore may use Pull-based webhooks only. Please verify the endpoint URL with BridgeCore documentation.')
                elif status_code == 401:
                    error_msg = _('Authentication failed (401). Please check your auth token in the subscriber settings.')
                elif status_code == 403:
                    error_msg = _('Access forbidden (403). Please check your authentication token and permissions.')
                elif status_code == 405:
                    error_msg = _('Method not allowed (405). This endpoint may not support POST requests.')
                elif status_code == 503:
                    error_msg = _('Service unavailable (503). The endpoint may be down or unreachable.')
                elif status_code == 408:
                    error_msg = _('Request timeout (408). The server took too long to respond. Try increasing the timeout value.')
                else:
                    # Include response body if available
                    body_detail = result['body'].get('detail') or result['body'].get('error') or ''
                    if body_detail:
                        error_msg = f"{error_msg} ({body_detail})"
                
                return {
                    'status': 'error',
                    'message': _('Connection test failed (Status: %s) - %s') % (status_code, error_msg),
                    'response_code': status_code,
                    'error': error_msg,
                }

        except Exception as e:
            return {
                'status': 'error',
                'message': str(e),
            }

    def check_rate_limit(self):
        """
        Check if rate limit is exceeded

        Returns:
            Boolean indicating if request is allowed
        """
        self.ensure_one()

        # No rate limit
        if self.rate_limit == 0:
            return True

        # Count recent requests
        cutoff_time = fields.Datetime.now() - timedelta(seconds=self.rate_limit_window)

        recent_events = self.env['webhook.event'].search_count([
            ('subscriber_id', '=', self.id),
            ('sent_at', '>=', cutoff_time),
            ('status', '=', 'sent')
        ])

        return recent_events < self.rate_limit

    def action_test_connection(self):
        """UI action to test connection"""
        self.ensure_one()

        result = self.test_connection()

        notification_type = 'success' if result['status'] == 'success' else 'danger'

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Connection Test'),
                'message': result['message'],
                'type': notification_type,
            }
        }

    def action_view_events(self):
        """View events for this subscriber"""
        self.ensure_one()

        return {
            'name': _('Webhook Events'),
            'type': 'ir.actions.act_window',
            'res_model': 'webhook.event',
            'view_mode': 'tree,form',
            'domain': [('subscriber_id', '=', self.id)],
            'context': {'default_subscriber_id': self.id},
        }

    @api.constrains('endpoint_url')
    def _check_endpoint_url(self):
        """Validate endpoint URL"""
        for record in self:
            if record.endpoint_url:
                if not record.endpoint_url.startswith(('http://', 'https://')):
                    raise ValidationError(
                        _("Endpoint URL must start with http:// or https://")
                    )

    @api.constrains('custom_headers')
    def _check_custom_headers(self):
        """Validate custom headers JSON"""
        for record in self:
            if record.custom_headers:
                try:
                    json.loads(record.custom_headers)
                except Exception as e:
                    raise ValidationError(
                        _("Invalid custom headers JSON: %s") % str(e)
                    )

    @api.onchange('auth_type')
    def _onchange_auth_type(self):
        """Clear auth fields when type changes"""
        if self.auth_type == 'none':
            self.auth_token = False
            self.api_key = False
