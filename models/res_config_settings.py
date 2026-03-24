from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    subscription_grace_days = fields.Integer(
        string='Grace Period (Days)',
        config_parameter='subscription.grace_days',
        default=5,
        help='Number of days after the due date before a subscription is paused.',
    )
    subscription_penalty_amount = fields.Float(
        string='Penalty Amount',
        config_parameter='subscription.penalty_amount',
        default=0.0,
        help='Fixed amount invoiced as a penalty when a subscription is paused for non-payment.',
    )
    subscription_reminder_days = fields.Integer(
        string='Send Reminder (Days Before Due)',
        config_parameter='subscription.reminder_days',
        default=3,
        help='Number of days before the due date to send a payment reminder email.',
    )
