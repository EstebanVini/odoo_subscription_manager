#models/subscription_subscriber.py

from odoo import models, fields, api

class SubscriptionSubscriber(models.Model):
    _name = 'subscription.subscriber'
    _description = 'Gestión de Suscriptor'
    _inherit = ['mail.thread', 'mail.activity.mixin'] # Para historial de correos y notas

    name = fields.Char(related='partner_id.name', store=True)
    partner_id = fields.Many2one(
        'res.partner', 
        string='Usuario Portal / Cliente', 
        required=True, 
        domain="[('is_company', '=', False)]",
        tracking=True
    )
    user_id = fields.Many2one(
        'res.users', 
        string='Usuario Vinculado', 
        compute='_compute_user_id', 
        store=True
    )
    stage_id = fields.Many2one(
        'subscription.stage', 
        string='Estado', 
        group_expand='_read_group_stage_ids',
        default=lambda self: self._default_stage_id(),
        tracking=True
    )
    subscription_ids = fields.One2many(
        'subscription.record', 
        'subscriber_id', 
        string='Suscripciones'
    )
    
    @api.depends('partner_id')
    def _compute_user_id(self):
        for rec in self:
            # Enlaza con el usuario del portal si existe
            rec.user_id = self.env['res.users'].search([('partner_id', '=', rec.partner_id.id)], limit=1)

    @api.model
    def _default_stage_id(self):
        return self.env['subscription.stage'].search([], limit=1)

    @api.model
    def _read_group_stage_ids(self, stages, domain, order):
        return self.env['subscription.stage'].search([])

    def action_open_payment_wizard(self):
        """Abre el wizard para pagar facturas desde la vista del suscriptor"""
        self.ensure_one()
        return {
            'name': 'Pagar Suscripción',
            'type': 'ir.actions.act_window',
            'res_model': 'subscription.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_subscriber_id': self.id},
        }