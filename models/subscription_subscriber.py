import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

# Priority order for computing subscriber state from subscription states
_STATE_PRIORITY = {
    'paused': 4,
    'pending_payment': 3,
    'active': 2,
    'draft': 1,
    'finished': 0,
}


class SubscriptionSubscriber(models.Model):
    _name = 'subscription.subscriber'
    _description = 'Subscription Subscriber'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    name = fields.Char(
        string='Name',
        compute='_compute_name',
        store=True,
        index='trigram',
    )
    portal_user_id = fields.Many2one(
        comodel_name='res.users',
        string='Portal User',
        domain="[('share', '=', True)]",
        required=True,
        tracking=True,
        index=True,
        help='Portal user linked to this subscriber',
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Contact',
        compute='_compute_partner_id',
        store=True,
        tracking=True,
        index=True,
    )
    phone = fields.Char(
        string='Teléfono',
        related='partner_id.phone',
        readonly=False,
    )
    email = fields.Char(
        string='Correo electrónico',
        related='partner_id.email',
        readonly=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('pending_payment', 'Pending Payment'),
            ('paused', 'Paused'),
            ('finished', 'Finished'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        index=True,
    )
    subscription_ids = fields.One2many(
        comodel_name='subscription.subscription',
        inverse_name='subscriber_id',
        string='Subscriptions',
    )
    subscription_count = fields.Integer(
        string='Subscriptions',
        compute='_compute_subscription_count',
    )
    invoice_count = fields.Integer(
        string='Invoices',
        compute='_compute_invoice_count',
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one(
        comodel_name='res.company',
        default=lambda self: self.env.company,
        required=True,
        index=True,
    )
    note = fields.Text(string='Internal Notes')

    @api.depends('portal_user_id')
    def _compute_partner_id(self):
        """Derive partner_id from the portal user's associated partner."""
        for rec in self:
            rec.partner_id = rec.portal_user_id.partner_id if rec.portal_user_id else False

    @api.depends('partner_id', 'partner_id.name')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.partner_id.name if rec.partner_id else _('New Subscriber')

    @api.depends('subscription_ids')
    def _compute_subscription_count(self):
        for rec in self:
            rec.subscription_count = len(rec.subscription_ids)

    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = self.env['account.move'].search_count([
                ('subscription_id.subscriber_id', '=', rec.id),
                ('move_type', '=', 'out_invoice'),
            ])

    def _compute_and_set_state(self):
        """Update subscriber state based on the worst-case subscription state."""
        for rec in self:
            active_subs = rec.subscription_ids.filtered(lambda s: s.state != 'finished')

            if not active_subs:
                all_finished = rec.subscription_ids and all(
                    s.state == 'finished' for s in rec.subscription_ids
                )
                if all_finished:
                    rec.state = 'finished'
                continue

            # Pick the highest-priority (worst) state
            worst_state = max(
                active_subs.mapped('state'),
                key=lambda s: _STATE_PRIORITY.get(s, 0),
            )
            if rec.state != worst_state:
                rec.state = worst_state

    def action_open_payment_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Register Payment'),
            'res_model': 'subscription.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subscriber_id': self.id,
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [
                ('subscription_id.subscriber_id', '=', self.id),
                ('move_type', '=', 'out_invoice'),
            ],
        }

    def action_view_subscriptions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Subscriptions'),
            'res_model': 'subscription.subscription',
            'view_mode': 'tree,form',
            'domain': [('subscriber_id', '=', self.id)],
            'context': {'default_subscriber_id': self.id},
        }

    def _ensure_portal_user(self):
        """Create a portal user for this subscriber's partner if none exists."""
        self.ensure_one()
        if self.portal_user_id:
            return
        if not self.partner_id.email:
            _logger.warning(
                "Subscriber %s has no email on partner — skipping portal user creation.",
                self.name,
            )
            return

        # Reuse existing portal user for this partner if any
        existing = self.env['res.users'].search([
            ('partner_id', '=', self.partner_id.id),
            ('share', '=', True),
            ('active', '=', True),
        ], limit=1)
        if existing:
            self.portal_user_id = existing
            return

        portal_group = self.env.ref('base.group_portal')
        user = self.env['res.users'].with_context(no_reset_password=True).sudo().create({
            'name': self.partner_id.name,
            'login': self.partner_id.email,
            'email': self.partner_id.email,
            'partner_id': self.partner_id.id,
            'groups_id': [(6, 0, [portal_group.id])],
        })
        self.portal_user_id = user
        _logger.info("Created portal user %s for subscriber %s.", user.login, self.name)

    def action_activate(self):
        for rec in self:
            rec._ensure_portal_user()
            rec.subscription_ids.filtered(
                lambda s: s.state == 'draft'
            ).action_activate()
