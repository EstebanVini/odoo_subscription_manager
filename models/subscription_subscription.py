import logging
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_INTERVAL_DELTA = {
    'daily': lambda n: relativedelta(days=n),
    'weekly': lambda n: relativedelta(weeks=n),
    'monthly': lambda n: relativedelta(months=n),
    'yearly': lambda n: relativedelta(years=n),
}


class SubscriptionSubscription(models.Model):
    _name = 'subscription.subscription'
    _description = 'Subscription'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date_start desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    subscriber_id = fields.Many2one(
        comodel_name='subscription.subscriber',
        string='Subscriber',
        required=True,
        ondelete='cascade',
        index=True,
    )
    plan_id = fields.Many2one(
        comodel_name='subscription.plan',
        string='Plan',
        required=True,
        tracking=True,
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
    date_start = fields.Date(
        string='Start Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    date_end = fields.Date(string='End Date', tracking=True)
    date_next_invoice = fields.Date(
        string='Next Invoice Date',
        index=True,
        tracking=True,
    )
    pending_since = fields.Date(
        string='Pending Since',
        help='Date when the subscription entered pending payment status',
    )

    price = fields.Monetary(
        string='Price',
        currency_field='currency_id',
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='plan_id.currency_id',
        store=True,
    )

    invoice_ids = fields.One2many(
        comodel_name='account.move',
        inverse_name='subscription_id',
        string='Invoices',
        domain=[('move_type', '=', 'out_invoice')],
    )
    invoice_count = fields.Integer(
        string='Invoices',
        compute='_compute_invoice_count',
    )
    unpaid_invoice_count = fields.Integer(
        string='Unpaid Invoices',
        compute='_compute_unpaid_invoice_count',
    )

    company_id = fields.Many2one(
        comodel_name='res.company',
        related='subscriber_id.company_id',
        store=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        related='subscriber_id.partner_id',
        store=True,
    )

    @api.depends('invoice_ids')
    def _compute_invoice_count(self):
        for rec in self:
            rec.invoice_count = len(rec.invoice_ids)

    def _compute_unpaid_invoice_count(self):
        for rec in self:
            rec.unpaid_invoice_count = self.env['account.move'].search_count([
                ('subscription_id', '=', rec.id),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('state', '=', 'posted'),
                ('move_type', '=', 'out_invoice'),
            ])

    @api.onchange('plan_id')
    def _onchange_plan_id(self):
        if self.plan_id:
            self.price = self.plan_id.price

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'subscription.subscription'
                ) or _('New')
            # Set price from plan if not provided
            if not vals.get('price') and vals.get('plan_id'):
                plan = self.env['subscription.plan'].browse(vals['plan_id'])
                vals['price'] = plan.price
        return super().create(vals_list)

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'finished'):
                raise UserError(
                    _("Cannot delete subscription '%s'. Only draft or finished subscriptions can be deleted.")
                    % rec.name
                )
        return super().unlink()

    # ── State Actions ────────────────────────────────────────────────────────

    def action_activate(self):
        for rec in self.filtered(lambda r: r.state in ('draft', 'paused')):
            if not rec.date_next_invoice:
                rec.date_next_invoice = rec.date_start
            rec.write({'state': 'active', 'pending_since': False})
        self._refresh_subscriber_states()

    def action_pause(self):
        self.filtered(lambda r: r.state not in ('finished',)).write({'state': 'paused'})
        self._refresh_subscriber_states()

    def action_finish(self):
        self.write({'state': 'finished', 'date_end': fields.Date.today()})
        self._refresh_subscriber_states()

    def action_reset_draft(self):
        self.filtered(lambda r: r.state == 'paused').write({
            'state': 'draft',
            'pending_since': False,
        })
        self._refresh_subscriber_states()

    def _refresh_subscriber_states(self):
        subscribers = self.mapped('subscriber_id')
        for subscriber in subscribers:
            subscriber._compute_and_set_state()

    # ── Invoice Actions ──────────────────────────────────────────────────────

    def action_view_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Invoices'),
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('subscription_id', '=', self.id)],
            'context': {'default_subscription_id': self.id},
        }

    def action_open_payment_wizard(self):
        """Open the payment wizard pre-loaded with this subscription and its oldest unpaid invoice."""
        self.ensure_one()
        oldest_unpaid = self.env['account.move'].search([
            ('subscription_id', '=', self.id),
            ('payment_state', 'in', ('not_paid', 'partial')),
            ('state', '=', 'posted'),
            ('move_type', '=', 'out_invoice'),
        ], order='invoice_date asc', limit=1)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Register Payment'),
            'res_model': 'subscription.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_subscriber_id': self.subscriber_id.id,
                'default_subscription_id': self.id,
                'default_invoice_id': oldest_unpaid.id if oldest_unpaid else False,
                'active_id': self.id,
                'active_model': self._name,
            },
        }

    def _generate_invoice(self):
        """Create and post the invoice for the current billing period."""
        self.ensure_one()
        if not self.subscriber_id.partner_id:
            _logger.warning("Subscription %s has no partner, skipping invoice.", self.name)
            return False

        due_date = self.date_next_invoice  # capture before advancing

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.subscriber_id.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': due_date,
            'subscription_id': self.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': self.plan_id.product_id.id if self.plan_id.product_id else False,
                'name': self.plan_id.name,
                'quantity': 1,
                'price_unit': self.price,
            })],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        self._advance_next_invoice_date()
        _logger.info("Generated invoice %s for subscription %s.", invoice.name, self.name)
        return invoice

    def _advance_next_invoice_date(self):
        """Move date_next_invoice forward by the plan interval."""
        self.ensure_one()
        if not self.date_next_invoice or not self.plan_id:
            return
        rule = self.plan_id.recurring_rule_type
        interval = self.plan_id.recurring_interval
        delta_fn = _INTERVAL_DELTA.get(rule)
        if delta_fn:
            self.date_next_invoice = self.date_next_invoice + delta_fn(interval)

    def _create_penalty_invoice(self, penalty_product):
        """Create a penalty invoice using the plan's penalty product."""
        self.ensure_one()
        if not self.subscriber_id.partner_id or not penalty_product:
            return False

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.subscriber_id.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': fields.Date.today(),
            'subscription_id': self.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': penalty_product.id,
                'name': penalty_product.name,
                'quantity': 1,
                'price_unit': penalty_product.lst_price,
            })],
        }
        invoice = self.env['account.move'].create(invoice_vals)
        invoice.action_post()
        self.message_post(
            body=_('Penalty invoice %s created for late payment.') % invoice.name
        )
        return invoice

    # ── Cron Methods ─────────────────────────────────────────────────────────

    @api.model
    def _cron_generate_invoices(self):
        """Generate invoices for active subscriptions whose billing date has arrived."""
        _logger.info("Cron: generating subscription invoices.")
        today = fields.Date.today()
        subscriptions = self.search([
            ('state', '=', 'active'),
            ('date_next_invoice', '<=', today),
        ])
        _logger.info("Found %d subscriptions to invoice.", len(subscriptions))
        for sub in subscriptions:
            try:
                with self.env.cr.savepoint():
                    sub._generate_invoice()
            except Exception:
                _logger.exception("Error generating invoice for subscription %s.", sub.name)

    @api.model
    def _cron_check_overdue(self):
        """Move active subscriptions with overdue unpaid invoices to pending_payment."""
        _logger.info("Cron: checking overdue subscription invoices.")
        today = fields.Date.today()
        active_subs = self.search([('state', '=', 'active')])
        moved = self.env['subscription.subscription']

        for sub in active_subs:
            overdue = sub.invoice_ids.filtered(
                lambda inv: (
                    inv.state == 'posted'
                    and inv.payment_state in ('not_paid', 'partial')
                    and inv.invoice_date_due
                    and inv.invoice_date_due < today
                )
            )
            if overdue:
                sub.write({'state': 'pending_payment', 'pending_since': today})
                moved |= sub
                # Send overdue notification
                template = self.env.ref(
                    'odoo_subscription_manager.email_template_overdue_notification',
                    raise_if_not_found=False,
                )
                if template and sub.subscriber_id.partner_id.email:
                    try:
                        template.send_mail(sub.id, force_send=False)
                    except Exception:
                        _logger.exception("Error sending overdue email for subscription %s.", sub.name)

        if moved:
            moved._refresh_subscriber_states()
        _logger.info("Cron overdue check: %d subscriptions moved to pending_payment.", len(moved))

    @api.model
    def _cron_check_grace_period(self):
        """Pause subscriptions that have exceeded the grace period and charge penalty."""
        _logger.info("Cron: checking grace period for pending subscriptions.")
        today = fields.Date.today()
        grace_days = int(
            self.env['ir.config_parameter'].sudo().get_param('subscription.grace_days', '5')
        )

        pending_subs = self.search([
            ('state', '=', 'pending_payment'),
            ('pending_since', '!=', False),
        ])
        moved = self.env['subscription.subscription']

        for sub in pending_subs:
            days_overdue = (today - sub.pending_since).days
            if days_overdue >= grace_days:
                sub.write({'state': 'paused'})
                moved |= sub
                penalty_product = sub.plan_id.penalty_product_id
                if penalty_product:
                    try:
                        with self.env.cr.savepoint():
                            sub._create_penalty_invoice(penalty_product)
                    except Exception:
                        _logger.exception("Error creating penalty invoice for subscription %s.", sub.name)

        if moved:
            moved._refresh_subscriber_states()
        _logger.info("Cron grace period: %d subscriptions paused.", len(moved))

    @api.model
    def _cron_send_payment_reminders(self):
        """Send payment reminder emails X days before the next invoice date."""
        send_reminders = self.env['ir.config_parameter'].sudo().get_param(
            'subscription.send_reminders', 'True'
        )
        if send_reminders.lower() in ('false', '0', ''):
            _logger.info("Cron reminders: disabled by configuration, skipping.")
            return

        _logger.info("Cron: sending payment reminders.")
        today = fields.Date.today()
        reminder_days = int(
            self.env['ir.config_parameter'].sudo().get_param('subscription.reminder_days', '3')
        )
        reminder_date = today + relativedelta(days=reminder_days)

        subscriptions = self.search([
            ('state', '=', 'active'),
            ('date_next_invoice', '=', reminder_date),
        ])
        template = self.env.ref(
            'odoo_subscription_manager.email_template_payment_reminder',
            raise_if_not_found=False,
        )
        if not template:
            return

        count = 0
        for sub in subscriptions:
            if sub.subscriber_id.partner_id.email:
                try:
                    template.send_mail(sub.id, force_send=False)
                    count += 1
                except Exception:
                    _logger.exception("Error sending reminder for subscription %s.", sub.name)

        _logger.info("Cron reminders: %d emails queued.", count)
