from odoo import api, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('subscription_create_portal_user'):
            portal_group = self.env.ref('base.group_portal')
            res['groups_id'] = [(6, 0, [portal_group.id])]
        return res
