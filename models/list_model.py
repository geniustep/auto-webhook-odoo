from odoo import models  # type: ignore
from .webhook import WebhookMixin

class SaleOrder(models.Model):
    _name = 'sale.order'
    _inherit = ['sale.order', 'webhook.mixin']

# class ProductProduct(models.Model):
#     _name = 'product.product'
#     _inherit = ['product.product', 'webhook.mixin']
 
class ProductTemplate(models.Model):
    _name = 'product.template'
    _inherit = ['product.template', 'webhook.mixin']

class ProductCategory(models.Model):
    _name = 'product.category'
    _inherit = ['product.category', 'webhook.mixin']

class ResPartner(models.Model):
    _name = 'res.partner'
    _inherit = ['res.partner', 'webhook.mixin']

class AccountMove(models.Model):
    _name = 'account.move'
    _inherit = ['account.move', 'webhook.mixin']

class AccountJournal(models.Model):
    _name = 'account.journal'
    _inherit = ['account.journal', 'webhook.mixin']

class HrExpense(models.Model):
    _name = 'hr.expense'
    _inherit = ['hr.expense', 'webhook.mixin']

class StockPicking(models.Model):
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'webhook.mixin']

class PurchaseOrder(models.Model):
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'webhook.mixin']

class HrEmployee(models.Model):
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'webhook.mixin']
