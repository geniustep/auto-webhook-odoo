# -*- coding: utf-8 -*-

from odoo import models, api  # pyright: ignore[reportMissingImports]
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    """طلبات المبيعات"""
    _name = 'sale.order'
    _inherit = ['sale.order', 'webhook.mixin']
    _description = 'Sales Order with Webhook Tracking'


class ProductTemplate(models.Model):
    """قوالب المنتجات"""
    _name = 'product.template'
    _inherit = ['product.template', 'webhook.mixin']
    _description = 'Product Template with Webhook Tracking'


class ProductCategory(models.Model):
    """فئات المنتجات"""
    _name = 'product.category'
    _inherit = ['product.category', 'webhook.mixin']
    _description = 'Product Category with Webhook Tracking'


class ResPartner(models.Model):
    """العملاء والموردين"""
    _name = 'res.partner'
    _inherit = ['res.partner', 'webhook.mixin']
    _description = 'Partner with Webhook Tracking'


class AccountMove(models.Model):
    """الفواتير والقيود المحاسبية"""
    _name = 'account.move'
    _inherit = ['account.move', 'webhook.mixin']
    _description = 'Account Move with Webhook Tracking'


class AccountJournal(models.Model):
    """دفاتر اليومية"""
    _name = 'account.journal'
    _inherit = ['account.journal', 'webhook.mixin']
    _description = 'Account Journal with Webhook Tracking'


class HrExpense(models.Model):
    """مصروفات الموظفين"""
    _name = 'hr.expense'
    _inherit = ['hr.expense', 'webhook.mixin']
    _description = 'HR Expense with Webhook Tracking'


class StockPicking(models.Model):
    """عمليات النقل والمخزون"""
    _name = 'stock.picking'
    _inherit = ['stock.picking', 'webhook.mixin']
    _description = 'Stock Picking with Webhook Tracking'


class PurchaseOrder(models.Model):
    """طلبات الشراء"""
    _name = 'purchase.order'
    _inherit = ['purchase.order', 'webhook.mixin']
    _description = 'Purchase Order with Webhook Tracking'


class HrEmployee(models.Model):
    """الموظفين"""
    _name = 'hr.employee'
    _inherit = ['hr.employee', 'webhook.mixin']
    _description = 'HR Employee with Webhook Tracking'


# ===== نماذج إضافية (اختيارية - يتم تفعيلها فقط إذا كانت موجودة) =====
# هذه النماذج قد لا تكون متوفرة في جميع قواعد البيانات
# يمكن إلغاء التعليق عنها إذا كانت الموديلات المطلوبة مثبتة

class StockMove(models.Model):
    """حركات المخزون"""
    _name = 'stock.move'
    _inherit = ['stock.move', 'webhook.mixin']
    _description = 'Stock Move with Webhook Tracking'


class AccountPayment(models.Model):
    """المدفوعات"""
    _name = 'account.payment'
    _inherit = ['account.payment', 'webhook.mixin']
    _description = 'Account Payment with Webhook Tracking'


class CrmLead(models.Model):
    """الفرص التجارية"""
    _name = 'crm.lead'
    _inherit = ['crm.lead', 'webhook.mixin']
    _description = 'CRM Lead with Webhook Tracking'


# class ProjectTask(models.Model):
#     """مهام المشاريع"""
#     _name = 'project.task'
#     _inherit = ['project.task', 'webhook.mixin']
#     _description = 'Project Task with Webhook Tracking'


# class HrAttendance(models.Model):
#     """الحضور والانصراف"""
#     _name = 'hr.attendance'
#     _inherit = ['hr.attendance', 'webhook.mixin']
#     _description = 'HR Attendance with Webhook Tracking'