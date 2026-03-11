from odoo import api, fields, models, _
from odoo.exceptions import UserError

import logging

_logger = logging.getLogger(__name__)


class SubscriptionPaymentWizard(models.TransientModel):
    _name = 'subscription.payment.wizard'
    _description = 'Subscription Payment Wizard'

    subscriber_id = fields.Many2one(
        comodel_name='subscription.subscriber',
        string='Subscriber',
        required=True,
    )
    subscription_line_id = fields.Many2one(
        comodel_name='subscription.line',
        string='Subscription',
        required=True,
        domain="[('subscriber_id', '=', subscriber_id), "
               "('state', 'in', ['active', 'pending_payment', 'paused'])]",
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Invoice to Pay',
        required=True,
        domain="[('id', 'in', available_invoice_ids), "
               "('payment_state', '!=', 'paid'), "
               "('state', '=', 'posted')]",
    )
    available_invoice_ids = fields.Many2many(
        comodel_name='account.move',
        compute='_compute_available_invoices',
    )

    amount = fields.Monetary(
        string='Amount to Pay',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    payment_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Payment Journal',
        domain="[('type', 'in', ['bank', 'cash'])]",
        default=lambda self: self.env['account.journal'].search(
            [('type', 'in', ['bank', 'cash']),
             ('company_id', '=', self.env.company.id)],
            limit=1,
        ),
    )
    payment_date = fields.Date(
        string='Payment Date',
        default=fields.Date.today,
        required=True,
    )

    invoice_amount_residual = fields.Monetary(
        related='invoice_id.amount_residual',
        string='Invoice Balance',
        currency_field='currency_id',
    )
    invoice_ref = fields.Char(
        related='invoice_id.ref',
        string='Invoice Reference',
    )

    @api.depends('subscription_line_id')
    def _compute_available_invoices(self):
        for wizard in self:
            if wizard.subscription_line_id:
                wizard.available_invoice_ids = (
                    wizard.subscription_line_id.invoice_ids.filtered(
                        lambda inv: (
                            inv.state == 'posted'
                            and inv.payment_state != 'paid'
                        )
                    )
                )
            else:
                wizard.available_invoice_ids = False

    @api.onchange('invoice_id')
    def _onchange_invoice_id(self):
        if self.invoice_id:
            self.amount = self.invoice_id.amount_residual
            self.currency_id = self.invoice_id.currency_id

    def action_pay(self):
        """Register payment for the selected invoice and send it by email."""
        self.ensure_one()

        if not self.invoice_id:
            raise UserError(_("Please select an invoice to pay."))
        if not self.payment_journal_id:
            raise UserError(_("Please select a payment journal."))
        if self.amount <= 0:
            raise UserError(_("Payment amount must be greater than zero."))

        invoice = self.invoice_id

        # Create and post payment
        payment_vals = {
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'partner_id': invoice.partner_id.id,
            'amount': self.amount,
            'date': self.payment_date,
            'journal_id': self.payment_journal_id.id,
            'ref': invoice.name,
            'currency_id': self.currency_id.id,
        }

        payment = self.env['account.payment'].create(payment_vals)
        payment.action_post()

        # Reconcile payment with invoice
        receivable_lines = (
            payment.move_id.line_ids + invoice.line_ids
        ).filtered(
            lambda l: l.account_id.reconcile and not l.reconciled
        )
        if receivable_lines:
            receivable_lines.reconcile()

        _logger.info(
            "Payment %s registered for invoice %s (amount: %s)",
            payment.name, invoice.name, self.amount,
        )

        # Send invoice by email after payment
        self._send_paid_invoice_email(invoice)

        # Reactivate subscription line if all invoices are paid
        line = self.subscription_line_id
        unpaid = line.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.payment_state != 'paid'
        )
        if not unpaid and line.state in ('pending_payment', 'paused'):
            line.write({
                'state': 'active',
                'overdue_since': False,
            })
            line.subscriber_id._recompute_state()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payment Registered'),
                'message': _('Payment of %s %s registered for invoice %s. '
                             'The invoice has been sent by email.') % (
                    self.amount, self.currency_id.name, invoice.name,
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _send_paid_invoice_email(self, invoice):
        """Send paid invoice by email to the subscriber."""
        try:
            template = self.env.ref(
                'subscription_management.email_template_invoice_paid'
            )
            template.send_mail(invoice.id, force_send=False)
            _logger.info("Sent paid invoice email for %s", invoice.name)
        except Exception as e:
            _logger.error("Error sending paid invoice email: %s", e)
