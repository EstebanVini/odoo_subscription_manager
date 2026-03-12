# models/subscription_record.py

from odoo import models, fields, api
from dateutil.relativedelta import relativedelta
from datetime import timedelta

class SubscriptionRecord(models.Model):
    _name = 'subscription.record'
    _description = 'Registro de Suscripción'

    # ==========================================================
    # 1. CAMPOS RELACIONALES Y BÁSICOS (¡Obligatorios!)
    # ==========================================================
    subscriber_id = fields.Many2one(
        'subscription.subscriber', 
        string='Suscriptor',
        required=True, 
        ondelete='cascade'
    )
    product_id = fields.Many2one('product.product', string='Plan/Servicio', required=True)
    price = fields.Float('Precio', related='product_id.list_price', readonly=False)
    
    # ==========================================================
    # 2. LÓGICA DE RECURRENCIA
    # ==========================================================
    next_invoice_date = fields.Date('Próxima Fecha', required=True, default=fields.Date.today, index=True)
    interval = fields.Integer('Intervalo', default=1)
    interval_type = fields.Selection([
        ('days', 'Días'), 
        ('weeks', 'Semanas'), 
        ('months', 'Meses'), 
        ('years', 'Años')
    ], string='Tipo de Intervalo', default='months', required=True)
    
    # ==========================================================
    # 3. PENALIZACIONES
    # ==========================================================
    penalty_days = fields.Integer('Días para penalización', default=5)
    penalty_amount = fields.Float('Monto Penalización', default=0.0)

    # ==========================================================
    # 4. RECORDATORIOS (Nuevos campos)
    # ==========================================================
    reminder_days = fields.Integer(
        string='Días de pre-aviso', 
        default=3, 
        help="Días antes de la fecha de cobro para enviar el correo recordatorio."
    )
    last_reminder_date = fields.Date(
        string='Último Recordatorio Enviado', 
        readonly=True, 
        copy=False
    )

    # ==========================================================
    # MÉTODOS Y LÓGICA (Unificados)
    # ==========================================================
    @api.model
    def _cron_process_subscriptions(self):
        """Método principal único llamado por el Cron."""
        # 1. Procesar notificaciones preventivas
        self._process_upcoming_reminders()
        # 2. Generar facturas
        self._process_invoicing()
        # 3. Evaluar impagos, penalizar y notificar atrasos
        self._process_unpaid_and_penalties()

    def _process_upcoming_reminders(self):
        """Envía correos N días antes del corte."""
        today = fields.Date.today()
        template = self.env.ref('odoo_subscription_management.email_template_upcoming_payment', raise_if_not_found=False)
        
        if not template:
            return

        active_stage = self.env.ref('odoo_subscription_management.stage_active', raise_if_not_found=False)
        domain = [('subscriber_id.stage_id', '=', active_stage.id)] if active_stage else []
        subscriptions = self.search(domain)

        for sub in subscriptions:
            target_reminder_date = sub.next_invoice_date - timedelta(days=sub.reminder_days)
            
            if today >= target_reminder_date and (not sub.last_reminder_date or sub.last_reminder_date < target_reminder_date):
                template.send_mail(sub.id, force_send=False)
                sub.last_reminder_date = today

    def _process_invoicing(self):
        """Genera facturas para suscripciones cuya fecha de corte es hoy o anterior."""
        today = fields.Date.today()
        
        active_stage = self.env.ref('odoo_subscription_management.stage_active', raise_if_not_found=False)
        domain = [
            ('next_invoice_date', '<=', today),
            ('subscriber_id.stage_id', '=', active_stage.id) if active_stage else ('id', '!=', False)
        ]
        subscriptions_to_invoice = self.search(domain)
        
        if not subscriptions_to_invoice:
            return

        invoice_vals_list = []
        for sub in subscriptions_to_invoice:
            invoice_vals_list.append({
                'move_type': 'out_invoice',
                'partner_id': sub.subscriber_id.partner_id.id,
                'invoice_date': today,
                'subscription_id': sub.id,
                'invoice_line_ids': [(0, 0, {
                    'product_id': sub.product_id.id,
                    'quantity': 1,
                    'price_unit': sub.price,
                    'name': f"Suscripción: {sub.product_id.name} - Periodo {today.strftime('%Y-%m-%d')}"
                })],
            })

        if invoice_vals_list:
            moves = self.env['account.move'].create(invoice_vals_list)
            moves.action_post()
            
            for sub in subscriptions_to_invoice:
                sub._compute_next_invoice_date()

    def _compute_next_invoice_date(self):
        """Calcula la próxima fecha usando relativedelta."""
        self.ensure_one()
        interval_args = {self.interval_type: self.interval}
        self.next_invoice_date = self.next_invoice_date + relativedelta(**interval_args)

    def _process_unpaid_and_penalties(self):
        """Evalúa facturas impagas, cambia etapas, genera penalizaciones y envía recordatorios."""
        today = fields.Date.today()
        pending_stage = self.env.ref('odoo_subscription_management.stage_pending', raise_if_not_found=False)
        paused_stage = self.env.ref('odoo_subscription_management.stage_paused', raise_if_not_found=False)
        late_template = self.env.ref('odoo_subscription_management.email_template_late_payment', raise_if_not_found=False)

        unpaid_moves = self.env['account.move'].search([
            ('subscription_id', '!=', False),
            ('state', '=', 'posted'),
            ('payment_state', 'in', ('not_paid', 'partial')),
        ])

        penalty_invoice_vals = []
        
        for move in unpaid_moves:
            sub = move.subscription_id
            days_late = (today - move.invoice_date_due).days if move.invoice_date_due else 0

            # Enviar aviso de atraso
            if days_late == 1 and late_template:
                late_template.send_mail(sub.id, force_send=False) 

            # Penalizar y Pausar
            if days_late >= sub.penalty_days:
                if paused_stage and sub.subscriber_id.stage_id != paused_stage:
                    sub.subscriber_id.stage_id = paused_stage.id
                    
                    if sub.penalty_amount > 0 and not self._penalty_already_exists(sub, today):
                        penalty_invoice_vals.append(self._prepare_penalty_vals(sub, today))
            
            # Pasar a Pendiente
            elif days_late > 0:
                if pending_stage and sub.subscriber_id.stage_id not in (pending_stage, paused_stage):
                    sub.subscriber_id.stage_id = pending_stage.id

        if penalty_invoice_vals:
            penalty_moves = self.env['account.move'].create(penalty_invoice_vals)
            penalty_moves.action_post()

    def _prepare_penalty_vals(self, subscription, date):
        """Retorna el diccionario de valores para la factura de penalidad"""
        penalty_product = self.env.ref('odoo_subscription_management.product_penalty', raise_if_not_found=False)
        return {
            'move_type': 'out_invoice',
            'partner_id': subscription.subscriber_id.partner_id.id,
            'invoice_date': date,
            'subscription_id': subscription.id,
            'invoice_line_ids': [(0, 0, {
                'product_id': penalty_product.id if penalty_product else False,
                'name': 'Penalización por falta de pago',
                'quantity': 1,
                'price_unit': subscription.penalty_amount,
            })],
        }

    def _penalty_already_exists(self, subscription, current_date):
        """Verifica si ya se emitió una penalidad este mes."""
        domain = [
            ('subscription_id', '=', subscription.id),
            ('invoice_date', '>=', current_date.replace(day=1)),
            ('invoice_line_ids.name', 'ilike', 'Penalización')
        ]
        return self.env['account.move'].search_count(domain) > 0