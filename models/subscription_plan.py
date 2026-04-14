from odoo import fields, models


class SubscriptionPlan(models.Model):
    _name = 'subscription.plan'
    _description = 'Subscription Plan'
    _order = 'name'

    name = fields.Char(string='Plan Name', required=True)
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Product',
        domain="[('type', 'in', ['service', 'consu'])]",
        help='Product used in invoices for this plan',
    )
    recurring_interval = fields.Integer(
        string='Billing Period',
        default=1,
        required=True,
        help='Number of intervals between invoices',
    )
    recurring_rule_type = fields.Selection(
        selection=[
            ('daily', 'Day(s)'),
            ('weekly', 'Week(s)'),
            ('monthly', 'Month(s)'),
            ('yearly', 'Year(s)'),
        ],
        string='Billing Frequency',
        default='monthly',
        required=True,
    )
    price = fields.Monetary(
        string='Price',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )
    penalty_product_id = fields.Many2one(
        comodel_name='product.product',
        string='Penalty Product',
        domain="[('type', 'in', ['service', 'consu'])]",
        help='Product added as a line on the penalty invoice when this subscription is paused for non-payment. Leave empty to disable penalties for this plan.',
    )
    monthly_classes_limit = fields.Integer(
        string='Monthly Classes Limit',
        default=0,
        help='Maximum number of classes allowed per month for this plan. Use 0 for unlimited.',
    )
    description = fields.Text(string='Description')
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name='res.company',
        default=lambda self: self.env.company,
        required=True,
    )
