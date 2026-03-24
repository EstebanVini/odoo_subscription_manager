from odoo import fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    subscription_id = fields.Many2one(
        comodel_name='subscription.subscription',
        string='Subscription',
        index=True,
        ondelete='set null',
    )
