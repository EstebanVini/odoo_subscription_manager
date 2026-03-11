from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class SubscriptionSubscriber(models.Model):
    _name = 'subscription.subscriber'
    _description = 'Subscription Subscriber'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name asc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    active = fields.Boolean(default=True)

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Subscriber (Portal User)',
        required=True,
        tracking=True,
        domain="[('user_ids', '!=', False)]",
        help='Portal user linked to this subscriber.',
    )
    partner_email = fields.Char(
        related='partner_id.email',
        string='Email',
        readonly=True,
    )
    partner_phone = fields.Char(
        related='partner_id.phone',
        string='Phone',
        readonly=True,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('pending_payment', 'Pending Payment'),
            ('paused', 'Paused'),
            ('done', 'Finalized'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
        group_expand='_expand_states',
    )

    subscription_line_ids = fields.One2many(
        comodel_name='subscription.line',
        inverse_name='subscriber_id',
        string='Subscriptions',
        copy=True,
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    notes = fields.Html(string='Internal Notes')

    # === COMPUTED FIELDS === #
    subscription_count = fields.Integer(
        string='Active Subscriptions',
        compute='_compute_subscription_count',
        store=True,
    )
    total_monthly_amount = fields.Monetary(
        string='Total Monthly Amount',
        compute='_compute_total_monthly_amount',
        store=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    invoice_count = fields.Integer(
        string='Invoices',
        compute='_compute_invoice_count',
    )
    pending_invoice_amount = fields.Monetary(
        string='Pending Amount',
        compute='_compute_pending_invoice_amount',
        currency_field='currency_id',
    )

    @api.model
    def _expand_states(self, states, domain, order):
        """Show all kanban states even when empty."""
        return [key for key, val in type(self).state.selection]

    @api.depends('subscription_line_ids', 'subscription_line_ids.state')
    def _compute_subscription_count(self):
        for record in self:
            record.subscription_count = len(
                record.subscription_line_ids.filtered(
                    lambda l: l.state == 'active'
                )
            )

    @api.depends('subscription_line_ids', 'subscription_line_ids.plan_id.amount',
                 'subscription_line_ids.state')
    def _compute_total_monthly_amount(self):
        for record in self:
            total = 0.0
            for line in record.subscription_line_ids.filtered(
                lambda l: l.state == 'active'
            ):
                total += line.plan_id.amount or 0.0
            record.total_monthly_amount = total

    def _compute_invoice_count(self):
        for record in self:
            invoices = record.subscription_line_ids.mapped('invoice_ids')
            record.invoice_count = len(invoices)

    def _compute_pending_invoice_amount(self):
        for record in self:
            invoices = record.subscription_line_ids.mapped('invoice_ids').filtered(
                lambda inv: inv.payment_state != 'paid' and inv.state == 'posted'
            )
            record.pending_invoice_amount = sum(invoices.mapped('amount_residual'))

    # === CRUD === #
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'subscription.subscriber'
                ) or _('New')
        return super().create(vals_list)

    def unlink(self):
        for record in self:
            if record.state not in ('draft', 'done'):
                raise UserError(
                    _("Cannot delete a subscriber in state '%s'. "
                      "Please finalize or reset to draft first.") % record.state
                )
        return super().unlink()

    # === ACTIONS === #
    def action_activate(self):
        """Activate the subscriber and all draft subscription lines."""
        for record in self:
            record.state = 'active'
            for line in record.subscription_line_ids.filtered(
                lambda l: l.state == 'draft'
            ):
                line.action_activate()
        return True

    def action_pause(self):
        for record in self:
            record.state = 'paused'
            for line in record.subscription_line_ids.filtered(
                lambda l: l.state in ('active', 'pending_payment')
            ):
                line.state = 'paused'
        return True

    def action_finalize(self):
        for record in self:
            record.state = 'done'
            for line in record.subscription_line_ids.filtered(
                lambda l: l.state != 'cancelled'
            ):
                line.state = 'cancelled'
        return True

    def action_draft(self):
        for record in self:
            record.state = 'draft'
        return True

    def action_view_invoices(self):
        """Open all invoices linked to this subscriber."""
        self.ensure_one()
        invoices = self.subscription_line_ids.mapped('invoice_ids')
        action = self.env['ir.actions.act_window']._for_xml_id(
            'account.action_move_out_invoice_type'
        )
        if len(invoices) > 1:
            action['domain'] = [('id', 'in', invoices.ids)]
        elif len(invoices) == 1:
            action['views'] = [(
                self.env.ref('account.view_move_form').id, 'form'
            )]
            action['res_id'] = invoices.id
        else:
            action['domain'] = [('id', '=', False)]
        return action

    def action_open_payment_wizard(self):
        """Open the quick payment wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Register Payment'),
            'res_model': 'subscription.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subscriber_id': self.id,
            },
        }

    # === SUBSCRIBER STATE RECOMPUTATION === #
    def _recompute_state(self):
        """Recompute subscriber state based on subscription line states."""
        for record in self:
            if record.state == 'done':
                continue
            lines = record.subscription_line_ids.filtered(
                lambda l: l.state != 'cancelled'
            )
            if not lines:
                continue
            states = lines.mapped('state')
            if all(s == 'paused' for s in states):
                record.state = 'paused'
            elif any(s == 'pending_payment' for s in states):
                record.state = 'pending_payment'
            elif any(s == 'active' for s in states):
                record.state = 'active'
