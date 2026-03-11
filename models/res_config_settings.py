from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    subscription_default_grace_days = fields.Integer(
        string='Default Grace Days',
        config_parameter='subscription_management.default_grace_days',
        default=7,
        help='Default number of days after invoice due date before pausing '
             'the subscription and applying a penalty. '
             'Can be overridden per subscription line.',
    )
    subscription_default_penalty_amount = fields.Float(
        string='Default Penalty Amount',
        config_parameter='subscription_management.default_penalty_amount',
        default=0.0,
        help='Default penalty amount when a subscription is paused due to '
             'non-payment. Can be overridden per subscription line.',
    )
    subscription_default_reminder_days_before = fields.Integer(
        string='Default Reminder Days Before Due',
        config_parameter='subscription_management.default_reminder_days_before',
        default=3,
        help='Send a payment reminder this many days before the invoice '
             'due date. Can be overridden per subscription line.',
    )
