import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SubscriptionPaymentWizard(models.TransientModel):
    _name = 'subscription.payment.wizard'
    _description = 'Subscription Payment Wizard'

    subscriber_id = fields.Many2one(
        comodel_name='subscription.subscriber',
        string='Subscriber',
        required=True,
        default=lambda self: self.env.context.get('default_subscriber_id'),
        readonly=True,
    )
    subscription_id = fields.Many2one(
        comodel_name='subscription.subscription',
        string='Subscription',
        domain="[('subscriber_id', '=', subscriber_id), ('state', 'in', ('active', 'pending_payment', 'paused'))]",
        required=True,
    )
    invoice_id = fields.Many2one(
        comodel_name='account.move',
        string='Invoice to Pay',
        domain="[('subscription_id', '=', subscription_id), ('payment_state', 'in', ('not_paid', 'partial')), ('state', '=', 'posted'), ('move_type', '=', 'out_invoice')]",
        required=True,
    )
    amount_residual = fields.Monetary(
        string='Amount Due',
        currency_field='currency_id',
        related='invoice_id.amount_residual',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='invoice_id.currency_id',
        readonly=True,
    )
    invoice_date = fields.Date(
        string='Invoice Date',
        related='invoice_id.invoice_date',
        readonly=True,
    )
    invoice_date_due = fields.Date(
        string='Due Date',
        related='invoice_id.invoice_date_due',
        readonly=True,
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Payment Journal',
        domain="[('type', 'in', ['bank', 'cash'])]",
        required=True,
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

    @api.onchange('subscriber_id')
    def _onchange_subscriber_id(self):
        self.subscription_id = False
        self.invoice_id = False

    @api.onchange('subscription_id')
    def _onchange_subscription_id(self):
        self.invoice_id = False
        if self.subscription_id:
            pending = self.env['account.move'].search([
                ('subscription_id', '=', self.subscription_id.id),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('state', '=', 'posted'),
                ('move_type', '=', 'out_invoice'),
            ], order='invoice_date asc', limit=1)
            self.invoice_id = pending

    def action_register_payment(self):
        self.ensure_one()
        invoice = self.invoice_id
        if not invoice:
            raise UserError(_('No invoice selected.'))
        if invoice.payment_state == 'paid':
            raise UserError(_('This invoice is already fully paid.'))

        # Delegate to Odoo's standard payment register wizard so that
        # reconciliation and outstanding accounts are handled correctly
        # regardless of the chart of accounts in use.
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=invoice.ids,
        ).create({
            'payment_date': self.payment_date,
            'journal_id': self.journal_id.id,
            'amount': invoice.amount_residual,
        })
        payment_register.action_create_payments()

        # Refresh invoice state from DB before sending confirmation
        invoice.invalidate_recordset(['payment_state'])

        # Send invoice confirmation by email
        self._send_payment_confirmation(invoice)

        # Restore subscription to active if all invoices are now paid
        subscription = self.subscription_id
        if subscription.state in ('pending_payment', 'paused'):
            remaining_unpaid = self.env['account.move'].search_count([
                ('subscription_id', '=', subscription.id),
                ('payment_state', 'in', ('not_paid', 'partial')),
                ('state', '=', 'posted'),
                ('move_type', '=', 'out_invoice'),
            ])
            if not remaining_unpaid:
                subscription.write({'state': 'active', 'pending_since': False})
                subscription._refresh_subscriber_states()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Payment Registered'),
                'message': _('Payment of %s registered. Invoice sent by email.') % invoice.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    def _send_payment_confirmation(self, invoice):
        """Send invoice by email after payment is confirmed."""
        template = self.env.ref(
            'odoo_subscription_manager.email_template_payment_confirmation',
            raise_if_not_found=False,
        )
        if template and invoice.partner_id.email:
            try:
                template.send_mail(invoice.id, force_send=True)
            except Exception:
                _logger.exception(
                    "Error sending payment confirmation email for invoice %s.", invoice.name
                )
