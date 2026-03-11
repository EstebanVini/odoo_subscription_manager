{
    'name': 'Subscription Management',
    'version': '17.0.1.0.0',
    'category': 'Sales/Subscriptions',
    'summary': 'Manage recurring subscriptions with automated invoicing and payments',
    'description': """
Subscription Management
=======================
Manage recurring subscriptions for portal users with:
- Multiple subscription plans per subscriber
- Kanban view with configurable stages
- Automated invoice generation
- Quick payment from subscriber view
- Automatic email on payment
- Overdue payment tracking with grace periods and penalties
- Payment reminder emails before and after due date
    """,
    'author': 'Custom',
    'website': '',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'mail',
        'account',
        'portal',
        'product',
    ],
    'data': [
        # Security first
        'security/subscription_management_security.xml',
        'security/ir.model.access.csv',
        # Data
        'data/sequence_data.xml',
        'data/product_data.xml',
        'data/mail_template_data.xml',
        'data/cron_data.xml',
        # Views
        'views/subscription_plan_views.xml',
        'views/subscription_subscriber_views.xml',
        'views/subscription_line_views.xml',
        'views/res_config_settings_views.xml',
        'views/menuitems.xml',
        # Wizards
        'wizards/subscription_payment_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'auto_install': False,
}
