# -*- coding: utf-8 -*-
# © 2016 Comunitea
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
from openerp import models, fields, api, exceptions, _


class AccountFiscalPoition(models.Model):

    _inherit = 'account.fiscal.position'

    magento_id = fields.Integer()


class AccountPaymentTerm(models.Model):

    _inherit = 'account.payment.term'

    magento_id = fields.Integer()
