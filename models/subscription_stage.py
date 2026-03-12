from odoo import models, fields

class SubscriptionStage(models.Model):
    _name = 'subscription.stage'
    _description = 'Estado de Suscripción'
    _order = 'sequence, id'

    name = fields.Char('Nombre del Estado', required=True, translate=True)
    sequence = fields.Integer('Secuencia', default=10)
    is_active = fields.Boolean('Es estado activo', default=True)
    fold = fields.Boolean('Plegado en Kanban', default=False)