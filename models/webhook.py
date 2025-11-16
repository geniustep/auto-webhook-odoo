# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)


class WebhookMixin(models.AbstractModel):
    """Enhanced Webhook Mixin for Comprehensive Event Tracking"""

    _name = 'webhook.mixin'
    _description = 'Webhook Mixin for tracking model changes'

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to track webhook events"""
        # Call super first to create records
        records = super(WebhookMixin, self).create(vals_list)

        # Track webhook events
        try:
            # Check if webhook.config model exists and is accessible
            if 'webhook.config' not in self.env:
                return records
                
            # Get webhook configuration for this model
            config = self.env['webhook.config'].sudo().get_config_for_model(self._name)

            if config and config.enabled and 'create' in config.events:
                # Check if batch processing is enabled
                if config.batch_enabled:
                    self._schedule_batch_event(records, 'create', config)
                else:
                    # Process individual events
                    for record in records:
                        try:
                            # Get corresponding vals for this record
                            idx = records._ids.index(record.id) if hasattr(records, '_ids') else 0
                            vals = vals_list[idx] if idx < len(vals_list) else vals_list[0]

                            self._create_webhook_event(record, 'create', config, vals=vals)
                        except Exception as e:
                            # Log error for this specific record but continue
                            _logger.error(f"Failed to create webhook event for {record._name}:{record.id}: {e}")

        except Exception as e:
            # Log error but don't block the operation
            _logger.error(f"Failed to create webhook event for {self._name}: {e}", exc_info=True)

        return records

    def write(self, vals):
        """Override write to track webhook events"""
        # Store old values before write - use safe read
        old_values = {}
        if vals:
            for record in self:
                try:
                    # Use read with specific fields to avoid transaction issues
                    # Only read fields that are being changed
                    fields_to_read = [f for f in vals.keys() if f in record._fields]
                    if fields_to_read:
                        read_result = record.read(fields_to_read)
                        old_values[record.id] = read_result[0] if read_result else {}
                    else:
                        old_values[record.id] = {}
                except Exception as e:
                    # If transaction is already failed, skip reading
                    error_msg = str(e)
                    if 'transaction' in error_msg.lower() or 'aborted' in error_msg.lower() or 'InFailedSqlTransaction' in error_msg:
                        _logger.warning(f"Transaction error reading old values for {record._name}:{record.id}: {error_msg}")
                        old_values[record.id] = {}
                    else:
                        _logger.warning(f"Could not read old values for {record._name}:{record.id}: {e}")
                        old_values[record.id] = {}

        # Call super to perform write first
        result = super(WebhookMixin, self).write(vals)

        # Track webhook events after successful write
        try:
            # Check if webhook.config model exists and is accessible
            if 'webhook.config' not in self.env:
                return result
                
            # Get webhook configuration for this model
            config = self.env['webhook.config'].sudo().get_config_for_model(self._name)

            if config and config.enabled and 'write' in config.events:
                changed_fields = set(vals.keys())

                for record in self:
                    try:
                        # Check if should track this event
                        if config.should_track_event(record, 'write', changed_fields):
                            old_data = old_values.get(record.id, {})

                            self._create_webhook_event(
                                record,
                                'write',
                                config,
                                vals=vals,
                                old_data=old_data,
                                changed_fields=list(changed_fields)
                            )
                    except Exception as e:
                        # Log error for this specific record but continue
                        _logger.error(f"Failed to create webhook event for {record._name}:{record.id}: {e}")

        except Exception as e:
            # Log error but don't block the operation
            _logger.error(f"Failed to create webhook event for {self._name}: {e}", exc_info=True)

        return result

    def unlink(self):
        """Override unlink to track webhook events"""
        # Store record data before deletion
        records_data = []
        for record in self:
            try:
                records_data.append({
                    'id': record.id,
                    'data': record.read()[0]
                })
            except Exception as e:
                _logger.warning(f"Could not read data for {record._name}:{record.id}: {e}")
                records_data.append({'id': record.id, 'data': {}})

        # Get webhook configuration before deleting
        try:
            # Check if webhook.config model exists and is accessible
            if 'webhook.config' in self.env:
                config = self.env['webhook.config'].sudo().get_config_for_model(self._name)

                if config and config.enabled and 'unlink' in config.events:
                    for record_data in records_data:
                        try:
                            # Create a temporary record-like object for checking
                            record = self.browse(record_data['id'])

                            if config.should_track_event(record, 'unlink', None):
                                # Create webhook event before deletion
                                self._create_webhook_event_for_deleted(
                                    record_data['id'],
                                    config,
                                    record_data['data']
                                )
                        except Exception as e:
                            # Log error for this specific record but continue
                            _logger.error(f"Failed to create webhook event for {self._name}:{record_data['id']}: {e}")

        except Exception as e:
            # Log error but don't block the operation
            _logger.error(f"Failed to create webhook event for {self._name}: {e}", exc_info=True)

        # Call super to perform deletion
        return super(WebhookMixin, self).unlink()

    def _create_webhook_event(self, record, event_type, config, vals=None, old_data=None, changed_fields=None):
        """
        Create webhook event with all metadata

        Args:
            record: Record that triggered the event
            event_type: Type of event (create/write/unlink)
            config: webhook.config record
            vals: Dictionary of new values
            old_data: Dictionary of old values (for write events)
            changed_fields: List of changed field names
        """
        try:
            # Build comprehensive payload
            payload = self._build_event_payload(record, event_type, vals, old_data, changed_fields)

            # Prepare event values
            event_vals = {
                'model': self._name,
                'record_id': record.id,
                'event': event_type,
                'priority': config.priority,
                'category': config.category,
                'config_id': config.id,
                'payload': payload,
                'status': 'pending',
            }

            # Add changed fields for write events
            if event_type == 'write' and changed_fields:
                event_vals['changed_fields'] = changed_fields

            # Add template if configured
            if config.template_id:
                event_vals['template_id'] = config.template_id.id

            # Add subscribers (use first subscriber if multiple)
            subscribers = config.get_event_subscribers()
            if subscribers:
                event_vals['subscriber_id'] = subscribers[0].id

            # Create the event
            self.env['webhook.event'].sudo().create(event_vals)

            _logger.debug(f"Created webhook event for {self._name}:{record.id} - {event_type}")

        except Exception as e:
            _logger.error(f"Failed to create webhook event: {e}")
            # Don't raise - we don't want to block the main operation

    def _create_webhook_event_for_deleted(self, record_id, config, record_data):
        """
        Create webhook event for deleted record

        Args:
            record_id: ID of deleted record
            config: webhook.config record
            record_data: Data of the deleted record
        """
        try:
            # Build payload for deleted record
            payload = {
                'deleted_record': record_data,
                'timestamp': fields.Datetime.now().isoformat(),
            }

            # Prepare event values
            event_vals = {
                'model': self._name,
                'record_id': record_id,
                'event': 'unlink',
                'priority': config.priority,
                'category': config.category,
                'config_id': config.id,
                'payload': payload,
                'status': 'pending',
            }

            # Add template if configured
            if config.template_id:
                event_vals['template_id'] = config.template_id.id

            # Add subscribers
            subscribers = config.get_event_subscribers()
            if subscribers:
                event_vals['subscriber_id'] = subscribers[0].id

            # Create the event
            self.env['webhook.event'].sudo().create(event_vals)

        except Exception as e:
            _logger.error(f"Failed to create webhook event for deleted record: {e}")

    def _build_event_payload(self, record, event_type, vals=None, old_data=None, changed_fields=None):
        """
        Build comprehensive event payload

        Args:
            record: Record that triggered the event
            event_type: Type of event
            vals: New values
            old_data: Old values (for write events)
            changed_fields: Changed field names

        Returns:
            Dictionary containing event payload
        """
        payload = {
            'event_type': event_type,
            'timestamp': fields.Datetime.now().isoformat(),
            'model': self._name,
            'record_id': record.id,
        }

        try:
            # Add record display name
            if record.exists():
                payload['record_name'] = record.display_name

            # For create events
            if event_type == 'create':
                payload['new_data'] = vals or {}

            # For write events
            elif event_type == 'write':
                payload['changed_fields'] = changed_fields or []
                payload['new_data'] = vals or {}

                # Add old values for changed fields only
                if old_data and changed_fields:
                    payload['old_data'] = {
                        field: old_data.get(field)
                        for field in changed_fields
                        if field in old_data
                    }

            # For unlink events - payload built separately

        except Exception as e:
            _logger.warning(f"Error building payload: {e}")

        return payload

    def _schedule_batch_event(self, records, event_type, config):
        """
        Schedule events for batch processing

        Args:
            records: Records that triggered the events
            event_type: Type of event
            config: webhook.config record
        """
        try:
            # For now, create individual events but mark them for batching
            # In a production system, you would implement a proper batch queue

            for record in records:
                # Create event marked for batch processing
                event_vals = {
                    'model': self._name,
                    'record_id': record.id,
                    'event': event_type,
                    'priority': config.priority,
                    'category': config.category,
                    'config_id': config.id,
                    'status': 'pending',
                    'payload': {
                        'batch': True,
                        'batch_size': config.batch_size,
                        'batch_timeout': config.batch_timeout,
                    }
                }

                if config.template_id:
                    event_vals['template_id'] = config.template_id.id

                subscribers = config.get_event_subscribers()
                if subscribers:
                    event_vals['subscriber_id'] = subscribers[0].id

                self.env['webhook.event'].sudo().create(event_vals)

            _logger.info(f"Scheduled {len(records)} events for batch processing")

        except Exception as e:
            _logger.error(f"Failed to schedule batch events: {e}")
