{
    'name': 'Gestión de Suscripciones',
    'version': '17.0.1.0.0',
    'category': 'Sales/Subscriptions',
    'summary': 'Manejo de suscripciones recurrentes, facturación y pagos desde Kanban',
    'description': """
        Módulo para la gestión de suscripciones recurrentes de usuarios.
        Incluye:
        - Vista Kanban de Suscriptores con drag & drop.
        - Generación automática de facturas vía Cron.
        - Penalizaciones automáticas por falta de pago.
        - Asistente de pagos rápidos con envío de factura por correo.
        - Recordatorios de pago automáticos por correo.
    """,
    'author': 'Esteban Viniegra | Eviniegra Software',
    'website': 'https://eviniegra.software',
    'depends': [
        'base',
        'mail',
        'account',
        'product',
    ],
    'data': [
        # 1. Seguridad (grupos primero, luego accesos)
        'security/subscription_security.xml',
        'security/ir.model.access.csv',

        # 2. Datos iniciales
        'data/subscription_data.xml',
        'data/mail_template.xml',
        'data/ir_cron.xml',

        # 3. Vistas y Wizards
        'wizard/subscription_payment_wizard_views.xml',
        'views/subscription_views.xml',
    ],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
