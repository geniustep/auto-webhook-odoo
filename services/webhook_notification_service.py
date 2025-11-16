# -*- coding: utf-8 -*-
from odoo import models, api, _
import logging

_logger = logging.getLogger(__name__)


class WebhookNotificationService(models.AbstractModel):
    """Notification Service for Webhook Events"""

    _name = 'webhook.notification.service'
    _description = 'Webhook Notification Service'

    @api.model
    def notify_event_failed(self, event):
        """
        Send notification when an event fails

        Args:
            event: webhook.event record
        """
        try:
            # Get admin users
            admin_group = self.env.ref('base.group_system')
            admin_users = admin_group.users

            if not admin_users:
                _logger.warning("No admin users found for notification")
                return

            # Prepare notification message
            subject = _("Webhook Event Failed: %s") % event.display_name
            body = _("""
                <p>A webhook event has failed:</p>
                <ul>
                    <li><strong>Model:</strong> %s</li>
                    <li><strong>Record ID:</strong> %s</li>
                    <li><strong>Event:</strong> %s</li>
                    <li><strong>Error:</strong> %s</li>
                    <li><strong>Retry Count:</strong> %s / %s</li>
                </ul>
                <p>Please check the webhook events dashboard for more details.</p>
            """) % (
                event.model,
                event.record_id,
                event.event,
                event.error_message or 'Unknown error',
                event.retry_count,
                event.max_retries
            )

            # Send message to admin users
            for user in admin_users:
                self.env['mail.message'].create({
                    'subject': subject,
                    'body': body,
                    'message_type': 'notification',
                    'model': 'res.users',
                    'res_id': user.id,
                    'author_id': self.env.user.partner_id.id,
                })

            _logger.info(f"Sent failure notification for event {event.id} to {len(admin_users)} admins")

        except Exception as e:
            _logger.error(f"Failed to send event failure notification: {e}")

    @api.model
    def notify_dead_letter(self, event):
        """
        Send notification when an event is moved to dead letter queue

        Args:
            event: webhook.event record
        """
        try:
            # Get admin users
            admin_group = self.env.ref('base.group_system')
            admin_users = admin_group.users

            if not admin_users:
                _logger.warning("No admin users found for notification")
                return

            # Prepare notification message
            subject = _("Webhook Event Moved to Dead Letter: %s") % event.display_name
            body = _("""
                <p><strong>⚠️ A webhook event has been moved to the dead letter queue after exhausting all retries:</strong></p>
                <ul>
                    <li><strong>Model:</strong> %s</li>
                    <li><strong>Record ID:</strong> %s</li>
                    <li><strong>Event:</strong> %s</li>
                    <li><strong>Priority:</strong> %s</li>
                    <li><strong>Last Error:</strong> %s</li>
                    <li><strong>Total Retries:</strong> %s</li>
                </ul>
                <p>This event requires manual intervention. Please review the dead letter queue.</p>
            """) % (
                event.model,
                event.record_id,
                event.event,
                event.priority,
                event.error_message or 'Unknown error',
                event.retry_count
            )

            # Send message to admin users
            for user in admin_users:
                self.env['mail.message'].create({
                    'subject': subject,
                    'body': body,
                    'message_type': 'notification',
                    'model': 'res.users',
                    'res_id': user.id,
                    'author_id': self.env.user.partner_id.id,
                })

            # Also try to send email for high priority events
            if event.priority == 'high':
                self._send_email_notification(admin_users, subject, body)

            _logger.info(f"Sent dead letter notification for event {event.id}")

        except Exception as e:
            _logger.error(f"Failed to send dead letter notification: {e}")

    @api.model
    def notify_subscriber_failure(self, subscriber, error_count):
        """
        Send notification when a subscriber has multiple failures

        Args:
            subscriber: webhook.subscriber record
            error_count: Number of consecutive failures
        """
        try:
            # Only notify if significant number of failures
            if error_count < 5:
                return

            # Get admin users
            admin_group = self.env.ref('base.group_system')
            admin_users = admin_group.users

            if not admin_users:
                return

            # Prepare notification message
            subject = _("Webhook Subscriber Having Issues: %s") % subscriber.name
            body = _("""
                <p><strong>⚠️ A webhook subscriber is experiencing multiple failures:</strong></p>
                <ul>
                    <li><strong>Subscriber:</strong> %s</li>
                    <li><strong>Endpoint:</strong> %s</li>
                    <li><strong>Consecutive Failures:</strong> %s</li>
                    <li><strong>Success Rate:</strong> %.2f%%</li>
                    <li><strong>Last Failure:</strong> %s</li>
                </ul>
                <p>Please check the subscriber configuration and endpoint availability.</p>
            """) % (
                subscriber.name,
                subscriber.endpoint_url,
                error_count,
                subscriber.success_rate,
                subscriber.last_failure_at.strftime('%Y-%m-%d %H:%M:%S') if subscriber.last_failure_at else 'N/A'
            )

            # Send message to admin users
            for user in admin_users:
                self.env['mail.message'].create({
                    'subject': subject,
                    'body': body,
                    'message_type': 'notification',
                    'model': 'res.users',
                    'res_id': user.id,
                    'author_id': self.env.user.partner_id.id,
                })

            _logger.info(f"Sent subscriber failure notification for {subscriber.name}")

        except Exception as e:
            _logger.error(f"Failed to send subscriber failure notification: {e}")

    def _send_email_notification(self, users, subject, body):
        """
        Send email notification to users

        Args:
            users: recordset of res.users
            subject: Email subject
            body: Email body (HTML)
        """
        try:
            # Get email template
            template = self.env.ref('auto_webhook_odoo.webhook_notification_email', raise_if_not_found=False)

            if not template:
                # Create simple email without template
                for user in users:
                    if user.email:
                        mail = self.env['mail.mail'].create({
                            'subject': subject,
                            'body_html': body,
                            'email_to': user.email,
                        })
                        mail.send()
            else:
                # Use template
                for user in users:
                    if user.email:
                        template.send_mail(user.id, force_send=True)

            _logger.info(f"Sent email notifications to {len(users)} users")

        except Exception as e:
            _logger.error(f"Failed to send email notifications: {e}")
