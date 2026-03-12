# Asegúrate de incluir esta primera línea
from odoo import models, fields, api

class AccountMove(models.Model):
    _inherit = 'account.move'
    
    subscription_id = fields.Many2one(
        'subscription.record', 
        string='Suscripción Origen', 
        index=True
    )