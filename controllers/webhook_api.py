# -*- coding: utf-8 -*-
"""
Webhook Pull API Controller

RESTful API endpoints for BridgeCore to pull webhook events
from the update.webhook table.

Security:
- Authentication required (API key or session)
- Rate limiting recommended
- CORS support for external access
"""

from odoo import http
from odoo.http import request, Response
import json
import logging
from datetime import datetime

_logger = logging.getLogger(__name__)


class WebhookPullAPI(http.Controller):
    """
    Pull-based Webhook API Controller

    Provides endpoints for external systems (like BridgeCore) to pull
    webhook events instead of receiving push notifications.
    """

    def _authenticate_api_key(self, api_key):
        """
        Authenticate using API key

        Args:
            api_key: API key from request header

        Returns:
            Boolean indicating if authentication is successful
        """
        # TODO: Implement proper API key authentication
        # For now, check against system parameter or config setting
        try:
            valid_api_key = request.env['ir.config_parameter'].sudo().get_param(
                'webhook.api_key', default=False
            )

            if not valid_api_key:
                _logger.warning("No API key configured in system parameters")
                return False

            return api_key == valid_api_key

        except Exception as e:
            _logger.error(f"API key authentication failed: {e}")
            return False

    def _get_auth_user(self):
        """
        Get authenticated user from session or API key

        Returns:
            User record or False
        """
        # Check for API key in header
        api_key = request.httprequest.headers.get('X-API-Key')

        if api_key:
            if self._authenticate_api_key(api_key):
                # Return admin user for API key authentication
                return request.env.ref('base.user_admin')
            else:
                return False

        # Check for session authentication
        if request.session.uid:
            return request.env['res.users'].sudo().browse(request.session.uid)

        return False

    def _make_response(self, data, status=200):
        """
        Create JSON response

        Args:
            data: Data to serialize
            status: HTTP status code

        Returns:
            HTTP Response
        """
        return Response(
            json.dumps(data, indent=2, default=str),
            status=status,
            mimetype='application/json',
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
            }
        )

    def _error_response(self, message, status=400):
        """
        Create error response

        Args:
            message: Error message
            status: HTTP status code

        Returns:
            HTTP Response
        """
        return self._make_response({
            'error': True,
            'message': message,
            'timestamp': datetime.now().isoformat(),
        }, status=status)

    @http.route('/api/webhooks/pull', type='http', auth='public', methods=['GET', 'POST'], csrf=False, cors='*')
    def pull_events(self, **kwargs):
        """
        Pull webhook events from update.webhook table

        Query Parameters (GET) or JSON Body (POST):
            last_event_id (int): Last event ID that was pulled (default: 0)
            limit (int): Maximum number of events to return (default: 100, max: 1000)
            models (list): List of model names to filter (optional)
            priority (str): Priority filter (high/medium/low) (optional)

        Returns:
            JSON response with events data:
            {
                "success": true,
                "events": [...],
                "last_id": 550,
                "has_more": true,
                "count": 100,
                "timestamp": "2025-11-16T22:30:00"
            }

        Example:
            GET /api/webhooks/pull?last_event_id=100&limit=50&models=sale.order,purchase.order
            POST /api/webhooks/pull
            {
                "last_event_id": 100,
                "limit": 50,
                "models": ["sale.order", "purchase.order"],
                "priority": "high"
            }
        """
        try:
            # Authenticate
            user = self._get_auth_user()
            if not user:
                return self._error_response("Authentication required", status=401)

            # Get parameters from GET or POST
            if request.httprequest.method == 'POST':
                try:
                    params = json.loads(request.httprequest.data.decode('utf-8'))
                except Exception as e:
                    return self._error_response(f"Invalid JSON body: {str(e)}", status=400)
            else:
                params = kwargs

            # Extract and validate parameters
            last_event_id = int(params.get('last_event_id', 0))
            limit = min(int(params.get('limit', 100)), 1000)  # Max 1000
            models = params.get('models')
            priority = params.get('priority')

            # Convert models string to list if needed
            if isinstance(models, str):
                models = [m.strip() for m in models.split(',') if m.strip()]

            _logger.info(f"Pull request: last_id={last_event_id}, limit={limit}, models={models}, priority={priority}")

            # Pull events using model method
            result = request.env['update.webhook'].sudo().pull_events(
                last_event_id=last_event_id,
                limit=limit,
                models=models,
                priority=priority
            )

            # Add success flag and timestamp
            result['success'] = True
            result['timestamp'] = datetime.now().isoformat()

            return self._make_response(result)

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}", status=400)
        except Exception as e:
            _logger.error(f"Pull events failed: {e}", exc_info=True)
            return self._error_response(f"Internal server error: {str(e)}", status=500)

    @http.route('/api/webhooks/mark-processed', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def mark_processed(self, **kwargs):
        """
        Mark events as processed

        JSON Body:
            event_ids (list): List of event IDs to mark as processed

        Returns:
            JSON response:
            {
                "success": true,
                "processed_count": 10,
                "message": "Events marked as processed"
            }

        Example:
            POST /api/webhooks/mark-processed
            {
                "event_ids": [101, 102, 103, 104, 105]
            }
        """
        try:
            # Authenticate
            user = self._get_auth_user()
            if not user:
                return self._error_response("Authentication required", status=401)

            # Get request body
            try:
                data = json.loads(request.httprequest.data.decode('utf-8'))
            except Exception as e:
                return self._error_response(f"Invalid JSON body: {str(e)}", status=400)

            # Get event IDs
            event_ids = data.get('event_ids', [])

            if not event_ids or not isinstance(event_ids, list):
                return self._error_response("event_ids must be a non-empty list", status=400)

            _logger.info(f"Marking {len(event_ids)} events as processed")

            # Mark as processed
            success = request.env['update.webhook'].sudo().mark_batch_as_processed(event_ids)

            if success:
                return self._make_response({
                    'success': True,
                    'processed_count': len(event_ids),
                    'message': f'{len(event_ids)} event(s) marked as processed',
                    'timestamp': datetime.now().isoformat(),
                })
            else:
                return self._error_response("Failed to mark events as processed", status=500)

        except Exception as e:
            _logger.error(f"Mark processed failed: {e}", exc_info=True)
            return self._error_response(f"Internal server error: {str(e)}", status=500)

    @http.route('/api/webhooks/stats', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_statistics(self, **kwargs):
        """
        Get webhook statistics

        Query Parameters:
            days (int): Number of days to look back (default: 7)

        Returns:
            JSON response with statistics:
            {
                "success": true,
                "stats": {
                    "period_days": 7,
                    "total": 1500,
                    "processed": 1200,
                    "pending": 300,
                    "archived": 100,
                    "by_model": [...],
                    "by_priority": {...}
                }
            }

        Example:
            GET /api/webhooks/stats?days=30
        """
        try:
            # Authenticate
            user = self._get_auth_user()
            if not user:
                return self._error_response("Authentication required", status=401)

            # Get days parameter
            days = int(kwargs.get('days', 7))

            _logger.info(f"Getting statistics for last {days} days")

            # Get statistics
            stats = request.env['update.webhook'].sudo().get_statistics(days=days)

            return self._make_response({
                'success': True,
                'stats': stats,
                'timestamp': datetime.now().isoformat(),
            })

        except ValueError as e:
            return self._error_response(f"Invalid parameter: {str(e)}", status=400)
        except Exception as e:
            _logger.error(f"Get statistics failed: {e}", exc_info=True)
            return self._error_response(f"Internal server error: {str(e)}", status=500)

    @http.route('/api/webhooks/health', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def health_check(self, **kwargs):
        """
        Health check endpoint

        Returns:
            JSON response:
            {
                "status": "healthy",
                "version": "2.0.0",
                "timestamp": "2025-11-16T22:30:00"
            }
        """
        try:
            # Get pending events count
            pending_count = request.env['update.webhook'].sudo().search_count([
                ('is_processed', '=', False),
                ('is_archived', '=', False),
            ])

            return self._make_response({
                'status': 'healthy',
                'version': '2.0.0',
                'module': 'auto_webhook',
                'pending_events': pending_count,
                'timestamp': datetime.now().isoformat(),
            })

        except Exception as e:
            _logger.error(f"Health check failed: {e}", exc_info=True)
            return self._error_response(f"Unhealthy: {str(e)}", status=503)

    @http.route('/api/webhooks/options', type='http', auth='public', methods=['OPTIONS'], csrf=False, cors='*')
    def options_handler(self, **kwargs):
        """
        Handle CORS preflight requests
        """
        return Response(
            status=200,
            headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Content-Type, X-API-Key',
                'Access-Control-Max-Age': '86400',
            }
        )
