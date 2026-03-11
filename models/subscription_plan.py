from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SubscriptionPlan(models.Model):
    _name = 'subscription.plan'
    _description = 'Subscription Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, name'

    name = fields.Char(
        string='Plan Name',
        required=True,
        tracking=True,
    )
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    description = fields.Html(string='Description')

    amount = fields.Monetary(
        string='Amount',
        required=True,
        tracking=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    interval_type = fields.Selection(
        selection=[
            ('daily', 'Day(s)'),
            ('weekly', 'Week(s)'),
            ('monthly', 'Month(s)'),
            ('yearly', 'Year(s)'),
        ],
        string='Billing Interval',
        default='monthly',
        required=True,
        tracking=True,
    )
    interval_count = fields.Integer(
        string='Interval Count',
        default=1,
        required=True,
        help='Number of intervals between each billing cycle.',
    )

    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Invoicing Product',
        help='Product used when generating invoices for this plan.',
        tracking=True,
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    subscriber_count = fields.Integer(
        string='Subscribers',
        compute='_compute_subscriber_count',
    )

    @api.depends()
    def _compute_subscriber_count(self):
        line_data = self.env['subscription.line'].read_group(
            domain=[('plan_id', 'in', self.ids), ('state', '!=', 'cancelled')],
            fields=['plan_id'],
            groupby=['plan_id'],
        )
        mapped = {d['plan_id'][0]: d['plan_id_count'] for d in line_data}
        for record in self:
            record.subscriber_count = mapped.get(record.id, 0)

    @api.constrains('interval_count')
    def _check_interval_count(self):
        for record in self:
            if record.interval_count < 1:
                raise ValidationError(
                    _("The interval count must be at least 1.")
                )

    @api.constrains('amount')
    def _check_amount(self):
        for record in self:
            if record.amount <= 0:
                raise ValidationError(
                    _("The plan amount must be greater than zero.")
                )
