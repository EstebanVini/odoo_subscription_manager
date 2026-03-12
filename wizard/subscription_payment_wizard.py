from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SubscriptionPaymentWizard(models.TransientModel):
    _name = 'subscription.payment.wizard'
    _description = 'Wizard de Pago Rápido de Suscripción'

    subscriber_id = fields.Many2one('subscription.subscriber', required=True)
    invoice_id = fields.Many2one(
        'account.move', 
        string='Factura a Pagar', 
        domain="[('subscription_id.subscriber_id', '=', subscriber_id), ('state', '=', 'posted'), ('payment_state', 'in', ['not_paid', 'partial'])]",
        required=True
    )
    journal_id = fields.Many2one('account.journal', string='Método de Pago', domain="[('type', 'in', ('bank', 'cash'))]", required=True)
    amount = fields.Monetary(string='Monto', related='invoice_id.amount_residual')
    currency_id = fields.Many2one(related='invoice_id.currency_id')

    def action_pay(self):
        self.ensure_one()
        if not self.invoice_id:
            raise UserError(_("Debes seleccionar una factura."))

        # 1. Registrar el pago usando la API del módulo de contabilidad
        payment_register = self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=self.invoice_id.ids,
        ).create({
            'journal_id': self.journal_id.id,
            'amount': self.amount,
            'payment_date': fields.Date.context_today(self),
        })
        payment_register._create_payments()

        # 2. Enviar la factura pagada por correo automáticamente
        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        if template:
            self.invoice_id.with_context(force_send=True).message_post_with_template(template.id)

        return {'type': 'ir.actions.act_window_close'}