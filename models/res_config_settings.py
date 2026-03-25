from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    subscription_grace_days = fields.Integer(
        string='Grace Period (Days)',
        config_parameter='subscription.grace_days',
        default=5,
        help='Number of days after the due date before a subscription is paused.',
    )
    subscription_send_reminders = fields.Boolean(
        string='Send Payment Reminders',
        config_parameter='subscription.send_reminders',
        default=True,
        help='Enable automatic payment reminder emails before the due date.',
    )
    subscription_reminder_days = fields.Integer(
        string='Days Before Due',
        config_parameter='subscription.reminder_days',
        default=3,
        help='Number of days before the due date to send a payment reminder email.',
    )
