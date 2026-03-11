from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, Command, _
from odoo.exceptions import UserError, ValidationError

import logging

_logger = logging.getLogger(__name__)


class SubscriptionLine(models.Model):
    _name = 'subscription.line'
    _description = 'Subscription Line'
    _inherit = ['mail.thread']
    _order = 'subscriber_id, sequence'

    name = fields.Char(
        string='Description',
        compute='_compute_name',
        store=True,
    )
    sequence = fields.Integer(default=10)

    subscriber_id = fields.Many2one(
        comodel_name='subscription.subscriber',
        string='Subscriber',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        related='subscriber_id.partner_id',
        store=True,
        string='Partner',
    )
    plan_id = fields.Many2one(
        comodel_name='subscription.plan',
        string='Subscription Plan',
        required=True,
        tracking=True,
    )

    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('active', 'Active'),
            ('pending_payment', 'Pending Payment'),
            ('paused', 'Paused'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )

    start_date = fields.Date(
        string='Start Date',
        default=fields.Date.today,
        required=True,
        tracking=True,
    )
    next_invoice_date = fields.Date(
        string='Next Invoice Date',
        tracking=True,
        help='Date when the next invoice will be automatically generated.',
    )
    end_date = fields.Date(
        string='End Date',
        tracking=True,
        help='Leave empty for an indefinite subscription.',
    )

    # === OVERDUE / PENALTY CONFIG === #
    grace_days = fields.Integer(
        string='Grace Days',
        default=0,
        help='Number of days after due date before the subscription is paused '
             'and a penalty is applied. Set 0 to use global setting.',
    )
    penalty_amount = fields.Monetary(
        string='Penalty Amount',
        default=0.0,
        currency_field='currency_id',
        help='Penalty charged when grace period expires. '
             'Set 0 to use global setting.',
    )
    reminder_days_before = fields.Integer(
        string='Reminder Days Before',
        default=0,
        help='Send payment reminder N days before due date. '
             'Set 0 to use global setting.',
    )

    currency_id = fields.Many2one(
        related='plan_id.currency_id',
        store=True,
    )
    company_id = fields.Many2one(
        related='subscriber_id.company_id',
        store=True,
    )

    # === INVOICE LINK === #
    invoice_ids = fields.Many2many(
        comodel_name='account.move',
        relation='subscription_line_invoice_rel',
        column1='subscription_line_id',
        column2='invoice_id',
        string='Invoices',
        copy=False,
    )
    invoice_count = fields.Integer(
        compute='_compute_invoice_count',
    )
    last_invoice_date = fields.Date(
        string='Last Invoice Date',
        copy=False,
    )

    overdue_since = fields.Date(
        string='Overdue Since',
        copy=False,
        help='Date since the subscription has an unpaid invoice past due.',
    )
    last_reminder_sent = fields.Date(
        string='Last Reminder Sent',
        copy=False,
        help='Date when the last payment reminder email was sent.',
    )

    @api.depends('subscriber_id.partner_id.name', 'plan_id.name')
    def _compute_name(self):
        for record in self:
            partner = record.subscriber_id.partner_id.name or ''
            plan = record.plan_id.name or ''
            record.name = f"{partner} - {plan}" if partner and plan else (
                partner or plan or _('New Subscription')
            )

    def _compute_invoice_count(self):
        for record in self:
            record.invoice_count = len(record.invoice_ids)

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for record in self:
            if record.end_date and record.start_date > record.end_date:
                raise ValidationError(
                    _("End date must be after the start date.")
                )

    # === ACTIONS === #
    def action_activate(self):
        """Activate the subscription line and set next invoice date."""
        for record in self:
            if not record.next_invoice_date:
                record.next_invoice_date = record.start_date
            record.state = 'active'
            record.overdue_since = False
        return True

    def action_cancel(self):
        for record in self:
            record.state = 'cancelled'
        self._recompute_subscriber_states()
        return True

    def action_view_invoices(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id(
            'account.action_move_out_invoice_type'
        )
        if len(self.invoice_ids) > 1:
            action['domain'] = [('id', 'in', self.invoice_ids.ids)]
        elif len(self.invoice_ids) == 1:
            action['views'] = [(
                self.env.ref('account.view_move_form').id, 'form'
            )]
            action['res_id'] = self.invoice_ids.id
        else:
            action['domain'] = [('id', '=', False)]
        return action

    # === INVOICE GENERATION === #
    def _get_effective_grace_days(self):
        """Return grace days: line-level override or global setting."""
        self.ensure_one()
        if self.grace_days > 0:
            return self.grace_days
        return int(self.env['ir.config_parameter'].sudo().get_param(
            'subscription_management.default_grace_days', '7'
        ))

    def _get_effective_penalty_amount(self):
        """Return penalty amount: line-level override or global setting."""
        self.ensure_one()
        if self.penalty_amount > 0:
            return self.penalty_amount
        return float(self.env['ir.config_parameter'].sudo().get_param(
            'subscription_management.default_penalty_amount', '0'
        ))

    def _get_effective_reminder_days(self):
        """Return reminder days before: line-level override or global setting."""
        self.ensure_one()
        if self.reminder_days_before > 0:
            return self.reminder_days_before
        return int(self.env['ir.config_parameter'].sudo().get_param(
            'subscription_management.default_reminder_days_before', '3'
        ))

    def _compute_next_period_date(self, from_date):
        """Compute the next billing date based on the plan interval."""
        self.ensure_one()
        plan = self.plan_id
        if plan.interval_type == 'daily':
            return from_date + relativedelta(days=plan.interval_count)
        elif plan.interval_type == 'weekly':
            return from_date + relativedelta(weeks=plan.interval_count)
        elif plan.interval_type == 'monthly':
            return from_date + relativedelta(months=plan.interval_count)
        elif plan.interval_type == 'yearly':
            return from_date + relativedelta(years=plan.interval_count)
        return from_date + relativedelta(months=1)

    def _generate_invoice(self):
        """Generate an invoice for this subscription line."""
        self.ensure_one()
        if not self.subscriber_id.partner_id:
            _logger.warning(
                "Subscription line %s has no partner, skipping invoice.",
                self.id,
            )
            return self.env['account.move']

        product = self.plan_id.product_id
        if not product:
            product = self.env.ref(
                'subscription_management.product_subscription_default',
                raise_if_not_found=False,
            )
        if not product:
            raise UserError(
                _("No invoicing product configured for plan '%s'. "
                  "Please set a product on the plan or configure the "
                  "default subscription product.") % self.plan_id.name
            )

        period_start = self.next_invoice_date
        period_end = self._compute_next_period_date(period_start) - relativedelta(days=1)

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.subscriber_id.partner_id.id,
            'invoice_date': period_start,
            'invoice_date_due': period_start,
            'invoice_origin': self.subscriber_id.name,
            'ref': _('%(sub)s - %(plan)s (%(start)s to %(end)s)') % {
                'sub': self.subscriber_id.name,
                'plan': self.plan_id.name,
                'start': period_start,
                'end': period_end,
            },
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': _('%(plan)s - Period %(start)s to %(end)s') % {
                    'plan': self.plan_id.name,
                    'start': period_start,
                    'end': period_end,
                },
                'quantity': 1,
                'price_unit': self.plan_id.amount,
            })],
        }

        invoice = self.env['account.move'].sudo().create(invoice_vals)
        invoice.action_post()

        self.write({
            'invoice_ids': [Command.link(invoice.id)],
            'last_invoice_date': period_start,
            'next_invoice_date': self._compute_next_period_date(period_start),
            'last_reminder_sent': False,
        })

        _logger.info(
            "Generated invoice %s for subscription line %s",
            invoice.name, self.id,
        )
        return invoice

    def _generate_penalty_invoice(self):
        """Generate a penalty invoice for overdue subscription."""
        self.ensure_one()
        penalty = self._get_effective_penalty_amount()
        if penalty <= 0:
            return self.env['account.move']

        product = self.env.ref(
            'subscription_management.product_subscription_penalty',
            raise_if_not_found=False,
        )
        if not product:
            product = self.plan_id.product_id or self.env.ref(
                'subscription_management.product_subscription_default',
                raise_if_not_found=False,
            )

        if not product:
            _logger.warning("No penalty product found, skipping penalty invoice.")
            return self.env['account.move']

        invoice_vals = {
            'move_type': 'out_invoice',
            'partner_id': self.subscriber_id.partner_id.id,
            'invoice_date': fields.Date.today(),
            'invoice_date_due': fields.Date.today(),
            'invoice_origin': self.subscriber_id.name,
            'ref': _('Penalty - %s') % self.name,
            'invoice_line_ids': [Command.create({
                'product_id': product.id,
                'name': _('Late payment penalty - %s') % self.plan_id.name,
                'quantity': 1,
                'price_unit': penalty,
            })],
        }

        invoice = self.env['account.move'].sudo().create(invoice_vals)
        invoice.action_post()
        self.invoice_ids = [Command.link(invoice.id)]

        _logger.info(
            "Generated penalty invoice %s for subscription line %s (amount: %s)",
            invoice.name, self.id, penalty,
        )
        return invoice

    # === CRON METHODS === #
    @api.model
    def _cron_generate_invoices(self):
        """Generate invoices for all active subscription lines due today."""
        _logger.info("Cron: Generating subscription invoices")
        today = fields.Date.today()
        lines = self.search([
            ('state', '=', 'active'),
            ('next_invoice_date', '<=', today),
        ])
        _logger.info("Found %d subscription lines to invoice", len(lines))

        for line in lines:
            try:
                # Check if end_date passed
                if line.end_date and line.end_date < today:
                    line.state = 'cancelled'
                    line._recompute_subscriber_states()
                    continue
                line._generate_invoice()
            except Exception as e:
                _logger.error(
                    "Error generating invoice for line %s: %s", line.id, e
                )

    @api.model
    def _cron_check_overdue_payments(self):
        """Check for unpaid invoices past due and update subscription states."""
        _logger.info("Cron: Checking overdue subscription payments")
        today = fields.Date.today()

        # Find active lines that have posted unpaid invoices past due
        active_lines = self.search([
            ('state', '=', 'active'),
        ])

        for line in active_lines:
            overdue_invoices = line.invoice_ids.filtered(
                lambda inv: (
                    inv.state == 'posted'
                    and inv.payment_state != 'paid'
                    and inv.invoice_date_due
                    and inv.invoice_date_due < today
                )
            )
            if overdue_invoices:
                line.write({
                    'state': 'pending_payment',
                    'overdue_since': min(
                        overdue_invoices.mapped('invoice_date_due')
                    ),
                })
                _logger.info(
                    "Subscription line %s moved to pending_payment", line.id
                )

        # Recompute subscriber states
        active_lines.mapped('subscriber_id')._recompute_state()

    @api.model
    def _cron_check_grace_period(self):
        """Check pending_payment lines and pause if grace period expired."""
        _logger.info("Cron: Checking grace periods")
        today = fields.Date.today()

        pending_lines = self.search([
            ('state', '=', 'pending_payment'),
            ('overdue_since', '!=', False),
        ])

        for line in pending_lines:
            grace_days = line._get_effective_grace_days()
            grace_deadline = line.overdue_since + relativedelta(days=grace_days)

            if today >= grace_deadline:
                _logger.info(
                    "Grace period expired for line %s, pausing and applying penalty",
                    line.id,
                )
                line.state = 'paused'

                # Generate penalty invoice
                try:
                    line._generate_penalty_invoice()
                except Exception as e:
                    _logger.error(
                        "Error generating penalty invoice for line %s: %s",
                        line.id, e,
                    )

                # Notify subscriber
                try:
                    template = self.env.ref(
                        'subscription_management.email_template_subscription_paused'
                    )
                    template.send_mail(line.id, force_send=False)
                except Exception as e:
                    _logger.error("Error sending pause notification: %s", e)

        # Recompute subscriber states
        pending_lines.mapped('subscriber_id')._recompute_state()

    @api.model
    def _cron_send_payment_reminders(self):
        """Send payment reminders before due date and overdue reminders."""
        _logger.info("Cron: Sending payment reminders")
        today = fields.Date.today()

        # --- PRE-DUE REMINDERS ---
        active_lines = self.search([
            ('state', '=', 'active'),
            ('next_invoice_date', '!=', False),
            ('last_reminder_sent', '=', False),
        ])

        for line in active_lines:
            reminder_days = line._get_effective_reminder_days()
            if reminder_days <= 0:
                continue
            reminder_date = line.next_invoice_date - relativedelta(
                days=reminder_days
            )
            if today >= reminder_date:
                try:
                    template = self.env.ref(
                        'subscription_management.email_template_payment_reminder'
                    )
                    template.send_mail(line.id, force_send=False)
                    line.last_reminder_sent = today
                    _logger.info(
                        "Sent pre-due reminder for line %s", line.id
                    )
                except Exception as e:
                    _logger.error("Error sending pre-due reminder: %s", e)

        # --- OVERDUE REMINDERS ---
        pending_lines = self.search([
            ('state', '=', 'pending_payment'),
        ])

        reminder_interval = int(
            self.env['ir.config_parameter'].sudo().get_param(
                'subscription_management.overdue_reminder_interval_days', '3'
            )
        )

        for line in pending_lines:
            if line.last_reminder_sent:
                next_reminder = line.last_reminder_sent + relativedelta(
                    days=reminder_interval
                )
                if today < next_reminder:
                    continue
            try:
                template = self.env.ref(
                    'subscription_management.email_template_overdue_reminder'
                )
                template.send_mail(line.id, force_send=False)
                line.last_reminder_sent = today
                _logger.info("Sent overdue reminder for line %s", line.id)
            except Exception as e:
                _logger.error("Error sending overdue reminder: %s", e)

    # === HELPERS === #
    def _recompute_subscriber_states(self):
        """Trigger subscriber state recomputation."""
        self.mapped('subscriber_id')._recompute_state()
